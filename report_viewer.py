#!/usr/bin/env python3
# report_viewer.py — 马股分析报告网页查看器 (Flask)
# 连接 stocks.db, 列出股票 + 分析状态, 点击查看完整报告。
# 用法: python report_viewer.py   ->  http://localhost:5000
import os
import sqlite3, os
from pathlib import Path
from flask import Flask, request, render_template_string, send_file, abort

DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "stocks.db")
CHART_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "aime_charts")
app = Flask(__name__)

def db():
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    return con

def get_stocks(q="", only_unanalyzed=0, page=1, perpage=100):
    con = db()
    w = []
    params = []
    if q:
        w.append("(s.code LIKE ? OR s.name LIKE ?)")
        params += [f"%{q}%", f"%{q}%"]
    if only_unanalyzed:
        w.append("r.code IS NULL")
    where = ("WHERE " + " AND ".join(w)) if w else ""
    total = con.execute(f"""
        SELECT COUNT(*) FROM stocks s
        LEFT JOIN reports r ON s.code=r.code {where}""", params).fetchone()[0]
    rows = con.execute(f"""
        SELECT s.code, s.name, s.category, s.price, s.change_pct, s.pe, s.dy, s.roe,
               r.code AS done, r.analyzed_at
        FROM stocks s
        LEFT JOIN reports r ON s.code=r.code
        {where}
        ORDER BY s.code
        LIMIT ? OFFSET ?""", params + [perpage, (page-1)*perpage]).fetchall()
    con.close()
    return rows, total

LIST_TPL = """<!doctype html>
<html lang="zh"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>马股分析报告</title>
<style>
 *{box-sizing:border-box}
 body{font-family:-apple-system,"Segoe UI",Roboto,"PingFang SC","Microsoft YaHei",sans-serif;margin:0;background:#f4f6f9;color:#1f2733}
 header{background:#15314b;color:#fff;padding:14px 20px;display:flex;gap:12px;align-items:center;flex-wrap:wrap}
 header h1{font-size:18px;margin:0;font-weight:600}
 .wrap{max-width:1180px;margin:0 auto;padding:16px}
 .bar{display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin-bottom:12px}
 input[type=text]{padding:8px 12px;border:1px solid #cbd3dc;border-radius:8px;font-size:14px;min-width:220px}
 button{padding:8px 14px;border:0;border-radius:8px;background:#2563eb;color:#fff;cursor:pointer;font-size:14px}
 button.ghost{background:#e2e8f0;color:#1f2733}
 .count{color:#5b6b7c;font-size:13px;margin-left:auto}
 table{width:100%;border-collapse:collapse;background:#fff;border-radius:10px;overflow:hidden;box-shadow:0 1px 3px rgba(0,0,0,.08)}
 th,td{padding:9px 10px;text-align:left;border-bottom:1px solid #eef1f5;font-size:13px;white-space:nowrap}
 th{background:#f8fafc;color:#5b6b7c;font-weight:600}
 tr:hover{background:#f7faff}
 td.num{text-align:right;font-variant-numeric:tabular-nums}
 a.code{color:#2563eb;text-decoration:none;font-weight:600}
 a.code:hover{text-decoration:underline}
 .tag{display:inline-block;padding:2px 8px;border-radius:20px;font-size:11px}
 .done{background:#dcfce7;color:#166534}
 .todo{background:#fee2e2;color:#991b1b}
 .up{color:#16a34a}.down{color:#dc2626}
 .muted{color:#94a3b8}
 .pager{margin-top:14px;display:flex;gap:8px;align-items:center}
</style></head>
<body>
<header><h1>📊 马股 Aime 分析报告</h1>
 <span class="muted" id="ts"></span></header>
<div class="wrap">
 <form class="bar" method="get">
   <input type="text" name="q" value="{{q}}" placeholder="搜索代码或名称, 如 0338 或 ORIENTAL">
   <label style="font-size:13px;color:#5b6b7c"><input type="checkbox" name="todo" value="1" {{'checked' if todo else ''}}> 仅未分析</label>
   <button>搜索</button>
   <button type="button" class="ghost" onclick="location.reload()">↻ 刷新</button>
   <span class="count">共 {{total}} 只 · 已分析 {{done_count}} 只</span>
 </form>
 <table>
  <tr><th>代码</th><th>名称</th><th>板块</th><th class="num">现价</th><th class="num">涨跌%</th><th class="num">PE</th><th class="num">DY%</th><th class="num">ROE%</th><th>状态</th><th>分析时间</th></tr>
  {% for r in rows %}
  <tr>
    <td><a class="code" href="/report/{{r.code}}">{{r.code}}</a></td>
    <td>{{r.name}}</td>
    <td class="muted">{{r.category[:28]}}</td>
    <td class="num">{{r.price}}</td>
    <td class="num {% if r.change_pct.startswith('-') %}down{% else %}up{% endif %}">{{r.change_pct}}</td>
    <td class="num">{{r.pe}}</td>
    <td class="num">{{r.dy}}</td>
    <td class="num">{{r.roe}}</td>
    <td>{% if r.done %}<span class="tag done">✓ 已分析</span>{% else %}<span class="tag todo">未分析</span>{% endif %}</td>
    <td class="muted">{{r.analyzed_at or ''}}</td>
  </tr>
  {% endfor %}
 </table>
 <div class="pager">
   {% if page>1 %}<a href="?q={{q}}&todo={{todo}}&page={{page-1}}"><button class="ghost">← 上一页</button></a>{% endif %}
   <span class="muted">第 {{page}} 页</span>
   {% if page*perpage<total %}<a href="?q={{q}}&todo={{todo}}&page={{page+1}}"><button class="ghost">下一页 →</button></a>{% endif %}
 </div>
</div>
<script>document.getElementById('ts').textContent='更新于 '+new Date().toLocaleString();</script>
</body></html>"""

