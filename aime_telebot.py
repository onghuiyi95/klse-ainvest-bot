#!/usr/bin/env python3
# ainvest_bot.py — Telegram bot: 问 Aime (ainvest) + 配额耗尽自动换新 guest
# 依赖: python-telegram-bot (已装 22.8)
# 前置: node ainvest_proxy.js 在跑 (8787); browseros-neo 在 9010 跑着
import os
import requests, json, uuid, re, subprocess, sys, threading, os
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters

# 配置: 优先读 ainvest_bot_config.py, 没有则用内置默认值 (只需 TELEGRAM_TOKEN)
# TELEGRAM_TOKEN 也可通过环境变量提供, 避免建配置文件
try:
    import ainvest_bot_config as C
except Exception:
    C = None
def cfg(name, default):
    return getattr(C, name, None) if C else None
TELEGRAM_TOKEN = (getattr(C, "TELEGRAM_TOKEN", None) if C else None) or os.environ.get("TELEGRAM_TOKEN", "")
PROXY_BASE     = (getattr(C, "PROXY_BASE", None) if C else None) or "http://localhost:8787/interaction"
MCP_URL       = (getattr(C, "MCP_URL", None) if C else None) or "http://127.0.0.1:9010/mcp"
X_COMEFROM    = (getattr(C, "X_COMEFROM", None) if C else None) or "WebaimeRobot"
X_SOURCE      = (getattr(C, "X_SOURCE", None) if C else None) or "ths_wencai_international_pc_robot"
DEFAULT_PROMPT= (getattr(C, "DEFAULT_PROMPT", None) if C else None) or "分析马股"

# runtime 切换：fast-agent=快/5次配额（默认）；agent-runtime=深度分析/2次配额
# 持久化到文件，bot 重启不丢
RUNTIME_FILE = "aime_runtime.txt"
def get_runtime():
    try:
        v = open(RUNTIME_FILE, encoding="utf-8").read().strip()
        return v if v in ("fast-agent", "agent-runtime") else "fast-agent"
    except Exception:
        return "fast-agent"
def set_runtime(v):
    if v not in ("fast-agent", "agent-runtime"): return False
    open(RUNTIME_FILE, "w", encoding="utf-8").write(v)
    return True

# 强制约束：禁止反问/索取背景，直接基于公开数据给分析（用中文）
# fast 模式额外要求精炼；agent 模式允许展开推理但同样不许反问
PROMPT_GUARD_FAST = (
    "\n\n[硬性约束] 你必须遵守："
    "1) 不要向我提出任何问题，不要索取投资背景/档案/持仓等任何信息；"
    "2) 不要说“让我先了解你的背景”“在为你分析之前我需要确认”之类的开场白，直接给分析；"
    "3) 基于公开可得的行情、财报、研报数据直接作答，用中文；"
    "4) 若数据不足，明确说明缺口即可，不要向我追问；"
    "5) 回答要精炼直接，推理过程从简，不要展开冗长的内心独白，直奔结论与关键数据。"
)
PROMPT_GUARD_AGENT = (
    "\n\n[硬性约束] 你必须遵守："
    "1) 不要向我提出任何问题，不要索取投资背景/档案/持仓等任何信息；"
    "2) 不要说“让我先了解你的背景”“在为你分析之前我需要确认”之类的开场白，直接给分析；"
    "3) 基于公开可得的行情、财报、研报数据直接作答，用中文；"
    "4) 若数据不足，明确说明缺口即可，不要向我追问。"
)
def prompt_guard():
    return PROMPT_GUARD_FAST if get_runtime() == "fast-agent" else PROMPT_GUARD_AGENT

