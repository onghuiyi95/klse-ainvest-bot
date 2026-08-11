# ainvest_bot_config.py — 配置 (可选)
#
# 本项目只需一个敏感信息: 你的 Telegram Bot token。
# 三种填法任选其一:
#   1) 复制本文件为 ainvest_bot_config.py, 填 TELEGRAM_TOKEN
#   2) 设置环境变量 TELEGRAM_TOKEN
#   3) 什么都不做 — 程序用内置默认值 (PROXY/MCP/请求头都是固定的, 不用改)
#
# 其余配置都是公开固定值, 程序已内置默认值, 一般无需改动。

TELEGRAM_TOKEN = "REPLACE_WITH_YOUR_BOTFATHER_TOKEN"

# 以下均有默认值, 通常不用改:
# PROXY_BASE = "http://localhost:8787/interaction"
# MCP_URL    = "http://127.0.0.1:9010/mcp"
# X_COMEFROM = "WebaimeRobot"
# X_SOURCE   = "ths_wencai_international_pc_robot"
# DEFAULT_PROMPT = "分析马股"
