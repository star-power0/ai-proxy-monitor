"""
中转站网页探测服务
通过 Playwright 连接本地调试 Chrome 实例（9222 端口），
利用免登状态静默打开中转站后台，拦截 API 响应包，获取真实的余额、分组及倍率。
"""
import asyncio
import json
import os
import re
import socket
import subprocess
import sys
from datetime import datetime
from urllib.parse import urlparse
from playwright.async_api import async_playwright

CDP_URL = "http://127.0.0.1:9222"


def _resolve_probe_cache_path() -> str:
    """
    Resolve the writable probe_cache.json path.
    - Source mode: project_root/data/probe_cache.json
    - Packaged (PyInstaller) mode: <exe_dir>/data/probe_cache.json
      On first run, seed it from the bundled factory preset in _MEIPASS.
    """
    if hasattr(sys, "_MEIPASS"):
        user_path = os.path.join(os.path.dirname(sys.executable), "data", "probe_cache.json")
        if not os.path.exists(user_path):
            seed = os.path.join(sys._MEIPASS, "data", "probe_cache.json")
            if os.path.exists(seed):
                try:
                    os.makedirs(os.path.dirname(user_path), exist_ok=True)
                    with open(seed, "r", encoding="utf-8") as src, \
                         open(user_path, "w", encoding="utf-8") as dst:
                        dst.write(src.read())
                except Exception:
                    pass
        return user_path
    return os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "data", "probe_cache.json"))


PROBE_CACHE_PATH = _resolve_probe_cache_path()

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


