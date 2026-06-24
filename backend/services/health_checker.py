"""
中转站网页探测服务
通过 Playwright 连接本地调试 Chrome 实例（9222 端口），
利用免登状态静默打开中转站后台，拦截 API 响应包，获取真实的余额、分组及倍率。
"""
import asyncio
import os
import socket
import subprocess
from datetime import datetime
from urllib.parse import urlparse
from playwright.async_api import async_playwright

CDP_URL = "http://127.0.0.1:9222"

BALANCE_KEYS = [
    "balance",
    "remain",
    "remain_balance",
    "remainBalance",
    "quota",
    "remain_quota",
    "remainQuota",
    "credit",
]

def _extract_balance(data, key_context=None):
    """递归提取 JSON 中的余额，并对 quota 进行自动换算"""
    if isinstance(data, dict):
        for key in BALANCE_KEYS:
            value = data.get(key)
            if isinstance(value, (int, float)):
                val = float(value)
                # One API / New API 中 1 美元 = 500000 quota
                if "quota" in key.lower() and val > 1000:
                    return val / 500000.0
                return val
            if isinstance(value, str):
                try:
                    val = float(value)
                    if "quota" in key.lower() and val > 1000:
                        return val / 500000.0
                    return val
                except ValueError:
                    pass
        for k, v in data.items():
            found = _extract_balance(v, k)
            if found is not None:
                return found
    elif isinstance(data, list):
        for item in data:
            found = _extract_balance(item, key_context)
            if found is not None:
                return found
    return None

def _extract_user_models(data):
    if isinstance(data, dict):
        models = data.get("models")
        if isinstance(models, list):
            if models and isinstance(models[0], dict):
                return [m.get("id") or m.get("model") or m.get("name") for m in models if isinstance(m, dict)]
            return [str(m) for m in models]
        for value in data.values():
            found = _extract_user_models(value)
            if found:
                return found
    elif isinstance(data, list):
        for item in data:
            found = _extract_user_models(item)
            if found:
                return found
    return []

def _extract_user_group(data):
    if isinstance(data, dict):
        group = data.get("group")
        if isinstance(group, str) and group:
            return group
        nested_data = data.get("data")
        if isinstance(nested_data, dict):
            group = nested_data.get("group")
            if isinstance(group, str) and group:
                return group
        for value in data.values():
            found = _extract_user_group(value)
            if found:
                return found
    return None

def _extract_price_map(data):
    if isinstance(data, list):
        return {
            item.get("model") or item.get("id") or item.get("name"): item
            for item in data
            if isinstance(item, dict) and (item.get("model") or item.get("id") or item.get("name"))
        }

    if isinstance(data, dict):
        for key in ("data", "items", "models", "model_prices", "prices"):
            value = data.get(key)
            if isinstance(value, list):
                return _extract_price_map(value)
            if isinstance(value, dict):
                nested = _extract_price_map(value)
                if nested:
                    return nested

        guessed = {
            key: value
            for key, value in data.items()
            if isinstance(value, dict) and any(k in value for k in ("model", "id", "name", "price", "ratio", "multiplier"))
        }
        if guessed:
            return guessed

    return {}

def _get_web_url(station: dict) -> str:
    """清洗出站点的网页控制台/官网主站 URL"""
    if station.get("website_url"):
        url = station["website_url"].rstrip("/")
    else:
        base_url = station["base_url"]
        parsed = urlparse(base_url)
        # 默认不剥离任何 api.，保持子域名登录 Cookie 生效
        host = parsed.netloc.lower() or base_url.lower()
        scheme = parsed.scheme or "https"
        url = f"{scheme}://{host}"

    url_lower = url.lower()
    # 针对特异性非标官网，直接重映射到展示余额的真实后台路由，省去自适应探测的超时折腾
    if "deepseek.com" in url_lower:
        return "https://platform.deepseek.com/usage"
    if "aicards.shop" in url_lower or "xiaoleai.team" in url_lower:
        return "https://aicards.shop/user/dashboard"
    if "anyrouter.top" in url_lower:
        return "https://anyrouter.top/console"
    if "freemodel.dev" in url_lower:
        return "https://freemodel.dev/dashboard/usage"
    if "qlcodeapi.com" in url_lower:
        return "https://api.qlcodeapi.com/keys"
    if "tygzs.cn" in url_lower:
        return "https://sub2api.tygzs.cn/keys"
    if "riyuexy.cc" in url_lower:
        return "https://svip.riyuexy.cc/keys"
    if "qlhazycoder.top" in url_lower:
        return "https://api.qlhazycoder.top/wallet"
    if "twgom.com" in url_lower:
        return "https://api.twgom.com/wallet"
    if "baiyuan.cc.cd" in url_lower:
        return "https://baiyuan.cc.cd/wallet"
    if "cheapyun.cc.cd" in url_lower:
        return "https://cheapyun.cc.cd/console"
    if "prorisehub.com" in url_lower:
        return "https://newapi.prorisehub.com/wallet"
    if "vsllm.com" in url_lower:
        return "https://vsllm.com/console/topup?tab=topup"
    if "proxy-gls.de5.net" in url_lower:
        return "https://api-public.proxy-gls.de5.net/wallet"
        
    return url


