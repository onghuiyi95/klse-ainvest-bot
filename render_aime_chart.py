"""从 Aime 吐出的 ECharts HTML 里提取图表 option 并用 matplotlib 渲染成 PNG。
Aime 的图表 HTML 形如:
  const option = {xAxis:{type:"category",data:[...]}, series:[{type:"bar",name:"营收",data:[...]}, ...]};
我们抽出这段，转成 python dict，画成柱状/折线图。
"""
import re
import json
import io
import os


def _js_to_json(js: str) -> str:
    """把 JS 对象字面量尽量转成合法 JSON 字符串。"""
    s = js.strip()
    # 去尾分号
    s = s.rstrip(";").strip()
    # 单引号 -> 双引号（ECharts option 里一般字符串都用双引号，但保险）
    # 给未加引号的 key 加引号:  {xAxis:  -> {"xAxis":
    s = re.sub(r'([{,]\s*)([A-Za-z_][A-Za-z0-9_]*)\s*:', r'\1"\2":', s)
    # 去尾逗号（对象/数组最后一个元素后的逗号）
    s = re.sub(r',(\s*[}\]])', r'\1', s)
    return s


def extract_option(html: str):
    """返回 (option_dict, series_title) 或 None。用括号配对稳健提取。"""
    m = re.search(r"const\s+option\s*=\s*", html)
    if not m:
        m = re.search(r"option\s*=\s*", html)
    if not m:
        return None
    start = html.find("{", m.end())
    if start == -1:
        return None
    depth = 0
    instr = None
    escapes = 0
    i = start
    end = -1
    while i < len(html):
        c = html[i]
        if instr:
            if escapes:
                escapes = 0
            elif c == "\\":
                escapes = 1
            elif c == instr:
                instr = None
        else:
            if c in "\"'":
                instr = c
            elif c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    end = i
                    break
        i += 1
    if end == -1:
        return None
    raw = html[start:end + 1]
    try:
        obj = json.loads(_js_to_json(raw))
        return obj
    except Exception:
        return None


def render_chart(html: str, out_path: str, title: str = "") -> bool:
    """把 Aime HTML 图表渲染成 PNG。成功返回 True。"""
    opt = extract_option(html)
    if not opt:
        return False
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib import font_manager as fm
    cn = "C:/Windows/Fonts/msyh.ttc"
    if os.path.exists(cn):
        fm.fontManager.addfont(cn)
        plt.rcParams["font.family"] = fm.FontProperties(fname=cn).get_name()
    plt.rcParams["axes.unicode_minus"] = False

    x = opt.get("xAxis", {})
    if isinstance(x, list):
        x = x[0] if x else {}
    xdata = x.get("data", []) if isinstance(x, dict) else []

    series = opt.get("series", [])
    if not isinstance(series, list):
        series = [series]

    fig, ax = plt.subplots(figsize=(9, 4.6))
    chart_title = title or opt.get("title", {}).get("text", "") or "Aime 图表"
    ax.set_title(chart_title, fontsize=12)

    colors = ["#4C72B0", "#DD8452", "#55A868", "#C44E52", "#8172B3"]
    for i, s in enumerate(series):
        name = s.get("name", f"series{i}")
        data = s.get("data", [])
        color = colors[i % len(colors)]
        st = s.get("type", "bar")
        if st == "line":
            ax.plot(range(len(data)), data, marker="o", label=name, color=color)
        else:
            ax.bar(range(len(data)), data, label=name, color=color, alpha=0.85)

    if xdata:
        ax.set_xticks(range(len(xdata)))
        ax.set_xticklabels(xdata, rotation=30, ha="right", fontsize=8)
    ax.legend(fontsize=8)
    ax.grid(axis="y", alpha=0.3)
    fig.tight_layout()
    fig.savefig(out_path, dpi=130)
    plt.close(fig)
    return True


if __name__ == "__main__":
    # 自测：用一段样例 HTML
    sample = '''
    const option = {xAxis:{type:"category",data:["Q1","Q2","Q3"]},yAxis:{type:"value"},series:[{type:"bar",name:"营收",data:[97.8,103.2,116.7]},{type:"bar",name:"净利",data:[13.1,13.8,17.9]}]};
    '''
    ok = render_chart(sample, "test_chart.png", "测试图")
    print("render ok:", ok)