def ask_ainvest(prompt, max_events=800, runtime=None, cookie=None):
    """走本地代理问 Aime, 返回 (status, text, reason)。cookie 可指定身份文件。"""
    rt = runtime or get_runtime()
    ck = cookie
    if ck is None:
        try: ck = open("cookie.txt", encoding="utf-8", errors="ignore").read().strip()
        except: ck = ""
    h = {"content-type":"application/json","x-comefrom":X_COMEFROM,
         "x-source":X_SOURCE,"user-agent":"Mozilla/5.0",
         "origin":"https://www.ainvest.com","referer":"https://www.ainvest.com/","cookie":ck}
    r = requests.post(PROXY_BASE+f"/chat?runtime={rt}",
                      headers={**h,"accept":"application/json"}, timeout=30)
    r.encoding = "utf-8"
    if r.status_code != 200:
        return r.status_code, r.text[:200], ""
    tid = r.json()["response"]["chat"]["threadId"]
    rid = str(uuid.uuid4())
    user_content = prompt + prompt_guard()
    body = {"threadId":tid,"runId":rid,"runtime":rt,
            "messages":[{"id":str(uuid.uuid4()),"role":"user","content":user_content}],
            "forwardedProps":{"agentName":"RouterAgent","source":X_SOURCE,
                              "comefrom":X_COMEFROM,"inputType":"typewrite"}}
    try:
        r2 = requests.post(PROXY_BASE+"/runs", headers={**h,"accept":"text/event-stream"},
                           json=body, stream=True, timeout=120)
    except Exception:
        # 代理在 guest 配额耗尽时常挂起不返 429，等待超时即视为配额耗尽
        return 429, "guest 配额耗尽(请求挂起)", ""
    r2.encoding = "utf-8"
    if r2.status_code == 429:
        return 429, "guest 配额耗尽", ""
    if r2.status_code not in (200,202):
        return r2.status_code, r2.read(300).decode("utf-8","ignore"), ""
    text=[]; reason=[]
    for line in r2.iter_lines(decode_unicode=True):
        if not line or not line.startswith("data:"): continue
        try: d=json.loads(line[5:])
        except: continue
        t=d.get("type")
        if t=="TEXT_MESSAGE_CONTENT": text.append(d.get("delta",""))
        elif t=="REASONING_MESSAGE_CONTENT": reason.append(d.get("delta",""))
        if len(text) > 6000: break   # 正文够长就停，避免无限流
    body = "".join(text).strip()
    thinking = "".join(reason).strip()
    return 200, body, thinking

def renew_guest():
    """调 simulate_guest.py 换新 guest, 返回 (gid, cookie_path) 或 (None, None)。线程安全。"""
    with _renew_lock:
        try:
            out = subprocess.run([sys.executable, "simulate_guest.py"],
                                  capture_output=True, text=True, timeout=120).stdout
            m = re.search(r"新 guest id:\s*(mt_\d+)", out)
            if not m:
                return None, None
            gid = m.group(1)
            return gid, f"cookie_{gid}.txt"
        except Exception as e:
            return None, None

def current_guest():
    try:
        ck = open("cookie.txt",encoding="utf-8").read()
        m = re.search(r"u_name=(mt_\d+)", ck)
        return m.group(1) if m else "(未知)"
    except: return "(无 cookie)"

