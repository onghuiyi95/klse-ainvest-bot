#!/usr/bin/env python3
# run_daemon.py — 马股批量分析守护进程
# 自动循环: 跑 batch -> 配额尽/退出 -> 检查 browseros 补生成新 guest -> 再跑
# 直到全部股票分析完。后台运行, 不依赖终端。每轮把进度写入 daemon.log。
# 停止: 用任务管理器结束 run_daemon.py 进程, 或删除 daemon.stop 文件。
import subprocess, os, sys, time, glob
from pathlib import Path

CWD = Path(os.path.dirname(os.path.abspath(__file__)))
VENV = CWD/"ai-shisho/.venv/Scripts/python.exe"
DB = r"os.path.join(os.path.dirname(os.path.abspath(__file__)), "stocks.db")"
STOP = CWD/"daemon.stop"

def log(msg):
    with open(CWD/"daemon.log", "a", encoding="utf-8") as f:
        f.write(f"[{time.strftime('%H:%M:%S')}] {msg}\n")

def db_count():
    try:
        import sqlite3
        c = sqlite3.connect(DB)
        tot = c.execute("SELECT COUNT(*) FROM stocks").fetchone()[0]
        done = c.execute("SELECT COUNT(*) FROM reports").fetchone()[0]
        c.close()
        return tot, done
    except Exception as e:
        return 0, 0

def gen_guests(n=8):
    """趁 browseros 好时补生成 n 个 guest, 返回成功数"""
    ok = 0
    for i in range(n):
        if STOP.exists():
            break
        try:
            r = subprocess.run([str(VENV), "-u", "simulate_guest.py"], cwd=str(CWD),
                capture_output=True, text=True, encoding="utf-8", errors="ignore", timeout=50)
            if "新 guest id:" in r.stdout:
                ok += 1
        except Exception:
            pass
        time.sleep(2)
    return ok

def run_batch():
    """跑一轮 batch (workers 自适应 guest 数), 返回退出码"""
    p = subprocess.run([str(VENV), "-B", "-u", "batch_analyze.py", "--workers", "10"],
        cwd=str(CWD), capture_output=True, text=True, encoding="utf-8", errors="ignore",
        timeout=1800)
    return p.returncode

if __name__ == "__main__":
    if STOP.exists():
        STOP.unlink()
    # 单实例保护: pid 文件 + 进程存活检查
    lock = CWD/"daemon.lock"
    if lock.exists():
        try:
            old = int(lock.read_text(encoding="utf-8", errors="ignore").strip())
            import os as _os
            _os.kill(old, 0)  # 进程存活则抛错? 不, 存活不抛, 不存在抛 OSError
            print("已有守护进程在运行(pid=%d), 退出" % old); log("已有实例 pid=%d, 退出" % old); raise SystemExit
        except (OSError, ValueError):
            pass  # 旧 pid 不存在, 可覆盖
    lock.write_text(str(os.getpid()))
    log("=== 守护进程启动 ===")
    round_n = 0
    while not STOP.exists():
        tot, done = db_count()
        if done >= tot:
            log(f"全部完成! {done}/{tot}")
            break
        round_n += 1
        log(f"第 {round_n} 轮 开始 | 进度 {done}/{tot} | 现有 guest 文件 {len(list(CWD.glob('cookie_mt_*.txt')))}")
        # 先补 guest (防止本轮配额不足)
        before = len(list(CWD.glob("cookie_mt_*.txt")))
        ok = gen_guests(8)
        log(f"补生成 guest: {ok} 个 (现有 {len(list(CWD.glob('cookie_mt_*.txt')))} 个)")
        # 跑 batch
        try:
            rc = run_batch()
        except subprocess.TimeoutExpired:
            log("batch 超时(>30min), 强制结束本轮")
        _, done2 = db_count()
        log(f"第 {round_n} 轮 结束 | 进度 {done2}/{tot} (本轮 +{done2-done})")
        # 若没进展且 browseros 持续卡, 等久一点再试
        if done2 == done:
            log("本轮无进展(browseros 可能卡), 等 60s 再试")
            time.sleep(60)
        else:
            time.sleep(5)
    log("=== 守护进程退出 ===")
