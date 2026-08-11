#!/usr/bin/env python3
# watchdog.py — 自动巡检守护: 确保 batch 持续跑, 不用人工问
# 循环: 查 batch 是否活 -> 死了就补 guest (browseros) + 重启 batch
#       -> 活但 5 分钟无进展(卡死)也重启 -> 直到 1095 只全完成
# 后台运行, 写 watchdog.log。停止: 删 watchdog.stop 文件 或 结束进程。
import os
import subprocess, os, time, sqlite3
from pathlib import Path

CWD = Path(os.path.dirname(os.path.abspath(__file__)))
VENV = str(CWD/"ai-shisho/.venv/Scripts/python.exe")
DB = r"os.path.join(os.path.dirname(os.path.abspath(__file__)), "stocks.db")"
STOP = CWD/"watchdog.stop"
GEN = CWD/"_gen_guests.py"

def log(m):
    with open(CWD/"watchdog.log","a",encoding="utf-8") as f:
        f.write(f"[{time.strftime('%H:%M:%S')}] {m}\n")

def count():
    try:
        c = sqlite3.connect(DB)
        n = c.execute("SELECT COUNT(*) FROM reports WHERE report_text IS NOT NULL AND report_text<>''").fetchone()[0]
        c.close(); return n
    except: return 0

def batch_alive():
    r = subprocess.run(["wmic","process","where","commandline like '%batch_analyze%' and not commandline like '%wmic%'","get","processid"],
                       capture_output=True,text=True,encoding="utf-8",errors="ignore")
    return bool([l.strip() for l in r.stdout.split() if l.strip().isdigit()])

def gen_guests(n=10):
    ok=0
    for _ in range(n):
        if STOP.exists(): break
        try:
            r = subprocess.run([VENV,"-u","simulate_guest.py"],cwd=str(CWD),
                capture_output=True,text=True,encoding="utf-8",errors="ignore",timeout=50)
            if "新 guest id:" in r.stdout: ok+=1
        except: pass
        time.sleep(2)
    return ok

def launch_batch():
    subprocess.Popen([VENV,"-B","-u","batch_analyze.py","--workers","12"],cwd=str(CWD),
        stdout=open(CWD/"batch_log.txt","w"),stderr=subprocess.STDOUT,
        creationflags=subprocess.DETACHED_PROCESS|subprocess.CREATE_NEW_PROCESS_GROUP, close_fds=True)

if __name__ == "__main__":
    if STOP.exists(): STOP.unlink()
    log("=== 巡检守护启动 ===")
    last = count(); last_t = time.time()
    while not STOP.exists():
        tot = 1095
        n = count()
        alive = batch_alive()
        # 完成则退出
        if n >= tot:
            log(f"全部完成 {n}/{tot}, 守护退出"); break
        if alive:
            # 活但 2 分钟没进展(worker 全卡死/退出) -> 杀掉重启
            if n > last:
                last = n; last_t = time.time()
                log(f"batch 运行中 | 进度 {n}/{tot}")
            elif time.time() - last_t > 120:
                log(f"batch 卡死/无产出(>2min {last}->无), 重启")
                subprocess.run(["wmic","process","where","commandline like '%batch_analyze%' and not commandline like '%wmic%'","delete"],capture_output=True,text=True,encoding="utf-8",errors="ignore")
                time.sleep(3)
                gen_guests(10)
                launch_batch(); last_t = time.time()
            else:
                log(f"batch 运行中(暂未新增) | 进度 {n}/{tot}")
        else:
            # 死了 -> 补 guest + 重启
            log(f"batch 已停 | 进度 {n}/{tot} | 补 guest…")
            gen_guests(10)
            launch_batch()
            last = n; last_t = time.time()
        time.sleep(60)
    log("=== 巡检守护退出 ===")