async def cmd_ask(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # /ask = 深度分析 (agent-runtime)
    prompt = " ".join(context.args) if context.args else DEFAULT_PROMPT
    await cmd_text(update, context, override_prompt=prompt, override_runtime="agent-runtime")

async def cmd_fast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # /fast = 快速 (fast-agent, 5次配额)
    prompt = " ".join(context.args) if context.args else DEFAULT_PROMPT
    await cmd_text(update, context, override_prompt=prompt, override_runtime="fast-agent")

async def cmd_text(update: Update, context: ContextTypes.DEFAULT_TYPE, override_prompt=None, override_runtime=None):
    prompt = override_prompt if override_prompt else update.message.text.strip()
    if not prompt:
        return
    rt = override_runtime or get_runtime()
    await update.message.reply_text(f"🔍 问 Aime: {prompt}\n(模式 {rt} | 身份 {current_guest()}) … 分析中，请稍候")
    try:
        status, body, reason = ask_ainvest(prompt, runtime=rt)
    except Exception as e:
        await update.message.reply_text(f"⏱ 请求超时或出错：{e}\n可稍后重试，或 /renew 换新身份。")
        return
    if status == 429:
        await update.message.reply_text("⚠ guest 配额耗尽, 自动换新身份…")
        gid, _ = renew_guest()
        if gid:
            await update.message.reply_text(f"🔄 已换新 guest: {gid}, 重试…")
            try:
                status, body, reason = ask_ainvest(prompt, runtime=rt)
            except Exception as e:
                await update.message.reply_text(f"⏱ 重试超时：{e}")
                return
        else:
            await update.message.reply_text("✗ 自动换新失败, 请手动 /renew")
            return
    if status != 200 or not body:
        await update.message.reply_text(f"✗ 失败 (HTTP {status}): {body[:300]}")
        return
    import re as _re
    # 抽出 Aime 吐出的图表 HTML（用于渲染成图片 preview）
    charts = _re.findall(r"<!doctype html>.*?</html>", body, flags=_re.S | _re.I)
    # 剥掉 HTML，只留文字分析
    clean = _re.sub(r"<!doctype html>.*?</html>", "", body, flags=_re.S | _re.I)
    clean = _re.sub(r"<script[\s\S]*?</script>", "", clean, flags=_re.I)
    clean = _re.sub(r"<style[\s\S]*?</style>", "", clean, flags=_re.I)
    clean = _re.sub(r"<[^>]+>", "", clean)
    clean = _re.sub(r"\n{3,}", "\n\n", clean).strip()
    body = clean or body
    # 发图表图片（如果有）
    if charts:
        try:
            import sys
            sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
            from render_aime_chart import render_chart
            for idx, ch in enumerate(charts[:3]):
                png = f"aime_chart_{idx}.png"
                if render_chart(ch, png):
                    with open(png, "rb") as f:
                        await update.message.reply_photo(f)
        except Exception as e:
            await update.message.reply_text(f"（图表渲染失败：{e}）")
    # 先发思考链（如果有）
    if reason:
        MAX = 4000
        rparts = [reason[i:i+MAX] for i in range(0, len(reason), MAX)]
        for p in rparts:
            await update.message.reply_text(f"💭 思考:\n{p}")
    # 再发最终答案
    MAX = 4000
    parts = [body[i:i+MAX] for i in range(0, len(body), MAX)]
    for p in parts:
        await update.message.reply_text(f"🤖 Aime:\n{p}")

async def cmd_kopi(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await cmd_text(update, context, override_prompt=DEFAULT_PROMPT)

async def cmd_renew(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🔄 换新 guest 中…")
    gid = renew_guest()
    await update.message.reply_text(f"✅ 新 guest: {gid}" if gid else "✗ 换新失败")

async def cmd_runtime(update: Update, context: ContextTypes.DEFAULT_TYPE):
    arg = (context.args[0] if context.args else "").strip().lower()
    if arg in ("fast", "fast-agent"):
        set_runtime("fast-agent")
        await update.message.reply_text("⚡ 已切到 fast-agent（快/约5次配额/每天）")
    elif arg in ("agent", "agent-runtime", "deep", "深度"):
        set_runtime("agent-runtime")
        await update.message.reply_text("🧠 已切到 agent-runtime（深度分析/约2次配额/每天）")
    else:
        rt = get_runtime()
        quota = "约5次/天" if rt == "fast-agent" else "约2次/天"
        await update.message.reply_text(
            f"当前模式: {rt}（{quota}）\n"
            "切换: /runtime fast  → 快/5次\n"
            "       /runtime agent → 深度/2次")

async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    rt = get_runtime()
    quota = "约5次/天" if rt == "fast-agent" else "约2次/天"
    await update.message.reply_text(f"当前 guest 身份: {current_guest()}\n当前模式: {rt}（{quota}）")

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    rt = get_runtime()
    quota = "约5次/天" if rt == "fast-agent" else "约2次/天"
    await update.message.reply_text(
        "Aime (ainvest) 马股分析 bot\n\n"
        "/fast <问题>  快速分析 (fast-agent, 约5次/天)\n"
        "/ask  <问题>  深度分析 (agent-runtime, 约2次/天)\n"
        "/kopi         快捷分析马股 Oriental Kopi\n"
        "/runtime      切换默认模式\n"
        "/renew        手动换新 guest\n"
        "/status       看当前身份+模式\n\n"
        f"当前默认模式: {rt}（{quota}），用尽自动换新。")

def main():
    if TELEGRAM_TOKEN in ("YOUR_TOKEN_HERE",""):
        print("✗ 请先在 ainvest_bot_config.py 填 TELEGRAM_TOKEN"); sys.exit(1)
    # 单实例保护 (Windows 用 msvcrt 文件锁)
    import msvcrt
    lock = open("ainvest_bot.lock","w")
    try:
        msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
    except OSError:
        print("✗ 已有 bot 实例在运行 (锁文件占用), 退出"); sys.exit(1)
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("ask", cmd_ask))
    app.add_handler(CommandHandler("fast", cmd_fast))
    app.add_handler(CommandHandler("kopi", cmd_kopi))
    app.add_handler(CommandHandler("runtime", cmd_runtime))
    app.add_handler(CommandHandler("renew", cmd_renew))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, cmd_text))
    print("bot 启动, 轮询中… (drop_pending_updates=True)")
    app.run_polling(drop_pending_updates=True,
                    allowed_updates=["message","callback_query"])

if __name__ == "__main__":
    main()