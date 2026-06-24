# AI 中转站监控大屏 — 当前状态说明

## 一、项目定位

这是一个**已完成并可打包使用的本机桌面/Web 监控大屏**，用于集中查看 ccswitch 中配置的 AI API 中转站状态。

项目只负责：
- 从 ccswitch 自动同步站点
- 抓取余额、分组倍率和可用状态
- 在大屏中展示、排序、辅助补录登录

项目不负责：
- 自动切换 ccswitch 当前站点
- 保存用户密码
- 替代中转站自身后台

---

## 二、当前技术栈

- **后端**：Python + FastAPI + Playwright
- **前端**：原生 HTML / CSS / JavaScript
- **桌面壳**：pywebview
- **打包**：PyInstaller onedir
- **数据来源**：ccswitch SQLite + 共享 Chrome 登录态 + 站点后台 API/DOM
- **默认服务地址**：`http://127.0.0.1:8084`

---

## 三、当前运行链路

### 桌面 EXE 模式

1. 用户启动 `dist\AI中转站监控大屏\AI中转站监控大屏.exe`
2. `run_app.py` 启动内置 FastAPI 后端线程
3. pywebview 打开无边框桌面窗口
4. 前端访问 `http://127.0.0.1:8084`
5. 点击「手动刷新」后，后端通过 Playwright 连接 `127.0.0.1:9222` Chrome
6. 复用 Chrome 登录态抓取余额、分组倍率、状态
7. 前端按站点卡片展示结果

### 开发模式

```bash
cd A:/ClaudeWorkspace/ai-proxy-monitor
python run_app.py
```

或仅启动 Web 服务：

```bash
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8084
```

---

## 四、当前项目结构

```text
A:\ClaudeWorkspace\ai-proxy-monitor\
├── run_app.py                         # 桌面应用入口，启动 FastAPI + pywebview
├── build.bat                          # Windows 打包脚本
├── start-monitor.bat                  # 调试 Chrome + 后端服务启动脚本
├── AI中转站监控大屏.spec              # PyInstaller 配置
├── AI中转站监控大屏.html              # 旧桌面/浏览器跳转壳，跳转到 frontend/static/index.html
├── backend/
│   ├── main.py                        # FastAPI 接口与静态资源服务
│   ├── requirements.txt               # Python 依赖
│   └── services/
│       ├── ccswitch_reader.py         # ccswitch SQLite 读取
│       └── health_checker.py          # Playwright 抓取余额、分组、倍率、状态
├── frontend/static/
│   ├── index.html                     # 大屏页面结构
│   ├── app.js                         # 前端渲染、交互、跳转、补录登录
│   └── style.css                      # 赛博朋克大屏样式
├── data/history.jsonl                 # 检测历史，本地持久化
├── dist/AI中转站监控大屏/             # 已打包桌面程序目录
├── README.md
├── CHANGELOG.md
└── HANDOFF.md
```

---

## 五、已实现功能

- 自动读取 ccswitch 的 Claude provider 配置
- 按 host 聚合同一站点下的多条 provider 记录
- 通过 Chrome CDP 复用已登录状态
- 通过 Playwright 静默访问站点后台
- 拦截 `/api/pricing`、`/api/user/self`、`/api/user/info` 等响应
- 页面内同源 fetch 兜底获取用户、余额、分组和价格信息
- DOM 文本正则兜底识别余额
- 适配 New-API、One-API、Sub2API、DeepSeek 官方、OIDC 登录站等常见类型
- 支持 OIDC / LinuxDO / dc.hhhl.cc 授权辅助点击
- 支持「补录登录」按钮打开共享 Chrome 标签页
- 支持站点控制台一键跳转
- 支持在线 / 需验证 / 异常三状态展示
- 支持异常和需验证站点置顶
- 支持分组倍率聚类和升序展示
- 支持检测历史写入 `data/history.jsonl`
- 支持 PyInstaller 打包为 Windows 桌面 EXE

---

## 六、核心文件说明

### `run_app.py`

桌面应用入口：
- 修正 PyInstaller 运行路径
- 启动 FastAPI 后端线程
- 打开 pywebview 无边框窗口
- 提供最小化、最大化、关闭、拖拽窗口 API

### `backend/main.py`

后端接口层：
- `/api/status`：读取当前缓存状态
- `/api/health`：触发全量检测
- `/api/providers`：返回 ccswitch 原始站点视图
- `/api/login_channel`：打开共享 Chrome 登录标签页
- `/`、`/app.js`、`/style.css`：服务前端静态资源

### `backend/services/ccswitch_reader.py`

读取 ccswitch SQLite：
- 自动查找常见数据库路径
- 只读取 `app_type='claude'` 的 provider
- 提取 `ANTHROPIC_BASE_URL` 和 key/token
- 保留 provider 名称、分类、当前选中状态、官网地址等元信息

### `backend/services/health_checker.py`

核心抓取引擎：
- 连接 `http://127.0.0.1:9222` Chrome CDP
- 根据站点生成后台控制台 URL
- 自动处理部分登录/OIDC 授权流程
- 拦截网络响应
- 页面内同源 fetch
- DOM 文本兜底
- 统一输出余额、分组倍率、模型、状态和耗时

### `frontend/static/app.js`

前端逻辑：
- 调用 `/api/status` 和 `/api/health`
- 渲染站点卡片、统计栏、异常区、分组倍率折叠面板
- 处理控制台跳转、补录登录、搜索、折叠等交互

---

## 七、使用注意

- EXE 使用 onedir 打包，不能只复制单个 `.exe`，必须保持整个 `dist\AI中转站监控大屏` 目录完整。
- 余额和分组抓取依赖 Chrome 9222 调试端口及登录态；如果站点未登录或后台结构特殊，可能显示「未知」或需要手动补录登录。
- 新增非标准站点时，需要同步维护后端 `_get_web_url()` 和前端 `getCleanWebsiteUrl()` 的控制台 URL 映射。
- `data/history.jsonl` 是运行数据，会持续追加检测历史。

---

## 八、当前状态结论

项目当前是**已打包、可运行、功能闭环的成品版**。

旧文档中关于“分组/倍率/余额还未改为网页抓取”的待办已经过时：当前实现已经使用 Playwright + Chrome 登录态 + 网络响应/同源 fetch/DOM 兜底完成了网页侧抓取链路。