async def check_station_health_with_playwright(context, station: dict) -> dict:
    """利用 Chrome 实例的登录态，静默访问网页并拦截/主动同源 Fetch API 响应以抓取真实数据，支持 DOM 兜底。"""
    base_url = station["base_url"]
    parsed_url = urlparse(base_url)
    
    # 1. 针对英伟达做短路，免检测
    if "nvidia.com" in parsed_url.netloc.lower():
        return {
            "status": "online",
            "status_reason": "英伟达官方免费接口",
            "response_time_ms": 0,
            "error": None,
            "checked_at": datetime.now().isoformat(),
            "available_models": [],
            "price_map": {},
            "balance": None,
            "groups_info": None,
        }

    # 2. 清洗出真正的 Web 页面 URL
    web_url = _get_web_url(station)

    result = {
        "status": "unknown",
        "status_reason": "未知，需验证",
        "response_time_ms": None,
        "error": None,
        "checked_at": datetime.now().isoformat(),
        "available_models": [],
        "price_map": {},
        "balance": None,
        "groups_info": None,
    }

    pricing_data = None
    user_data = None
    
    # 拦截网络响应
    async def handle_response(response):
        nonlocal pricing_data, user_data
        url = response.url.lower()
        if "/api/pricing" in url or "/api/token/prices" in url:
            try:
                pricing_data = await response.json()
            except Exception:
                pass
        if "/api/user/self" in url or "/api/user/info" in url or "/api/user/dashboard" in url:
            try:
                user_data = await response.json()
            except Exception:
                pass

    page = await context.new_page()
    page.on("response", handle_response)

    start_time = datetime.now()
    try:
        # 3. 导航逻辑：如果是纯域名，默认拼入 /dashboard 触发控制台；如果是带有路径的精确控制台 URL，则直接直达
        parsed_web = urlparse(web_url)
        path = parsed_web.path.strip("/")
        if path:
            goto_url = web_url
        else:
            goto_url = f"{web_url.rstrip('/')}/dashboard"
            
        await page.goto(goto_url, timeout=10000, wait_until="domcontentloaded")
        
        # 4. 判断是否进入了 Chrome 错误页面 (ERR_NAME_NOT_RESOLVED 等)
        title = await page.title()
        body_text = await page.evaluate("() => document.body.innerText")
        
        err_keywords = [
            "无法访问此网站", "找不到服务器", "未连接", "ERR_NAME_NOT_RESOLVED",
            "ERR_CONNECTION_REFUSED", "ERR_CONNECTION_TIMED_OUT", "ERR_NAME_RESOLUTION_FAILED",
            "连接失败"
        ]
        is_chrome_error = any(kw in title or kw in body_text for kw in err_keywords)
        if is_chrome_error:
            raise Exception(f"Chrome 网页加载失败: {title or '域名无法解析'}")

        await asyncio.sleep(2.0)

        # 4.0 智能等待页面关键元素或已登录菜单渲染（自适应轮询，最长等待 8 秒）
        for _ in range(16):
            text = await page.evaluate("() => document.body.innerText")
            has_login_elements = ("登录" in text or "Sign in" in text or "OIDC" in text or "dc.hhhl.cc" in text or "LinuxDO" in text)
            has_logged_in = ("数据看板" in text or "控制台" in text or "API令牌" in text or "个人设置" in text or "钱包" in text or "令牌管理" in text)
            if has_login_elements or has_logged_in:
                break
            await asyncio.sleep(0.5)


        # 4.1 仅在确认为登录页时，自动提交预填充表单 / 勾选同意条款并点击 OIDC 登录
        cur_text = await page.evaluate("() => document.body.innerText")
        has_password_input = await page.evaluate("() => !!document.querySelector('input[type=\"password\"]')")
        has_logged_in = any(kw in cur_text for kw in ["数据看板", "个人设置", "API令牌", "令牌管理", "控制台", "钱包", "使用日志"])
        is_login_page = has_password_input or (not has_logged_in and any(kw in cur_text for kw in ["登录", "Sign in", "OIDC", "dc.hhhl.cc", "LinuxDO"]))

        if is_login_page:
            try:
                interacted = await page.evaluate("""async () => {
                    let actionTaken = false;
                    // 1. 尝试寻找并勾选用户协议复选框
                    const checkboxes = Array.from(document.querySelectorAll('input[type="checkbox"], [role="checkbox"]'));
                    for (const cb of checkboxes) {
                        const parentText = cb.parentElement ? cb.parentElement.innerText : '';
                        const labelText = cb.getAttribute('aria-label') || '';
                        const html = cb.outerHTML || '';
                        if (['agree', 'consent', '协议', '政策', '同意', 'legal-consent'].some(kw => 
                            parentText.includes(kw) || labelText.includes(kw) || html.includes(kw)
                        )) {
                            const isChecked = cb.checked || cb.getAttribute('aria-checked') === 'true';
                            if (!isChecked) {
                                cb.click();
                                actionTaken = true;
                            }
                        }
                    }

                    // 2. 检查是否有已填充用户名密码的表单，且尚未提交过
                    const u = document.querySelector('input[type="text"], input[placeholder*="用户名"], input[placeholder*="邮箱"], input[placeholder*="username"], input[placeholder*="email"]');
                    const p = document.querySelector('input[type="password"]');
                    if (u && u.value && p && p.value) {
                        const submitBtn = Array.from(document.querySelectorAll('button, input[type="submit"]')).find(el => {
                            const txt = (el.innerText || el.value || '').trim();
                            return txt.includes('登录') || txt.includes('Sign in') || txt.includes('Log in') || el.type === 'submit';
                        });
                        if (submitBtn) {
                            submitBtn.click();
                            return true;
                        }
                    }

                    // 3. 检查是否有 OIDC/dc.hhhl.cc 登录按钮，如果有就点击
                    const oidcBtn = Array.from(document.querySelectorAll('button, a')).find(el => {
                        const text = el.innerText || '';
                        return text.includes('dc.hhhl.cc') || text.includes('OIDC') || text.includes('使用 OIDC 继续');
                    });
                    if (oidcBtn) {
                        oidcBtn.removeAttribute('disabled');
                        oidcBtn.removeAttribute('data-disabled');
                        oidcBtn.click();
                        actionTaken = true;
                    }
                    return actionTaken;
                }""")
                
                if interacted:
                    # 循环等待直到页面 url 发生变化或者变成了 dc.hhhl.cc，最多等待 8 秒
                    for _ in range(16):
                        if "dc.hhhl.cc" in page.url:
                            break
                        await asyncio.sleep(0.5)
                    
                    # 4.2 自动点击第三方 OIDC 授权页的确认按钮 (针对 dc.hhhl.cc 的 miauth / oidc)
                    if "dc.hhhl.cc" in page.url:
                        # 等待授权确认按钮加载出来，最多等 6 秒
                        for _ in range(12):
                            status = await page.evaluate("""() => {
                                const approveKeywords = ['Approve', '允许', '授权', '同意', 'Confirm', '确认授权', '继续'];
                                const buttons = Array.from(document.querySelectorAll('button, a, input[type="submit"]'));
                                const approveBtn = buttons.find(btn => {
                                    const text = (btn.innerText || btn.value || btn.textContent || '').trim();
                                    return approveKeywords.some(kw => text.includes(kw));
                                });
                                if (approveBtn) {
                                    // 如果按钮处于 disabled 状态，说明还没登录或者还没准备好，我们继续等待
                                    if (approveBtn.disabled || approveBtn.getAttribute('data-disabled') !== null) {
                                        return 'disabled';
                                    }
                                    approveBtn.click();
                                    return 'clicked';
                                }
                                return 'not_found';
                            }""")
                            if status == 'clicked':
                                break
                            await asyncio.sleep(0.5)
                            
                        # 点击完授权按钮后，等待重定向回原站，最多等 8 秒
                        for _ in range(16):
                            if "dc.hhhl.cc" not in page.url:
                                break
                            await asyncio.sleep(0.5)
            except Exception as e:
                # 自动登录为辅助功能，不阻断正常抓取
                print(f"[health_checker] 自动登录/授权流程异常: {e}")


        # 5. 双轨制抓取逻辑：同源后台 Fetch (极度稳定防广告公告干扰)
        fetched_data = await page.evaluate("""async () => {
            let resData = { user: null, pricing: null, groups: null };
            let headers = {};
            try {
                const userStr = localStorage.getItem('user');
                if (userStr) {
                    const u = JSON.parse(userStr);
                    if (u && u.token) {
                        headers['Authorization'] = 'Bearer ' + u.token;
                    }
                }
                const token = localStorage.getItem('token') || localStorage.getItem('auth_token');
                if (token) {
                    headers['Authorization'] = 'Bearer ' + token;
                }
            } catch(e) {}

            // 1. 同源 fetch /api/user/self 或新系统的 /api/v1/auth/me
            try {
                const r = await fetch('/api/user/self', { headers, credentials: 'same-origin' });
                if (r.ok) {
                    resData.user = await r.json();
                } else {
                    const r2 = await fetch('/api/user/info', { headers, credentials: 'same-origin' });
                    if (r2.ok) {
                        resData.user = await r2.json();
                    } else {
                        const r3 = await fetch('/api/v1/auth/me', { headers, credentials: 'same-origin' });
                        if (r3.ok) resData.user = await r3.json();
                    }
                }
            } catch(e) {}

            // 2. 同源 fetch /api/pricing
            try {
                const r = await fetch('/api/pricing', { credentials: 'same-origin' });
                if (r.ok) {
                    resData.pricing = await r.json();
                } else {
                    const r2 = await fetch('/api/token/prices', { credentials: 'same-origin' });
                    if (r2.ok) resData.pricing = await r2.json();
                }
            } catch(e) {}

            // 3. 同源 fetch /api/user/self/groups (New-API / One-API 分组)
            try {
                let userId = '';
                if (resData.user && resData.user.data && resData.user.data.id) {
                    userId = String(resData.user.data.id);
                } else {
                    const userStr = localStorage.getItem('user');
                    if (userStr) {
                        const u = JSON.parse(userStr);
                        if (u && u.id) userId = String(u.id);
                    }
                }
                
                let groupHeaders = { ...headers };
                if (userId) {
                    groupHeaders['new-api-user'] = userId;
                }
                const r = await fetch('/api/user/self/groups', { headers: groupHeaders, credentials: 'same-origin' });
                if (r.ok) {
                    resData.groups = await r.json();
                }
            } catch(e) {}

            // 4. 同源 fetch /api/v1/groups/available (Sub2API 系统分组)
            try {
                const r = await fetch('/api/v1/groups/available', { headers, credentials: 'same-origin' });
                if (r.ok) {
                    resData.sub2api_groups = await r.json();
                }
            } catch(e) {}
            
            return resData;
        }""")
        
        if fetched_data:
            if fetched_data.get("user") and not user_data:
                user_data = fetched_data["user"]
            if fetched_data.get("pricing") and not pricing_data:
                pricing_data = fetched_data["pricing"]

        result["response_time_ms"] = int((datetime.now() - start_time).total_seconds() * 1000)

        # 6. 处理截获到的数据
        # 6.1 余额提取
        if user_data:
            balance = _extract_balance(user_data)
            if balance is not None:
                result["balance"] = balance
            models = _extract_user_models(user_data)
            if models:
                result["available_models"] = models

        # 6.2 分组与倍率提取
        if pricing_data:
            price_map = _extract_price_map(pricing_data)
            if price_map:
                result["price_map"] = price_map

            group_ratio = pricing_data.get("group_ratio", {})
            usable_group = pricing_data.get("usable_group", {})
            if group_ratio:
                groups = {}
                for grp_id, grp_ratio in group_ratio.items():
                    grp_name = usable_group.get(grp_id) or grp_id
                    groups[grp_id] = {
                        "name": grp_name,
                        "ratio": float(grp_ratio)
                    }
                result["groups_info"] = groups

        # 6.2.2 从 /api/user/self/groups 提取真实分组与倍率 (New-API / One-API 特性)
        if fetched_data and fetched_data.get("groups"):
            groups_resp = fetched_data["groups"]
            if isinstance(groups_resp, dict) and groups_resp.get("success"):
                groups_data = groups_resp.get("data")
                if isinstance(groups_data, dict):
                    groups = {}
                    for grp_id, grp_info in groups_data.items():
                        if isinstance(grp_info, dict):
                            grp_name = grp_info.get("desc") or grp_id
                            grp_ratio = grp_info.get("ratio", 1.0)
                            groups[grp_id] = {
                                "name": grp_name,
                                "ratio": float(grp_ratio)
                            }
                    if groups:
                        result["groups_info"] = groups

        # 6.2.3 从 Sub2API 系统的 /api/v1/groups/available 提取真实分组与倍率
        if fetched_data and fetched_data.get("sub2api_groups"):
            sub2_resp = fetched_data["sub2api_groups"]
            if isinstance(sub2_resp, dict) and sub2_resp.get("code") == 0:
                groups_list = sub2_resp.get("data")
                if isinstance(groups_list, list):
                    groups = {}
                    for grp in groups_list:
                        if isinstance(grp, dict):
                            grp_name = grp.get("name")
                            grp_ratio = grp.get("rate_multiplier", 1.0)
                            if grp_name:
                                groups[grp_name] = {
                                    "name": grp_name,
                                    "ratio": float(grp_ratio) if grp_ratio is not None else 1.0
                                }
                    if groups:
                        result["groups_info"] = groups

        # 7. 判定在线状态与 DOM 正则解析兜底 (主要对应 DeepSeek 等官方站与复杂页面)
        # 只要 API 轨道未获得有效余额，即降级执行 DOM 提取进行数据补充
        if result["balance"] is None:
            dom_balance = await page.evaluate(r"""async () => {
                // 循环等待渲染，最多等 8 秒
                for (let i = 0; i < 40; i++) {
                    const text = document.body.innerText;
                    const hasPasswordInput = !!document.querySelector('input[type="password"]');
                    const hasLoggedInMenu = text.includes("数据看板") || 
                                            text.includes("个人设置") || 
                                            text.includes("API令牌") || 
                                            text.includes("令牌管理") || 
                                            text.includes("控制台") || 
                                            text.includes("钱包") || 
                                            text.includes("使用日志");
                    
                    // 判定是否是未登录状态的登录/注册界面
                    const isLoginPage = hasPasswordInput || 
                                        (!hasLoggedInMenu && (
                                            (text.includes("登录") || text.includes("Sign in")) && 
                                            (text.includes("注册") || text.includes("Register") || text.includes("OIDC") || text.includes("dc.hhhl.cc"))
                                        ));
                    if (isLoginPage) {
                        return null; // 未登录，直接退出，防止误提取广告宣传语如 "注册赠送 24 元额度"
                    }
                    
                    // 全局正则匹配，寻找并筛选真正的余额项，在数字后允许向后抓取 8 个字符以囊括可能存在的单位（如“小时”）用于排除逻辑
                    const regex = /(?:充值余额|可用余额|余额|可用额度|额度|义气值|积分|点数|可用点数|Balance|Quota|Credit)[\s\S]{0,15}?(?:¥|\$)?\s*([0-9,.]+)[\s\S]{0,8}/gi;
                    let match;
                    let foundBalance = null;
                    while ((match = regex.exec(text)) !== null) {
                        const fullText = match[0];
                        const valStr = match[1];
                        // 过滤常见的各种用量时间窗/限制等干扰数字
                        if (fullText.includes("小时") || fullText.includes("天") || fullText.includes("限制") || 
                            fullText.includes("hour") || fullText.includes("day") || fullText.includes("limit") ||
                            fullText.includes("重置") || fullText.includes("reset") || fullText.includes("窗口") ||
                            fullText.includes("window") || fullText.includes("上限") || fullText.includes("max")) {
                            continue;
                        }
                        foundBalance = valStr;
                        break;
                    }
                    if (foundBalance) {
                        return foundBalance;
                    }
                    await new Promise(r => setTimeout(r, 200));
                }
                return null;
            }""")
            if dom_balance:
                try:
                    result["balance"] = float(dom_balance.replace(",", ""))
                except Exception:
                    pass

        # 8. 最终判定在线状态和归类数据来源说明
        if result["balance"] is not None or pricing_data:
            result["status"] = "online"
            captured = []
            if pricing_data: captured.append("分组倍率")
            if result["balance"] is not None: captured.append("余额")
            
            # 判断余额的真正来源以精确标记
            is_api_balance = (result["balance"] is not None and user_data and _extract_balance(user_data) is not None)
            source_type = "API 抓取" if is_api_balance or (result["balance"] is None) else "DOM 提取"
            
            result["status_reason"] = f"已验证（{source_type}：{'、'.join(captured)}）"
        else:
            if title:
                result["status"] = "online"
                result["status_reason"] = "已验证：网页可访问"
            else:
                result["status"] = "unknown"
                result["status_reason"] = "未知，需验证（页面无响应）"

        # 6.3 兜底分组与倍率提取（根据 user_data 中的 group 字段或 online 状态）
        if not result["groups_info"]:
            user_group = None
            if user_data:
                user_group = _extract_user_group(user_data)
            
            # 默认倍率：如果 station 里有 cost_multiplier 则使用它，否则为 1.0
            default_ratio = station.get("cost_multiplier")
            base_url_lower = station.get("base_url", "").lower()
            if "xiaoleai.team" in base_url_lower or "aicards.shop" in base_url_lower:
                default_ratio = 0.2
            elif default_ratio is None or default_ratio <= 0:
                default_ratio = 1.0

            if user_group:
                result["groups_info"] = {
                    user_group: {
                        "name": user_group,
                        "ratio": default_ratio
                    }
                }
            elif result["status"] == "online":
                # 对于没有任何分组信息的 online 站点，默认生成 default 分组
                result["groups_info"] = {
                    "default": {
                        "name": "default",
                        "ratio": default_ratio
                    }
                }

    except Exception as exc:
        result["status"] = "error"
        result["status_reason"] = f"网页加载异常: {str(exc)}"
        result["error"] = str(exc)
    finally:
        # 如果是 online 状态但最终依然未获得有效余额，对其保存排查截图
        if result["status"] == "online" and result["balance"] is None:
            parsed = urlparse(base_url)
            host = parsed.netloc.lower() or base_url.lower()
            if "nvidia.com" not in host:
                try:
                    debug_dir = os.path.join(os.path.dirname(__file__), "..", "..", "data", "debug_screenshots")
                    os.makedirs(debug_dir, exist_ok=True)
                    screenshot_path = os.path.join(debug_dir, f"{host}_balance_none.png")
                    await page.screenshot(path=screenshot_path)
                    print(f"[health_checker] 站点 {host} 余额为 None 且为 online，已保存截图至: {screenshot_path}")
                except Exception as se:
                    print(f"[health_checker] 保存 debug 截图失败: {se}")
        await page.close()

    # Force 0.2x ratio override for xiaoleai.team / aicards.shop
    base_url_lower = station.get("base_url", "").lower()
    if "xiaoleai.team" in base_url_lower or "aicards.shop" in base_url_lower:
        if result.get("groups_info"):
            for grp in result["groups_info"].values():
                grp["ratio"] = 0.2

    return result

