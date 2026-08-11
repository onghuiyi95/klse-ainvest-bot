#!/usr/bin/env python3
# scrape_klse.py — 抓 KLSE Screener 全部股票列表，写入 stocks.db
import os
import requests, re, sqlite3, os

URL = "https://www.klsescreener.com/v2/screener/quote_results"
DB  = os.path.join(os.path.dirname(os.path.abspath(__file__)), "stocks.db")
HDR = {"user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/151.0.0.0 Safari/537.36",
       "accept": "text/html,application/xhtml+xml",
       "accept-language": "en-US,en;q=0.9"}

def fetch():
    r = requests.get(URL, headers=HDR, timeout=30)
    r.raise_for_status()
    return r.text

def parse(html):
    # 每个股票行: <tr class="list"> ... </tr>
    rows = re.findall(r"<tr class=\"list\">(.*?)</tr>", html, re.S)
    stocks = []
    for row in rows:
        cells = re.findall(r"<td[^>]*>(.*?)</td>", row, re.S)
        if len(cells) < 14:
            continue
        def clean(c):
            c = re.sub(r"<[^>]+>", " ", c)
            return re.sub(r"\s+", " ", c).replace("&nbsp;", " ").strip()
        cells = [clean(c) for c in cells]
        name, code = cells[0], cells[1]
        cat = cells[2]
        price, chg, chgp = cells[3], cells[4], cells[5]
        w52 = cells[6]
        vol, eps, dps, nta, pe, dy, roe = cells[7], cells[8], cells[9], cells[10], cells[11], cells[12], cells[13]
        m = re.search(r"\d{4}", code)
        if not m:
            continue
        stocks.append({
            "code": m.group(0), "name": name, "category": cat,
            "price": price, "change": chg, "change_pct": chgp,
            "week52": w52, "volume": vol, "eps": eps, "dps": dps,
            "nta": nta, "pe": pe, "dy": dy, "roe": roe,
        })
    return stocks

def save(db, stocks):
    con = sqlite3.connect(db)
    cur = con.cursor()
    cur.execute("""
    CREATE TABLE IF NOT EXISTS stocks (
        code TEXT PRIMARY KEY,
        name TEXT,
        category TEXT,
        price TEXT,
        change TEXT,
        change_pct TEXT,
        week52 TEXT,
        volume TEXT,
        eps TEXT,
        dps TEXT,
        nta TEXT,
        pe TEXT,
        dy TEXT,
        roe TEXT,
        analyzed INTEGER DEFAULT 0,
        last_error TEXT
    )""")
    for s in stocks:
        cur.execute("""INSERT OR REPLACE INTO stocks
            (code,name,category,price,change,change_pct,week52,volume,eps,dps,nta,pe,dy,roe)
            VALUES (:code,:name,:category,:price,:change,:change_pct,:week52,:volume,:eps,:dps,:nta,:pe,:dy,:roe)""", s)
    con.commit()
    n = cur.execute("SELECT COUNT(*) FROM stocks").fetchone()[0]
    con.close()
    return n

if __name__ == "__main__":
    print("抓取 KLSE Screener ...")
    html = fetch()
    stocks = parse(html)
    print(f"解析到 {len(stocks)} 只")
    n = save(DB, stocks)
    print(f"已写入 stocks.db, 共 {n} 只股票")