REPORT_TPL = """<!doctype html>
<html lang="zh"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{{r.name}} 报告</title>
<style>
 body{font-family:-apple-system,"Segoe UI",Roboto,"PingFang SC","Microsoft YaHei",sans-serif;margin:0;background:#f4f6f9;color:#1f2733}
 header{background:#15314b;color:#fff;padding:14px 20px}
 header a{color:#9ecbff;text-decoration:none;font-size:13px}
 .wrap{max-width:860px;margin:0 auto;padding:20px}
 .meta{color:#5b6b7c;font-size:13px;margin-bottom:16px}
 .card{background:#fff;border-radius:10px;padding:20px;box-shadow:0 1px 3px rgba(0,0,0,.08);line-height:1.7;font-size:15px;white-space:pre-wrap;word-wrap:break-word}
 h2{margin:22px 0 8px;font-size:15px;color:#5b6b7c}
 .think{background:#f8fafc;border-left:3px solid #cbd5e1;padding:12px 16px;border-radius:6px;color:#475569;white-space:pre-wrap;font-size:13px}
 img{max-width:100%;border-radius:8px;margin-top:8px}
</style></head>
<body>
<header><a href="/">← 返回列表</a> &nbsp; {{r.code}} {{r.name}}</header>
<div class="wrap">
 <div class="meta">分析时间: {{r.analyzed_at}} · 模式: {{r.runtime}}</div>
 <h2>📋 Aime 分析报告</h2>
 <div class="card">{{r.report_text}}</div>
 {% if r.thinking %}<h2>💭 思考链</h2><div class="think">{{r.thinking}}</div>{% endif %}
 {% if chart %}<h2>📈 图表</h2><img src="{{chart}}" alt="chart">{% endif %}
</div>
</body></html>"""

@app.route("/")
def index():
    q = request.args.get("q", "").strip()
    todo = request.args.get("todo", "0") == "1"
    page = max(1, int(request.args.get("page", 1)))
    rows, total = get_stocks(q, 1 if todo else 0, page)
    done_count = db().execute("SELECT COUNT(*) FROM reports").fetchone()[0]
    perpage = 100
    return render_template_string(LIST_TPL, rows=rows, total=total, q=q, todo=1 if todo else 0,
                                  page=page, perpage=perpage, done_count=done_count)

@app.route("/report/<code>")
def report(code):
    con = db()
    r = con.execute("SELECT * FROM reports WHERE code=?", (code,)).fetchone()
    con.close()
    if not r:
        abort(404, "尚未分析")
    chart = None
    if r["chart_png"] and os.path.exists(r["chart_png"]):
        rel = os.path.relpath(r["chart_png"], os.getcwd())
        chart = "/" + rel.replace("\\", "/")
    return render_template_string(REPORT_TPL, r=r, chart=chart)

if __name__ == "__main__":
    print("报告查看器启动: http://localhost:5000")
    app.run(host="0.0.0.0", port=5000, debug=False, threaded=True)