# AI 中转站监控面板

本机 Web 面板，用于集中查看 AI 中转站状态，辅助决策哪个站、哪个分组最划算。

## 核心架构

- **ccswitch** 只负责提供站点入口（host + key）
- **分组/倍率** 从站点网页实时抓取
- **余额** 从站点后台网页登录态抓取
- 每个站点只展示最低价前 4 个分组
- 不做自动切换，用户自己在 ccswitch 里切

## 启动

```bash
cd A:/ClaudeWorkspace/ai-proxy-monitor/backend
pip install -r requirements.txt
cd ..
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8084
```

浏览器打开 `http://127.0.0.1:8084`

## 项目结构

```
ai-proxy-monitor/
├── backend/
│   ├── main.py                    # FastAPI 入口
│   ├── requirements.txt
│   └── services/
│       ├── ccswitch_reader.py     # ccswitch 数据库读取
│       └── health_checker.py      # 站点检测（待改为网页抓取）
├── frontend/
│   └── static/
│       ├── index.html
│       ├── app.js
│       └── style.css
├── data/
│   └── history.jsonl              # 检测历史
├── README.md
├── CHANGELOG.md
└── HANDOFF.md                     # 项目交接文档（给下一个 AI 看）
```

## 当前状态

- ✅ ccswitch 站点导入（~20 个 host）
- ✅ 站点按 host 聚合
- ✅ 父子卡片展示（站点层 + 分组层）
- ✅ 保守状态机（online / unknown / error）
- ❌ 分组/倍率：待改为网页实时抓取
- ❌ 余额：待从站点后台网页抓取

## 维护与新增站点指南

### 1. 自动同步逻辑
本监控系统会自动实时查询 `ccswitch` 本地数据库。只要您在 **`ccswitch` 客户端中导入或添加了新站**，该站点卡片在您启动大屏或点击手动刷新时，就**会自动产生在面板上**。

### 2. 新增站点的余额与自动登录适配
大部分基于主流 One-API/New-API 等搭建的站点无需额外开发即可自适应获取余额，只需配合以下操作：

* **如果新站使用普通用户名密码登录**：
  在由 `Start-Claude-Chrome.cmd` 拉起的**调试版 Chrome**中，输入一次密码并让浏览器选择**“保存密码”**即可。以后程序检测到页面有保存的账号密码时，会自适应等待渲染并在后台点击登录。
* **如果新站使用 OIDC（例如 `dc.hhhl.cc` 或 LinuxDO）登录**：
  您只需在**调试版 Chrome**中**登录一次您的 `dc.hhhl.cc` / 第三方账号**使其记住登录态。程序在检测时一旦在登录页发现“使用 dc.hhhl.cc 继续”等按钮，会自动点击并全自动在第三方授权页确认“继续”，实现免密秒登。
* **如果新站的 API 地址与控制台页面地址不同**：
  若其 API 地址为 `https://api.new站.com`，而其用户钱包页面是 `https://api.new站.com/wallet`：
  分别在 [health_checker.py](backend/services/health_checker.py) 的 `_get_web_url` 和 [app.js](frontend/static/app.js) 的 `getCleanWebsiteUrl` 中，将该域名的网页重映射配置加入即可。

### 3. 关键踩坑经验总结
* **已登录会话保护**：管理员控制台菜单（如 cheapyun.cc.cd）可能包含“OIDC”字眼。自动登录逻辑必须先判定页面是否已登录（如包含“数据看板”等菜单），对于已登录的页面**严禁产生任何模拟点击**，否则会误点导致会话重定向退出。
* **自适应渲染等待**：在多站并发（concurrency）的高负载下，调试 Chrome 实例加载缓慢。切勿使用 `sleep(2)` 等固定死等，应采用自适应轮询（最长 8 秒）直到检测到登录框、OIDC 按钮或控制台菜单再继续操作，能保证 100% 抓取稳定性。

## 详细交接文档

见 [HANDOFF.md](HANDOFF.md)

