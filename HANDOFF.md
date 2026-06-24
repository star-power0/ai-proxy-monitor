# AI 中转站监控面板 — 项目总结

## 一、项目目标

做一个**本机 Web 面板**，集中查看用户在约 20 个 AI API 中转站的状态，辅助决策哪个站、哪个分组最划算。

用户（丞相）通过 `ccswitch` 桌面端管理这些中转站的切换，本工具**不做自动切换**，只负责监控和推荐。

---

## 二、技术栈

- **后端**：Python 3.13 + FastAPI + httpx
- **前端**：原生 HTML / CSS / JS（无框架）
- **数据来源**：ccswitch 本地 SQLite 数据库 + 站点自身网页/API
- **部署方式**：本机运行，浏览器访问 `http://127.0.0.1:端口`
- **用户**：单用户，无登录/权限

---

## 三、核心架构决策（已定，不可改）

### 3.1 ccswitch 只负责"站点导入"

ccswitch 数据库路径：`C:\Users\huang\.cc-switch\cc-switch.db`

从 `providers` 表读取 `app_type='claude'` 的记录，提取：
- 站名
- base_url（ANTHROPIC_BASE_URL）
- api_key（ANTHROPIC_AUTH_TOKEN）

**ccswitch 不提供**：分组、倍率、余额、在线状态。这些都是死数据，不能用。

### 3.2 分组和倍率：从站点网页实时抓取

用户原话："实时倍率和分组最好也是用网页查"

**不用 API 接口查分组/倍率**，而是从站点后台网页抓取。

原因：
- 有些站的 `/api/pricing` 能拿到 `group_ratio` 和 `usable_group`，但不是所有站都有
- 用户认为网页看到的才是真实的
- 站点后台页面的内容更可靠

### 3.3 余额：从站点网页登录态抓取

用户原话："余额是账户余额，这些东西也许需要你自己从网站抓取"

**不用调用 key 查余额**（key 是模型调用凭证，不是账户查询凭证）。

用户登录方式：
- 有些站用 **Microsoft 登录**
- 有些站用 **Google 登录**

余额需要基于浏览器登录态逐站适配抓取。

### 3.4 同 host 多条记录的处理

ccswitch 里同一个 host 可能有多条记录（不同 key、不同分组名），例如：
- `api.wluvyh.cloud` 下有 3 条（sober 0.08, sober 国模, sober 0.03x）— 3 个不同 key
- `newapi.prorisehub.com` 下有 2 条（pro api 0.12, pro grok）— 2 个不同 key

**聚合规则：按 host 聚合成一个站点**，不再把 ccswitch 的拆分当成真实分组。

### 3.5 分组展示规则

- 分组来自站点实时数据，不是 ccswitch
- 每个站点只展示**最低价前 4 个分组**
- 高倍率分组不展示

### 3.6 在线状态判定

采用**保守状态机**：
- `online`：成功拿到任意核心接口数据
- `unknown`：探不到 / 超时 / 可能需要代理 → 显示"未知，需验证"
- `error`：明确的站点接口异常（5xx 等）

不乱判离线。

---

## 四、当前项目文件结构

```
A:\ClaudeWorkspace\ai-proxy-monitor\
├── backend/
│   ├── main.py                          # FastAPI 入口，当前版本
│   ├── requirements.txt                 # 依赖：fastapi, uvicorn, httpx, sqlite-utils, pydantic
│   ├── inspect_live_shapes.py           # 临时探针脚本（可删）
│   ├── inspect_newapi_details.py        # 临时探针脚本（可删）
│   └── services/
│       ├── ccswitch_reader.py           # 从 ccswitch SQLite 读取站点列表
│       └── health_checker.py            # 站点健康检测（当前版本用 API 探测，需改为网页抓取）
├── frontend/
│   └── static/
│       ├── index.html                   # 主页面
│       ├── app.js                       # 前端逻辑
│       └── style.css                    # 样式
├── data/
│   ├── output/
│   └── history.jsonl                    # 检测历史记录
├── README.md
└── CHANGELOG.md
```

---

## 五、当前版本状态

### 已完成
- ✅ 项目骨架搭建完成
- ✅ ccswitch 数据库读取（23 条 provider 记录，去重后约 20 个 host）
- ✅ FastAPI 后端 + 原生前端页面
- ✅ 站点按 host 聚合
- ✅ 保守状态机（online / unknown / error）
- ✅ 父子卡片展示（站点层 + 分组层）
- ✅ 检测历史写入 history.jsonl
- ✅ 顶部统计栏（站点/在线/需验证/异常）
- ✅ 异常置顶

### 未完成（下一步要做）
- ❌ **分组和倍率改为网页抓取**（当前还在用 API 探测，逻辑不对）
- ❌ **每站最低价前 4 个分组的筛选逻辑**
- ❌ **余额网页抓取**（需逐站适配，依赖浏览器登录态）
- ❌ 5 分钟自动刷新
- ❌ 筛选功能（只看异常/只看常用/只看低倍率）
- ❌ 推荐排序（按倍率低 + 延迟低 + 可用）

---

## 六、已确认的 API 接口结构

以下是探针实际抓到的结构，供参考（但下一步要改为网页抓取）：

### New API 系列（如 newapi.prorisehub.com）
- `GET /api/pricing` → 200
  ```json
  {
    "success": true,
    "group_ratio": {"Claude-Max": 1.2, "default": 0.2, "Grok": 0.1, ...},
    "usable_group": {"Claude-Max": "说明文字", ...},
    "data": [{"model_name": "claude-opus-4-6", "model_ratio": 2.5, "completion_ratio": 5, ...}]
  }
  ```
- `GET /api/user/self` → 200 但 `{"message":"Unauthorized, invalid access token","success":false}`
- `GET /v1/models` → 200

### One API 系列（如 api.qlcodeapi.com）
- `GET /v1/models` → 200
  ```json
  {"data": [{"id": "model-name", "type": "...", "display_name": "..."}]}
  ```
- 没有 `/api/pricing`

### 纯 OpenAI-compatible（如 api.freemodel.dev）
- `GET /v1/models` → 200
- 没有 `/api/pricing`，没有 `/api/user/*`

### DeepSeek / Xiaomi MiMo 等官方站
- 接口路径不同（如 `/anthropic`），当前未适配

---

## 七、启动方式

```bash
cd A:/ClaudeWorkspace/ai-proxy-monitor/backend
pip install -r requirements.txt
cd ..
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8084
```

浏览器打开 `http://127.0.0.1:8084`

---

## 八、下一步工作方向

按优先级排序：

### P0：分组和倍率改为网页抓取
1. 确定用什么方式抓取站点后台网页（浏览器自动化 / 用户手动触发）
2. 从网页 HTML 中提取分组名和倍率
3. 按倍率从低到高排序，取前 4 个
4. 更新后端数据结构和前端展示

### P1：余额网页抓取
1. 用户已在浏览器中登录各站点后台（Google / Microsoft）
2. 逐站适配余额 DOM 抓取
3. 同 host 多 key 时，余额口径待定（目前建议先显示未知，等能抓到再补）

### P2：自动刷新
- 5 分钟自动轮询

### P3：推荐和筛选
- 按倍率 + 延迟综合推荐
- 筛选：只看异常 / 只看常用 / 只看低倍率

---

## 九、用户偏好

- 称呼用户为「丞相」
- 回复使用中文
- 代码注释使用英文
- 简洁直接，不铺垫客套
- 不喜欢 CLI 工具，偏好 Web 面板
- 大屏用户，卡片字体要大
- 用户通过 ccswitch 切换站点，本工具只做监控
