#!/usr/bin/env python3
# batch_analyze.py (多线程版, 多有效 guest cookie 并发)
# 批量把马股喂给 Aime 分析，报告存 stocks.db (reports 表 10 列)
# 架构: 每个 worker 独占一个有效 guest cookie 文件并发请求; 该 guest 配额用尽(429)后尝试换新。
# 换新失败则 worker 退出 (下次跑再补)。随机 sleep 防封; 幂等: 已分析跳过, 可反复运行续跑。
# 用法:
#   python batch_analyze.py                # 全量
#   python batch_analyze.py --code 0338    # 单只(测试)
#   python batch_analyze.py --workers 4    # 指定并发数(默认=有效cookie数)
#   python batch_analyze.py --limit 20     # 限前 N 只
import os
import sys, os, re, time, random, sqlite3, threading
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import importlib.util
spec = importlib.util.spec_from_file_location("aime_telebot", r"os.path.join(os.path.dirname(os.path.abspath(__file__)), "aime_telebot.py")")
A = importlib.util.module_from_spec(spec); sys.modules["aime_telebot"]=A; spec.loader.exec_module(A)
from pathlib import Path

DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "stocks.db")
CHART_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "aime_charts")
os.makedirs(CHART_DIR, exist_ok=True)

# 扫描有效 guest cookie 文件 (跳过 cookie.txt, 它常是默认且可能耗尽)
CK_DIR = Path(os.path.dirname(os.path.abspath(__file__)))
BAD_GUESTS = {"mt_1887426093"}  # 已知持久失效身份
def collect_cookies():
    files = sorted(CK_DIR.glob("cookie_mt_*.txt"), key=lambda x: x.stat().st_mtime, reverse=True)
    out = []
    for f in files[:15]:
        gid = re.search(r"mt_(\d+)", f.name)
        if gid and gid.group(1) in BAD_GUESTS:
            continue
        out.append(str(f))
    return out

def init_reports(con):
    con.execute("""CREATE TABLE IF NOT EXISTS reports(
        code TEXT PRIMARY KEY, name TEXT, prompt TEXT, report_text TEXT,
        thinking TEXT, chart_png TEXT, raw_json TEXT, runtime TEXT,
        analyzed_at TEXT, error TEXT)""")
    con.execute("""CREATE TABLE IF NOT EXISTS errors(
        code TEXT PRIMARY KEY, name TEXT, err TEXT, at TEXT)""")
    con.commit()

def get_unanalyzed(con, code=None, limit=None):
    done = "(SELECT code FROM reports WHERE report_text IS NOT NULL AND report_text<>'')"
    if code:
        rows = con.execute(f"SELECT code,name FROM stocks WHERE code=? AND code NOT IN {done}", (code,)).fetchall()
    else:
        rows = con.execute(f"SELECT code,name FROM stocks WHERE code NOT IN {done} ORDER BY code").fetchall()
    if limit:
        rows = rows[:limit]
    return rows

def save_report(con, code, name, prompt, report, thinking, chart_png, raw, runtime):
    con.execute("""INSERT OR REPLACE INTO reports
        (code,name,prompt,report_text,thinking,chart_png,raw_json,runtime,analyzed_at,error)
        VALUES(?,?,?,?,?,?,?,?,datetime('now'),NULL)""",
        (code, name, prompt, report, thinking, chart_png, raw, runtime))
    con.commit()

def save_error(con, code, name, err):
    con.execute("INSERT OR REPLACE INTO errors VALUES(?,?,?,datetime('now'))", (code, name, err[:200]))
    con.commit()

def render_chart(html, png):
    try:
        from render_aime_chart import render_chart as rc
        return rc(html, png)
    except Exception:
        return False

_renew_lock = threading.Lock()
def new_guest_from_browser():
    """调 simulate_guest.py 换新 guest, 返回新 cookie 内容或 None (带超时+重试)。锁保护。"""
    with _renew_lock:
        for attempt in range(3):
            try:
                out = subprocess.run([sys.executable, os.path.join(os.path.dirname(os.path.abspath(__file__)), "simulate_guest.py")],
                                     capture_output=True, text=True, timeout=45).stdout
                m = re.search(r"新 guest id:\s*(mt_\d+)", out)
                if m:
                    gid = m.group(1)
                    p = f'{os.path.join(os.path.dirname(os.path.abspath(__file__)), "cookie_"+gid+".txt")}'
                    if os.path.exists(p):
                        return open(p, encoding="utf-8", errors="ignore").read().strip()
            except Exception:
                pass
            time.sleep(8)  # browseros 偶发卡, 等一会重试
    return None