def _load_probe_cache() -> dict:
    try:
        with open(PROBE_CACHE_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save_probe_cache(cache: dict):
    os.makedirs(os.path.dirname(PROBE_CACHE_PATH), exist_ok=True)
    with open(PROBE_CACHE_PATH, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)


def _remember_balance_path(host: str, url: str, label: str | None = None):
    """Remember the path (and optionally the label) that successfully yielded a balance."""
    parsed = urlparse(url)
    if not parsed.netloc:
        return
    cache = _load_probe_cache()
    entry = cache.setdefault(host, {})
    entry["balance_path"] = parsed.path or "/"
    if label:
        entry["balance_label"] = label
    _save_probe_cache(cache)


def _get_cached_probe_url(host: str, web_url: str):
    cache = _load_probe_cache()
    cached_path = cache.get(host, {}).get("balance_path")
    if not cached_path:
        return None
    parsed = urlparse(web_url)
    root = f"{parsed.scheme or 'https'}://{parsed.netloc}".rstrip("/")
    return f"{root}/{cached_path.strip('/')}".rstrip("/")


def _get_cached_balance_label(host: str) -> str | None:
    """Return the previously-successful balance label for this host, if any."""
    cache = _load_probe_cache()
    return cache.get(host, {}).get("balance_label")


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


def _build_probe_urls(web_url: str, cached_url: str | None = None) -> list[str]:
    parsed = urlparse(web_url)
    root = f"{parsed.scheme or 'https'}://{parsed.netloc}".rstrip("/")
    urls = []
    if cached_url:
        urls.append(cached_url.rstrip("/"))
    if parsed.path and parsed.path != "/":
        urls.append(web_url.rstrip("/"))
    common_paths = (
        "/dashboard", "/console", "/wallet", "/topup", "/profile",
        "/user/asset-source", "/user/dashboard", "/user/wallet",
        "/user/profile", "/account", "/account/billing", "/billing",
        "/",
    )
    for path in common_paths:
        urls.append(f"{root}{path}".rstrip("/"))
    return list(dict.fromkeys(urls))


async def _extract_dom_balance_via_dom(page, preferred_label: str | None = None):
    """
    DOM-level balance extraction (v5).
    Walks all visible text nodes in DOM order. When a node contains a known
    balance label, scans the next ~30 text nodes (or 400 chars) for the
    first valid number. Returns {value, label} dict or None.

    A previously-successful label (from probe_cache.json) gets a +1000
    priority boost so once a host has been mapped, that mapping is sticky.
    """
    return await page.evaluate("""(preferredLabel) => {
        const LABEL_PRIORITY = {
            '当前余额': 100, '账户余额': 100, '账号余额': 100,
            '个人余额': 90, '我的余额': 90, '可用余额': 90,
            '钱包余额': 85, 'Token余额': 85, '剩余余额': 85,
            '充值余额': 80,
            '账户额度': 70, '账户余款': 70, '账户金额': 70,
            '剩余额度': 65, '可用额度': 65,
            '剩余配额': 55, '可用配额': 55,
            '点数余额': 50, '剩余金额': 50,
            '我的资产': 60, '账户资产': 60, '总资产': 55,
            '金币池': 50, '我的金币': 50, '积分余额': 55, '点数': 45,
            'Balance': 60, 'Credits': 50, 'Credit': 50,
            'Quota': 40, 'Remaining': 50, 'Available': 45,
            '余额': 30, '额度': 25
        };
        const LABELS = Object.keys(LABEL_PRIORITY).sort((a, b) => b.length - a.length);

        const NUM_RE = /([0-9][0-9,]*(?:\\.\\d+)?)/;
        const BAD_WORDS = ['满', '送', '减', '赠', '折', '优惠', '抢', '仅需',
                           '充值送', '冻结', '限时', '活动', '套餐', '即可'];

        const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
        const nodes = [];
        let n;
        while ((n = walker.nextNode())) {
            const t = (n.textContent || '').trim();
            if (!t) continue;
            const tag = n.parentElement && n.parentElement.tagName;
            if (tag === 'SCRIPT' || tag === 'STYLE') continue;
            nodes.push(t);
        }

        function findLabelIn(txt) {
            for (const lbl of LABELS) {
                if (txt.includes(lbl)) return lbl;
            }
            return null;
        }

        const candidates = [];
        for (let i = 0; i < nodes.length; i++) {
            const txt = nodes[i];
            const label = findLabelIn(txt);
            if (!label) continue;

            const labelIdx = txt.indexOf(label);
            let ctx = txt.slice(labelIdx + label.length);
            for (let j = 1; j <= 30 && i + j < nodes.length; j++) {
                ctx += ' ' + nodes[i + j];
                if (ctx.length > 400) break;
            }
            ctx = ctx.slice(0, 400);

            const m = ctx.match(NUM_RE);
            if (!m) continue;
            const v = parseFloat(m[1].replace(/,/g, ''));
            if (isNaN(v) || v > 1000000) continue;

            const beforeNum = ctx.slice(0, m.index);
            if (BAD_WORDS.some(w => beforeNum.includes(w))) continue;

            let priority = LABEL_PRIORITY[label] || 0;
            if (preferredLabel && label === preferredLabel) priority += 1000;

            candidates.push({ value: v, label, priority, domOrder: i });
        }

        if (candidates.length === 0) return null;
        candidates.sort((a, b) => b.priority - a.priority || a.domOrder - b.domOrder);
        return { value: candidates[0].value, label: candidates[0].label };
    }""", preferred_label)


def _extract_dom_groups_text(text: str) -> dict:
    if not text:
        return {}
    groups = {}
    for match in re.finditer(r"([一-龥A-Za-z0-9_\-\[\]【】（）() ]{1,40})\s*([0-9]+(?:\.[0-9]+)?)\s*x\b", text, re.IGNORECASE):
        name = match.group(1).strip(" ：:|-\n\t") or f"{match.group(2)}x"
        ratio = float(match.group(2))
        key = name.lower()
        groups[key] = {"name": name, "ratio": ratio}
    return groups


async def _dismiss_page_overlays(page):
    try:
        await page.keyboard.press("Escape")
        await page.evaluate("""() => {
            const keywords = ['今日不再', '不再提示', '我知道', '知道了', '关闭', '确定', 'Close', 'OK'];
            const controls = Array.from(document.querySelectorAll('button, a, [role="button"]')).reverse();
            for (const el of controls) {
                const text = (el.innerText || el.textContent || el.getAttribute('aria-label') || '').trim();
                if (keywords.some(kw => text.includes(kw))) {
                    el.click();
                    return true;
                }
            }
            return false;
        }""")
        await asyncio.sleep(0.5)
    except Exception:
        pass


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
    host = parsed_url.netloc.lower() or base_url.lower()
    cached_probe_url = _get_cached_probe_url(host, web_url)

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

    page = None
    start_time = datetime.now()
    try:
        page = await context.new_page()
        page.on("response", handle_response)

        # 3. 导航逻辑：如果是纯域名，默认拼入 /dashboard 触发控制台；如果是带有路径的精确控制台 URL，则直接直达
        parsed_web = urlparse(web_url)
        path = parsed_web.path.strip("/")
        if path:
            goto_url = web_url
        else:
            goto_url = f"{web_url.rstrip('/')}/dashboard"
            
        await page.goto(goto_url, timeout=10000, wait_until="domcontentloaded")
        await _dismiss_page_overlays(page)

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

            // 1. 同源 fetch 常见用户接口
            for (const endpoint of ['/api/user/self', '/api/user/info', '/api/user/dashboard', '/api/user/quota', '/api/user/token', '/api/user/balance', '/api/billing/info', '/api/v1/auth/me', '/api/me']) {
                try {
                    const r = await fetch(endpoint, { headers, credentials: 'same-origin' });
                    if (r.ok) {
                        resData.user = await r.json();
                        break;
                    }
                } catch(e) {}
            }

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
            if not isinstance(group_ratio, dict):
                group_ratio = {}
            if not isinstance(usable_group, dict):
                usable_group = {}
            if group_ratio:
                groups = {}
                for grp_id, grp_ratio in group_ratio.items():
                    grp_name = usable_group.get(grp_id) or grp_id
                    try:
                        ratio_val = float(grp_ratio)
                    except (ValueError, TypeError):
                        continue
                    groups[grp_id] = {
                        "name": grp_name,
                        "ratio": ratio_val
                    }
                if groups:
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
                            try:
                                ratio_val = float(grp_ratio)
                            except (ValueError, TypeError):
                                continue
                            groups[grp_id] = {
                                "name": grp_name,
                                "ratio": ratio_val
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
                            if not grp_name:
                                continue
                            grp_ratio = grp.get("rate_multiplier", 1.0)
                            try:
                                ratio_val = float(grp_ratio)
                            except (ValueError, TypeError):
                                continue
                            groups[grp_name] = {
                                "name": grp_name,
                                "ratio": ratio_val
                            }
                    if groups:
                        result["groups_info"] = groups

        # 7. 判定在线状态与 DOM 正则解析兜底 (主要对应 DeepSeek 等官方站与复杂页面)
        # 只要 API 轨道未获得有效余额，即降级执行 DOM 提取进行数据补充
        final_dom_text = await page.evaluate("() => document.body.innerText")
        if result["balance"] is None:
            probe_urls = _build_probe_urls(web_url, cached_probe_url)
            balance_trace = []  # diagnostic trace for debugging
            for probe_url in probe_urls:
                try:
                    if page.url.rstrip("/") != probe_url.rstrip("/"):
                        await page.goto(probe_url, timeout=8000, wait_until="domcontentloaded")
                    await _dismiss_page_overlays(page)
                    # Retry up to 3 times: SPA pages may need extra time to render balance
                    for _retry in range(3):
                        await asyncio.sleep(1.5 if _retry > 0 else 1.0)
                        # Login-gate check: skip if this is clearly a login page
                        page_state = await page.evaluate("""() => {
                            const raw = document.body.innerText;
                            const text = raw;
                            const textLower = raw.toLowerCase();
                            const hasPasswordInput = !!document.querySelector('input[type="password"]');
                            const LOGGED_IN_KW_CN = [
                                '数据看板','个人设置','API令牌','API 令牌','API密钥','API 密钥',
                                '令牌管理','控制台','钱包','账户数据','使用日志','我的余额',
                                '账户信息','账户中心','个人中心','用户中心','资产来源','资产明细',
                                '退出登录','退出账号','退出账户',
                                '我的卡密','卡密管理','邀请','签到','充值','账单','用量信息',
                                '接口文档','产品定价','实用集成','个人信息','仪表盘','仪表板',
                                '资产管理','额度记录','额度管理','使用统计','在线充值'
                            ];
                            const LOGGED_IN_KW_EN = [
                                'sign out','log out','logout','dashboard','api keys','api key',
                                'billing','account','profile','usage','api tokens','my account'
                            ];
                            const hasLoggedInMenu =
                                LOGGED_IN_KW_CN.some(k => text.includes(k)) ||
                                LOGGED_IN_KW_EN.some(k => textLower.includes(k));
                            const isLoginPage = hasPasswordInput ||
                                (!hasLoggedInMenu && (text.includes('登录') || text.includes('Sign in')) &&
                                 (text.includes('注册') || text.includes('Register') ||
                                  text.includes('OIDC') || text.includes('dc.hhhl.cc')));
                            return { isLoginPage, hasLoggedInMenu };
                        }""")
                        if page_state.get("isLoginPage"):
                            balance_trace.append(f"{probe_url}#r{_retry}:login_page")
                            break
                        if not page_state.get("hasLoggedInMenu"):
                            balance_trace.append(f"{probe_url}#r{_retry}:no_logged_in_menu")
                            continue  # Not authenticated yet — retry
                        # Authenticated: try DOM-level balance extraction
                        cached_label = _get_cached_balance_label(host)
                        dom_result = await _extract_dom_balance_via_dom(page, cached_label)
                        if dom_result is not None:
                            result["balance"] = dom_result["value"]
                            final_dom_text = await page.evaluate("() => document.body.innerText")
                            _remember_balance_path(host, page.url, dom_result.get("label"))
                            balance_trace.append(
                                f"{probe_url}#r{_retry}:HIT={dom_result['value']}({dom_result.get('label')})"
                            )
                            break
                        balance_trace.append(f"{probe_url}#r{_retry}:logged_in_no_match")
                        # Diagnostic: on last retry of a probe URL, dump short snippets
                        # around currency symbols / digits so we can see what label is used.
                        if _retry == 2:
                            try:
                                hints = await page.evaluate("""() => {
                                    const txt = document.body.innerText || '';
                                    const out = [];
                                    // Find all $/¥ amounts and grab 25 chars before them
                                    const re = /(?:¥|￥|\\$)\\s*[0-9][0-9,.]*/g;
                                    let m;
                                    while ((m = re.exec(txt)) !== null && out.length < 6) {
                                        const start = Math.max(0, m.index - 25);
                                        out.push(txt.slice(start, m.index + m[0].length).replace(/\\s+/g, ' '));
                                    }
                                    return out;
                                }""")
                                if hints:
                                    print(f"[balance_hint] {host} @ {probe_url}: {hints}")
                            except Exception:
                                pass
                    if result["balance"] is not None:
                        break
                except Exception as e:
                    balance_trace.append(f"{probe_url}:exc={type(e).__name__}")
                    continue
            if result["balance"] is None and balance_trace:
                print(f"[balance_trace] {host}: {' | '.join(balance_trace)}")

        if not result["groups_info"]:
            dom_groups = _extract_dom_groups_text(final_dom_text)
            if dom_groups:
                result["groups_info"] = dom_groups

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
        # Save debug screenshot only when we confirmed login but still couldn't get balance.
        # Skip the snapshot for sites that are simply unreachable or never authenticated.
        should_screenshot = (
            result["status"] == "online"
            and result["balance"] is None
            and result.get("groups_info")  # implies API/login succeeded enough to learn groups
        )
        if should_screenshot:
            parsed = urlparse(base_url)
            host = parsed.netloc.lower() or base_url.lower()
            if "nvidia.com" not in host and page:
                try:
                    debug_dir = os.path.join(os.path.dirname(__file__), "..", "..", "data", "debug_screenshots")
                    os.makedirs(debug_dir, exist_ok=True)
                    screenshot_path = os.path.join(debug_dir, f"{host}_balance_none.png")
                    await page.screenshot(path=screenshot_path)
                    print(f"[health_checker] 站点 {host} 余额为 None 且为 online，已保存截图至: {screenshot_path}")
                except Exception as se:
                    print(f"[health_checker] 保存 debug 截图失败: {se}")
        if page:
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

