# AI 中转站监控大屏

> 一个赛博朋克风格的桌面/网页监控面板，与 [ccswitch](https://github.com/CCBluX/cc-switch) 深度集成，实时抓取所有 AI 中转站的余额、分组倍率与健康状态。

![界面预览](https://raw.githubusercontent.com/star-power0/ai-proxy-monitor/main/preview.png)

---

## ✨ 主要功能

- **自动同步 ccswitch 站点**：自动从本地 ccswitch SQLite 数据库读取所有已配置的 AI 代理站点，无需重复录入
- **实时余额抓取**：利用本地 Chrome 浏览器的登录状态，静默访问站点后台并拦截 API 响应，精准提取账户余额
- **分组倍率展示**：自动获取 New-API / One-API / Sub2API 等各类站点的分组列表与价格倍率，并按倍率从低到高排列
- **三状态健康检测**：每个站点标注 `在线 ✅` / `需验证 ⚠️` / `异常 ❌` 三种状态，快速定位问题
- **赛博朋克动效大屏**：赛博霓虹粒子网格、极光流光、激光扫描线，内发光呼吸边框，WoW 等级视觉效果
- **一键跳转控制台**：站点名称可点击，直接跳转到对应的账户余额/控制台页面
- **补录登录引导**：对于未抓取到余额的站点，提供"补录登录 🔑"按钮，弹出 Chrome 窗口辅助登录
- **历史记录**：每次检测结果自动保存至本地 `data/history.jsonl`，可供后续分析
- **独立桌面 EXE**：支持一键打包为无需 Python 环境的独立 Windows 桌面应用

---

## 📋 前置依赖

| 依赖 | 说明 | 必须 |
|------|------|------|
| [ccswitch](https://github.com/CCBluX/cc-switch) | AI 代理切换工具，本项目的数据源 | ✅ 必须 |
| Python 3.11+ | 后端服务运行环境 | ✅ 必须（开发模式） |
| Google Chrome | 余额抓取所需的浏览器（需已安装） | ✅ 必须 |
| Playwright Chromium | 自动化浏览器控制内核 | ✅ 必须（见下方安装步骤） |
| PyInstaller + pywebview | 仅用于打包 EXE，开发模式无需 | ⬜ 可选 |

---

## 🚀 快速启动

### 开发模式（直接运行）

```bash
# 1. 克隆项目
git clone https://github.com/star-power0/ai-proxy-monitor.git
cd ai-proxy-monitor

# 2. 安装 Python 依赖
pip install -r backend/requirements.txt

# 3. 安装 Playwright 浏览器内核（关键步骤，不可跳过）
playwright install chromium

# 4. 运行桌面窗口应用
python run_app.py

# 或者仅运行 Web 服务（在浏览器中访问）
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8084
# 然后浏览器打开 http://127.0.0.1:8084
```

### 打包为独立 EXE（Windows）

```bash
# 确保已安装 PyInstaller 和 pywebview，或直接运行：
build.bat
```

打包完成后，可执行文件位于 `dist\AI中转站监控大屏\AI中转站监控大屏.exe`。

> [!WARNING]
> **EXE 不可单独移出目录！** 采用 `--onedir` 模式打包，EXE 依赖同级目录下的 DLL 和静态资源。如需桌面快捷方式，请**右键 EXE → 发送到 → 桌面快捷方式**，不要直接复制 EXE 到桌面。

---

## 🗄️ ccswitch 数据库

本项目启动时自动扫描以下默认路径寻找 ccswitch 数据库，**无需手动配置**：

| 系统 | 路径 |
|------|------|
| Windows | `%APPDATA%\cc-switch\cc-switch.db` |
| Windows (备选) | `%LOCALAPPDATA%\cc-switch\cc-switch.db` |
| Linux / macOS | `~/.cc-switch/cc-switch.db` |

如果大屏显示"未找到 ccswitch 数据库"，请确认已安装并至少启动过一次 ccswitch 客户端。

---

## 🔐 共享登录态（余额抓取的核心）

本项目通过 **Chrome CDP 调试模式（9222 端口）** 共享浏览器登录状态来抓取余额，无需存储任何密码。

### 配置步骤

**1. 以调试模式启动 Chrome（仅需一次）**

```bash
# Windows（替换为你自己的 Chrome 路径和 Profile 目录）
"C:\Program Files\Google\Chrome\Application\chrome.exe" ^
  --remote-debugging-port=9222 ^
  --user-data-dir="C:\MyChromeProfile"
```

> 可以使用项目附带的 `start-monitor.bat` 脚本快速启动（其中默认 Profile 路径可根据自己需要修改）。

**2. 登录你的各个 AI 中转站账号**

在该 Chrome 窗口中，依次打开各个中转站的登录页，完成登录：
- **普通账户（用户名/密码）**：正常登录并让浏览器记住密码即可。
- **OIDC 单点登录（如 LinuxDO / dc.hhhl.cc）**：登录一次并保持会话，程序后续会自动完成 OIDC 授权流程。

**3. 保持 Chrome 运行，然后点击大屏的"手动刷新"**

大屏会自动连接 9222 端口的 Chrome 实例，静默完成所有站点的余额和分组数据抓取。

### Profile 路径自适应策略

| 环境 | Chrome Profile 路径 |
|------|---------------------|
| A 盘存在（如本项目作者的配置） | `A:\ChromeDevToolsProfile` |
| 无 A 盘的普通系统 | `~/.ai-proxy-monitor/ChromeDevToolsProfile` |

---

## ⚙️ 数据抓取原理

### 双轨制抓取架构

```
Chrome (已登录状态)
    └── Playwright CDP 连接
           ├── 轨道 1：拦截网络响应 (XHR/Fetch 监听)
           │       ├── /api/pricing        → 分组倍率
           │       └── /api/user/self      → 余额 + 用户分组
           ├── 轨道 2：同源 Fetch (页面内执行，绕过跨域限制)
           │       ├── /api/user/self      → 余额 (One-API / New-API)
           │       ├── /api/user/info      → 余额 (备选)
           │       ├── /api/user/self/groups → 分组 (New-API / One-API 特性)
           │       └── /api/v1/groups/available → 分组 (Sub2API 专属)
           └── 轨道 3：DOM 正则解析兜底
                   └── 正则匹配"余额"/"可用额度"等关键词附近的数字
```

### 支持的站点类型

| 站点框架 | 余额 | 分组倍率 | 说明 |
|----------|------|----------|------|
| **New-API** | ✅ | ✅ | 完全适配，包含 `/api/user/self/groups` 专属解析 |
| **One-API** | ✅ | ✅ | 完全适配，quota 自动换算（500000 quota = $1） |
| **Sub2API** | ✅ | ✅ | 完全适配，通过 `/api/v1/groups/available` 获取分组 |
| **DeepSeek 官方** | ✅ | ➖ | 直接跳转 `platform.deepseek.com/usage`，DOM 提取 |
| **OIDC 登录站** | ✅ | ✅ | 自动点击 dc.hhhl.cc / LinuxDO 授权按钮完成登录 |
| **自定义 API 站** | ⚠️ | ⚠️ | 通用 DOM 兜底，效果因站而异 |

### 自动登录机制

程序在检测到登录页时会尝试以下操作（全部为辅助功能，不影响主流程）：

1. **自动勾选用户协议复选框**
2. **自动点击已预填充表单的登录按钮**（浏览器保存密码时有效）
3. **自动点击 OIDC 按钮**（识别 `dc.hhhl.cc`、`OIDC`、`LinuxDO` 关键词）
4. **自动点击第三方授权确认按钮**（在 dc.hhhl.cc 授权页识别"允许/Approve"等按钮）

---

## 📁 项目结构

```
ai-proxy-monitor/
├── run_app.py                    # 桌面应用入口（pywebview 窗口容器）
├── build.bat                     # Windows 一键打包脚本
├── logo.ico                      # 应用图标
├── start-monitor.bat             # 调试版 Chrome 快速启动脚本
├── backend/
│   ├── main.py                   # FastAPI 后端，提供 /api/* 接口
│   ├── requirements.txt          # Python 依赖列表
│   └── services/
│       ├── ccswitch_reader.py    # ccswitch SQLite 数据库读取器
│       └── health_checker.py     # 核心：Playwright 双轨制抓取引擎
├── frontend/
│   └── static/
│       ├── index.html            # 大屏 HTML 结构（含 Canvas 动效层）
│       ├── app.js                # 前端逻辑（渲染、API 调用、动效）
│       └── style.css             # 赛博朋克样式表（含呼吸流光动效）
└── data/
    └── history.jsonl             # 检测历史记录（本地持久化）
```

---

## 🌐 API 接口

| 接口 | 方法 | 说明 |
|------|------|------|
| `GET /api/status` | GET | 获取所有站点当前状态（含缓存，快速） |
| `GET /api/health` | GET | 触发全量检测并刷新所有站点数据（较慢） |
| `GET /api/providers` | GET | 获取原始 ccswitch 站点列表 |
| `GET /api/login_channel?url=...` | GET | 在共享 Chrome 中打开登录页辅助补录 |

---

## 🐛 已知 Bug / 待修复

- **❌ 启动窗口未居中**：桌面 EXE 启动时窗口不能自动居中，在分辨率较小（如 1536×864）的屏幕上可能超出屏幕边界。待后续版本修复。
- **⚠️ 部分站点余额抓取失败**：非标准 One-API/New-API 框架的自建站，或修改了后台 API 路由的站点，可能无法自动获取余额，需手动点击"补录登录"并在 Chrome 中手动查看。

---

## 📝 新增站点适配

如果您的站点 API 地址与网页控制台地址不同（如 API 在 `api.example.com`，而控制台在 `example.com/dashboard`），需要在以下两处添加重映射规则：

1. **后端** [`backend/services/health_checker.py`](backend/services/health_checker.py) 中的 `_get_web_url()` 函数
2. **前端** [`frontend/static/app.js`](frontend/static/app.js) 中的 `getCleanWebsiteUrl()` 函数

在两处同时添加如下格式的规则：
```python
# 后端 _get_web_url() 中
if "example.com" in url_lower:
    return "https://example.com/dashboard"
```
```javascript
// 前端 getCleanWebsiteUrl() 中
if (urlLower.includes("example.com")) {
    return "https://example.com/dashboard";
}
```

---

## 📜 许可证

MIT License