def worker(wid, ckpaths, codes, runtime):
    con = sqlite3.connect(DB)
    ck_idx = 0
    ck = open(ckpaths[ck_idx], encoding="utf-8", errors="ignore").read().strip()
    for code, name in codes:
        if con.execute("SELECT 1 FROM reports WHERE code=? AND report_text IS NOT NULL AND report_text<>''", (code,)).fetchone():
            continue
        try:
            prompt = f"分析马股 {name} ({code}.KL)，给出基本面、估值、技术面与关键风险结论"
            status, body, thinking = A.ask_ainvest(prompt, runtime=runtime, cookie=ck)
        except Exception as e:
            print(f"[w{wid}] {code} {name} ✗ EXC:{e}", flush=True)
            save_error(con, code, name, f"EXC:{e}")
            time.sleep(random.uniform(5, 12))
            continue
        if status == 429:
            # 该 guest 配额耗尽, 先换列表里下一个文件
            ck_idx += 1
            if ck_idx < len(ckpaths):
                ck = open(ckpaths[ck_idx], encoding="utf-8", errors="ignore").read().strip()
                print(f"[w{wid}] {code} {name} ✗ 429, 换 guest #{ck_idx} 继续", flush=True)
                time.sleep(2)
                continue
            # 文件列表用尽, 调 browseros 生成新 guest
            print(f"[w{wid}] {code} {name} ✗ 429, 调 browseros 换新 guest…", flush=True)
            nk = new_guest_from_browser()
            if nk:
                ck = nk
                ckpaths.append("__live__")  # 标记已用动态 guest (避免重复)
                print(f"[w{wid}] 新 guest 就绪, 继续", flush=True)
                time.sleep(2)
                continue
            else:
                # 换新失败 (browseros 偶发卡): 不退出, 等恢复后重试同一只
                waited = 0
                while waited < 150:
                    print(f"[w{wid}] {code} {name} ✗ 换新失败, 等 30s browseros 恢复…", flush=True)
                    time.sleep(30); waited += 30
                    nk = new_guest_from_browser()
                    if nk:
                        ck = nk
                        ckpaths.append("__live__")
                        print(f"[w{wid}] 新 guest 就绪, 继续", flush=True)
                        time.sleep(2)
                        break
                if not nk:
                    print(f"[w{wid}] {code} {name} ✗ 多次换新失败, 跳过本只", flush=True)
                    save_error(con, code, name, "HTTP_429_noguest")
                    time.sleep(10)
                    continue  # 跳过这只, 继续下一只 (而非退出整个 worker)
                continue
        if status in (401, 403):
            print(f"[w{wid}] {code} {name} ✗ HTTP {status}, worker 退出", flush=True)
            return
        if status == 200 and body:
            chart_png = None
            try:
                charts = re.findall(r"<!doctype html>.*?</html>", body, flags=re.S|re.I)
                if charts:
                    png = os.path.join(CHART_DIR, f"{code}.png")
                    if render_chart(charts[0], png):
                        chart_png = png
            except Exception:
                chart_png = None
            clean = re.sub(r"<!doctype html>.*?</html>", "", body, flags=re.S|re.I)
            clean = re.sub(r"<[^>]+>", "", clean)
            clean = re.sub(r"\n{3,}", "\n\n", clean).strip()
            save_report(con, code, name, f"分析马股 {name} ({code}.KL)", clean or body, thinking, chart_png, body, runtime)
            print(f"[w{wid}] {code} {name} ✓ ({len(clean or body)}字)", flush=True)
        else:
            print(f"[w{wid}] {code} {name} ✗ HTTP {status}: {body[:100] if body else ''}", flush=True)
            save_error(con, code, name, f"HTTP_{status}:{body[:120] if body else ''}")
        time.sleep(random.uniform(2, 6))
    print(f"[w{wid}] 本 worker 任务完成", flush=True)

def main():
    workers = None
    if "--workers" in sys.argv:
        workers = int(sys.argv[sys.argv.index("--workers")+1])
    code = None
    if "--code" in sys.argv:
        code = sys.argv[sys.argv.index("--code")+1]
    limit = None
    if "--limit" in sys.argv:
        limit = int(sys.argv[sys.argv.index("--limit")+1])

    cks = collect_cookies()
    if not cks:
        print("✗ 没有有效的 cookie_mt_*.txt, 无法启动。请先运行 simulate_guest.py 生成。"); return
    print(f"发现 {len(cks)} 个 guest cookie 文件")
    if workers is None:
        workers = len(cks)

    con = sqlite3.connect(DB)
    init_reports(con)
    todo = get_unanalyzed(con, code=code, limit=limit)
    con.close()
    print(f"待分析: {len(todo)} 只, workers={workers}")
    if not todo:
        print("全部完成 ✓"); return
    runtime = "fast-agent"

    # 均分任务给各 worker, 每个 worker 绑定一个 cookie 文件
    chunks = [[] for _ in range(workers)]
    for i, row in enumerate(todo):
        chunks[i % workers].append(row)

    threads = []
    for i in range(workers):
        # 每个 worker 拿到全部有效 cookie 列表, 一个 guest 配额用尽自动换下一个
        t = threading.Thread(target=worker, args=(i, cks, chunks[i], runtime), daemon=True)
        t.start(); threads.append(t)
    for t in threads:
        t.join()
    print("本轮完成 ✓ 报告存于 stocks.db")

if __name__ == "__main__":
    main()