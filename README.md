# KLSE Ainvest Bot — 马股 AI 分析 Telegram Bot + 批量报告库

一个把 [Aime / ainvest](https://www.ainvest.com) 的 AI 股票分析能力接到 **Telegram** 和 **本地网页** 的项目。
最初目标是：给一只马来西亚股票（KLSE / Bursa Malaysia），自动拿到 Aime 的基本面 / 估值 / 技术面 / 风险分析，
并把全市场 1000+ 只马股批量分析、存进 SQLite，再用网页浏览。

> ⚠️ **项目性质说明（务必先读）**
> Aime 是一个**网页端 AI 投研助手**，没有公开 API。本项目通过以下方式"借道"使用它：
> 1. **本地代理** `ainvest_proxy.js` 转发请求到 Aime 网页端点；
> 2. **游客身份（guest）cookie** 作为身份凭证 —— 每个 guest 有调用配额（实测 fast-agent 约 5 次），耗尽需换新；
> 3. **换 guest** 借助本地 `browseros-neo` MCP 服务（一个浏览器自动化环境）刷新 cookie。
>
> 因此本项目**代码可移植，但运行依赖 Aime 的游客态 + 本地 browseros 环境**。换一台电脑需要重新搭建这两部分（详见下文「复活步骤」）。

---

## 功能

- 🤖 **Telegram Bot**（`aime_telebot.py`）：发股票代码/名称，返回 Aime 分析报告。支持 `/fast` `/agent` 切换分析深度、`/runtime` 查询。
- 🌐 **网页查看器**（`report_viewer.py`）：Flask 应用，列出全部股票+分析状态，点开看完整报告（含思考链、图表）。
- 📊 **批量分析**（`batch_analyze.py`）：多线程并发，把全市场马股喂给 Aime，报告存 `stocks.db`。
- 🔄 **自动换 guest**（`simulate_guest.py`）：通过 browseros-neo 刷新游客身份，绕过单次配额限制。
- 👀 **巡检守护**（`watchdog.py`）：自动检测批量任务是否卡死/退出，自动补 guest 重启，直到全部跑完。

---

## 架构

```
Telegram ──► aime_telebot.py ──► ainvest_proxy.js (localhost:8787)
                                      │
                                      ▼
                            Aime / ainvest 网页端点 (SSE: /chat, /runs)
                                      ▲
                          cookie.txt (guest 身份, 配额约5次)
                                      │
                          simulate_guest.py ──► browseros-neo MCP (localhost:9010)
                                      │                (登录态浏览器, 刷新 cookie)
                                      ▼
                            cookie_mt_*.txt (新 guest)

批量模式:
batch_analyze.py ──(多线程, 各持一 guest)──► ainvest_proxy.js ──► Aime
       │                                            │
       └── 配额耗尽 ──► simulate_guest.py ──► browseros ──► 换 guest 续跑
       ▼
   stocks.db (stocks 表 + reports 表)

查看:
report_viewer.py (Flask :5000) ──► 读 stocks.db ──► 浏览器
```

### 接口 / 数据流

**`ask_ainvest(prompt, runtime="fast-agent", cookie=None)`** → `(status, text, reason)`
1. `POST {PROXY_BASE}/chat?runtime={rt}` 拿到 `threadId`；
2. `POST {PROXY_BASE}/runs`（SSE，`stream=True`，`timeout=120`）发送消息，逐事件解析；
3. SSE 事件流：`TEXT_MESSAGE_START` → `REASONING_*`（思考链）→ `TEXT_MESSAGE_CONTENT`（正文，可能多段）→ `TEXT_MESSAGE_END`；
4. 正文里若含 `<!doctype html>...</html>` 是 ECharts 配置，由 `render_aime_chart.py` 抽出来用 matplotlib 渲成 PNG（中文用 `msyh.ttc`）；
5. 返回时 `r.encoding="utf-8"` **必须手动设置**（requests 默认 ISO-8859-1，会导致中文乱码）；
6. 配额耗尽时 `/runs` 会**挂起不返 429**，故 `timeout` 触发即视为 429 处理。

**关键约定**
- `runtime="fast-agent"`：快速回复，配额约 5 次/身份，回答精炼（默认）；
- `runtime="agent-runtime"`：深度分析，配额约 2 次/身份，推理更展开；
- `PROMPT_GUARD`：强制 Aime 不反问、不索取投资背景、直接基于公开数据作答、用中文。

---

## 目录结构

```
klse-ainvest-bot/
├── aime_telebot.py            # Telegram bot 主程序
├── ainvest_proxy.js           # 本地代理 (Node, 监听 8787)
├── ainvest_bot_config.example.py  # 配置模板 (复制为 ainvest_bot_config.py 填 token)
├── simulate_guest.py          # 通过 browseros 换 guest 身份
├── batch_analyze.py           # 多线程批量分析 -> stocks.db
├── report_viewer.py           # Flask 网页查看器 (:5000)
├── scrape_klse.py             # 抓 KLSE Screener 股票列表 -> stocks.db
├── render_aime_chart.py       # Aime 图表 HTML -> matplotlib PNG
├── watchdog.py                # 批量任务巡检守护
├── run_daemon.py              # 旧版守护 (备用)
├── requirements.txt
├── .gitignore
└── README.md
```

---

## 复活步骤（新电脑 / 新环境）

### 1. 基础环境
```bash
git clone <this-repo>
cd klse-ainvest-bot
python -m venv .venv && .venv\Scripts\activate      # Windows
pip install -r requirements.txt
npm install                                         # ainvest_proxy.js 依赖 (若用 node 运行)
```

### 2. 配置
```bash
cp ainvest_bot_config.example.py ainvest_bot_config.py
# 编辑 ainvest_bot_config.py, 填入你的 Telegram @BotFather token
```

### 3. 获取 Aime 游客身份（关键）
Aime 网页端以**游客（guest）** 身份可用。需要一份有效 cookie：
- **方式 A（本项目依赖）**：部署 `browseros-neo` 这类浏览器自动化 MCP 服务（监听 9010），
  用 `simulate_guest.py` 在其登录态浏览器里刷新 cookie（详见 `simulate_guest.py` 注释）；
- **方式 B（手动）**：用浏览器登录/以游客打开 ainvest，从 DevTools 复制 `cookie.txt`
  （需含 `u_name=mt_xxxxxxxx` 等会话字段）。cookie 绑定设备/浏览器，**换机需重新获取**。

### 4. 启动代理 + Bot
```bash
# 终端1: 代理
node ainvest_proxy.js
# 终端2: Telegram bot
python aime_telebot.py
# 终端3 (可选): 网页查看器
python report_viewer.py        # 打开 http://localhost:5000
```

### 5. 批量分析全市场
```bash
# 先把股票列表抓进库
python scrape_klse.py
# 确保有可用 guest cookie, 然后批量
python batch_analyze.py --workers 10
# 或用巡检守护自动续跑 (推荐, 遇卡自动换新 guest 重启)
python watchdog.py
```

---

## 已知限制 / 坑

1. **游客身份配额**：每个 guest 约 5 次调用，耗尽需换新。换新依赖 browseros 环境，
   没有它则只能手动更换 `cookie.txt`。
2. **browseros 偶发卡**：`simulate_guest.py` 的 `evaluate` 工具在 browseros 不稳定时会
   偶发卡死（chunked 响应读不完），已加超时+重试缓解，但仍可能失败 → 批量任务会等浏览器恢复。
3. **Aime 端点可能变更**：本项目逆向的是特定时期的网页端点与请求结构，Aime 改版即需重新抓包。
4. **中文乱码**：`requests` 的 SSE 响应必须 `r.encoding="utf-8"`，否则 ISO-8859-1 乱码。
5. **非投资建议**：内容来自 AI，仅供研究，不构成投资建议。

---

## 数据

- `stocks.db`（不入库，体积大且含分析结果）：`stocks` 表（代码/名称/板块/价/PE/DY/ROE…）+ `reports` 表（分析报告全文/思考链/图表路径/时间）。
- 批量跑完约 1095 只马股，每只为一条 `reports` 记录。

---

## 许可证

MIT（仅供学习研究，使用本项目须遵守 Aime / ainvest 的服务条款与所在地法律法规）。