def is_port_open(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=0.8):
            return True
    except OSError:
        return False

def _find_chrome_path():
    paths = [
        "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
        "C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe",
        os.path.join(os.environ.get("PROGRAMFILES", "C:\\Program Files"), "Google\\Chrome\\Application\\chrome.exe"),
        os.path.join(os.environ.get("PROGRAMFILES(X86)", "C:\\Program Files (x86)"), "Google\\Chrome\\Application\\chrome.exe"),
        os.path.join(os.environ.get("LOCALAPPDATA", "C:\\Users\\Default\\AppData\\Local"), "Google\\Chrome\\Application\\chrome.exe")
    ]
    for p in paths:
        if os.path.exists(p):
            return p
    return None

async def check_all_stations(stations: list[dict], concurrency: int = 3) -> list[dict]:
    """并发检测所有站点，利用已启动的 Chrome 进行静默抓取。按 host 自动去重。"""
    # 1. 按照 base_url 的 host 进行去重
    unique_stations = {}
    for s in stations:
        parsed = urlparse(s["base_url"])
        host = parsed.netloc.lower() or s["base_url"].lower()
        if host not in unique_stations:
            unique_stations[host] = s

    unique_list = list(unique_stations.values())

    spawned_process = None
    async with async_playwright() as p:
        context = None
        is_connected_cdp = False
        try:
            # 优先检查 9222 端口，若开了就直接 CDP 连上，与桌面 Chrome 调试窗口共用
            if is_port_open("127.0.0.1", 9222):
                try:
                    browser = await p.chromium.connect_over_cdp(CDP_URL)
                    context = browser.contexts[0]
                    is_connected_cdp = True
                    print("[health_checker] Connected to existing Chrome via CDP (9222).")
                except Exception as cdp_err:
                    print(f"[health_checker] Failed connection over CDP: {cdp_err}, falling back to headless launch.")

            # 若 CDP 不可用，我们使用子进程后台启动无头 Chrome 实例并锁定在 9222，再以 CDP 连接
            if not context:
                chrome_path = _find_chrome_path()
                if not chrome_path:
                    raise Exception("在系统默认路径中未检测到 Chrome 浏览器，请确认已安装。")
                
                profile_dir = "A:\\ChromeDevToolsProfile"
                if not (os.path.exists("A:\\") or os.path.isdir("A:\\")):
                    profile_dir = os.path.expanduser("~/.ai-proxy-monitor/ChromeDevToolsProfile")

                cmd = [
                    chrome_path,
                    "--remote-debugging-port=9222",
                    f"--user-data-dir={profile_dir}",
                    "--headless",
                    "--disable-gpu",
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    "--disable-dev-shm-usage"
                ]
                # Windows 下通过 CREATE_NO_WINDOW (0x08000000) 静默启动子进程
                spawned_process = subprocess.Popen(
                    cmd, 
                    stdout=subprocess.DEVNULL, 
                    stderr=subprocess.DEVNULL,
                    creationflags=0x08000000
                )
                
                # 轮询等待端口响应
                for _ in range(40):
                    if is_port_open("127.0.0.1", 9222):
                        break
                    await asyncio.sleep(0.1)
                
                browser = await p.chromium.connect_over_cdp(CDP_URL)
                context = browser.contexts[0]
                is_connected_cdp = True
                print("[health_checker] Successfully spawned and connected to headless Chrome on 9222.")

        except Exception as e:
            # 降级处理
            print(f"[health_checker] 初始化检测上下文失败: {e}")
            fallback_reason = f"初始化检测浏览器失败: {str(e)}。若已打开其他调试版 Chrome，请关闭它或重试。"
            
            results = []
            for station in stations:
                results.append({
                    **station,
                    "status": "unknown",
                    "status_reason": fallback_reason,
                    "response_time_ms": None,
                    "error": fallback_reason,
                    "checked_at": datetime.now().isoformat(),
                    "available_models": [],
                    "price_map": {},
                    "balance": None,
                    "groups_info": None,
                })
            return results

        semaphore = asyncio.Semaphore(concurrency)

        async def _check_one(station: dict) -> dict:
            async with semaphore:
                health = await check_station_health_with_playwright(context, station)
                return {**station, **health}

        try:
            tasks = [_check_one(station) for station in unique_list]
            unique_results = await asyncio.gather(*tasks)
        finally:
            # 极其重要：若是我们自己后台拉起的无头 Chrome 实例，检测完后必须强杀进程释放 Profile 锁，防止目录独占占用
            if spawned_process:
                try:
                    subprocess.call(f"taskkill /F /PID {spawned_process.pid}", shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    print("[health_checker] Terminated spawned headless Chrome on 9222 and released profile lock.")
                except Exception as kill_err:
                    print(f"[health_checker] Failed to kill spawned Chrome: {kill_err}")

        # 将去重后的检测结果映射回 host
        results_by_host = {}
        for res in unique_results:
            parsed = urlparse(res["base_url"])
            host = parsed.netloc.lower() or res["base_url"].lower()
            results_by_host[host] = res

        # 回填到原始的所有记录中
        final_results = []
        for s in stations:
            parsed = urlparse(s["base_url"])
            host = parsed.netloc.lower() or s["base_url"].lower()
            res = results_by_host.get(host)
            if res:
                final_results.append({
                    **s,
                    "status": res["status"],
                    "status_reason": res["status_reason"],
                    "response_time_ms": res["response_time_ms"],
                    "error": res["error"],
                    "checked_at": res["checked_at"],
                    "available_models": res["available_models"],
                    "price_map": res["price_map"],
                    "balance": res["balance"],
                    "groups_info": res["groups_info"],
                })
            else:
                final_results.append({**s})

        return final_results

