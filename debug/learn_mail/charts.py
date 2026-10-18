"""One chart definition, two outputs.

Each builder returns a Vega-Lite chart. The web page embeds its JSON and lets
the browser draw it with hover tooltips; the email gets the same spec turned
into a PNG by vl-convert, without a browser. ``interactive=False`` drops only
the hover layers, so the two outputs cannot drift apart.
"""
from __future__ import annotations

import altair as alt
import pandas as pd

BLUE, GRAY = "#2a78d6", "#898781"
INK, INK2, MUTED, GRID, AXIS = "#0b0b0b", "#4d5158", "#898781", "#e1e0d9", "#c3c2b7"
WEB_FONT = "PingFang SC, Hiragino Sans, Noto Sans SC, Noto Sans CJK SC, Microsoft YaHei, sans-serif"
PNG_FONT = "Noto Sans CJK SC"
PCT_LABEL = "(datum.value > 0 ? '+' : '') + datum.value + '%'"


def _pct(v: float) -> str:
    return f"{'+' if v > 0 else ''}{v:.1f}%"


def _md(iso: str) -> str:
    _, m, d = iso.split("-")
    return f"{int(m)}/{int(d)}"


def _finish(chart: alt.TopLevelMixin, *, width: int | str, height: int, font: str) -> alt.TopLevelMixin:
    autosize = alt.AutoSizeParams(type="fit-x", contains="padding") if width == "container" else "pad"
    return (chart.properties(width=width, height=height, autosize=autosize)
            .configure(font=font, background="#fcfcfb")
            .configure_view(stroke=None)
            .configure_axis(labelColor=MUTED, labelFontSize=12, gridColor=GRID, domain=False,
                            tickColor=AXIS, titleColor=INK2)
            .configure_legend(labelColor=INK2, labelFontSize=13, symbolStrokeWidth=3))


def reaction_chart(case: dict, name: str, *, interactive: bool, width: int | str = 640,
                   height: int = 300, font: str = WEB_FONT) -> alt.TopLevelMixin:
    """Stock vs market, both indexed to 0% at the last pre-news close."""
    s = pd.DataFrame(case["series"])
    s["date"] = pd.to_datetime(s["date"])
    long = s.melt(id_vars=["date", "rel", "close"], value_vars=["stock", "bench"],
                  var_name="k", value_name="pct")
    long["series"] = long["k"].map({"stock": name, "bench": "大盘"})

    x = alt.X("date:T", title=None, axis=alt.Axis(format="%-m/%-d", tickCount=6, grid=False))
    y = alt.Y("pct:Q", title=None, axis=alt.Axis(labelExpr=PCT_LABEL, tickCount=6))
    color = alt.Color("series:N", title=None, legend=alt.Legend(orient="top"),
                      scale=alt.Scale(domain=[name, "大盘"], range=[BLUE, GRAY]))

    zero = alt.Chart(pd.DataFrame({"y": [0]})).mark_rule(color=AXIS).encode(y="y:Q")
    lines = alt.Chart(long).mark_line(strokeWidth=2, strokeJoin="round").encode(x=x, y=y, color=color)

    i0 = s.index[s["rel"] == 0][0]
    mid = s["date"][i0] + (s["date"][i0 + 1] - s["date"][i0]) / 2
    when = "收盘后" if case["event"]["after_close"] else "开盘前"
    ev = pd.DataFrame({"date": [mid], "label": [f"{_md(case['event']['announce'])} {when}\n公布财报"]})
    event_rule = alt.Chart(ev).mark_rule(strokeDash=[4, 4], color=INK2).encode(x="date:T")
    event_text = alt.Chart(ev).mark_text(align="right", baseline="top", dx=-6, fontSize=12.5, color=INK, lineBreak="\n").encode(
        x="date:T", y=alt.value(2), text="label:N")

    marks = s[s["rel"].isin([1, 5, 20])].assign(label=lambda d: d["rel"].map(lambda r: f"{r} 天后"))
    dots = alt.Chart(marks).mark_point(filled=True, size=70, color=BLUE, stroke="white",
                                       strokeWidth=2, opacity=1).encode(x="date:T", y="stock:Q")
    first = alt.Chart(marks[marks["rel"] == 1]).mark_text(align="right", dx=-9, dy=4, fontSize=12, color=INK2)
    # Later markers sit below-right: by then the line is usually climbing back,
    # so that corner is the one most likely to be empty.
    rest = alt.Chart(marks[marks["rel"] != 1]).mark_text(align="left", dx=5, dy=17, fontSize=12, color=INK2)
    dot_labels = [c.encode(x="date:T", y="stock:Q", text="label:N") for c in (first, rest)]

    last = s.iloc[-1]
    span = float(long["pct"].max() - long["pct"].min()) or 1.0
    ys, yb = float(last["stock"]), float(last["bench"])
    if abs(ys - yb) < span * 0.12:                       # keep the two end labels apart
        mid_y, push = (ys + yb) / 2, span * 0.06
        ys, yb = (mid_y + push, mid_y - push) if ys >= yb else (mid_y - push, mid_y + push)
    ends = pd.DataFrame({"date": [last["date"]] * 2, "y": [ys, yb],
                         "text": [f"{name} {_pct(last['stock'])}", f"大盘 {_pct(last['bench'])}"]})
    end_labels = alt.Chart(ends).mark_text(align="left", dx=8, fontSize=12.5, color=INK, fontWeight=600).encode(
        x="date:T", y="y:Q", text="text:N")

    layers = [zero, lines, event_rule, event_text, dots, *dot_labels, end_labels]
    if interactive:
        hover = alt.selection_point(nearest=True, on="pointerover", fields=["date"], empty=False,
                                    clear="pointerout")
        wide = s.assign(when=s["rel"].map(lambda r: "公布前最后一个收盘" if r == 0
                                          else f"财报后第 {r} 个交易日" if r > 0 else f"财报前 {-r} 个交易日"))
        layers += [
            alt.Chart(wide).mark_rule(color=GRAY, strokeWidth=1).encode(
                x="date:T",
                opacity=alt.condition(hover, alt.value(0.8), alt.value(0)),
                tooltip=[alt.Tooltip("date:T", title="日期", format="%Y-%m-%d"),
                         alt.Tooltip("when:N", title="时点"),
                         alt.Tooltip("stock:Q", title=name, format="+.1f"),
                         alt.Tooltip("bench:Q", title="大盘", format="+.1f"),
                         alt.Tooltip("close:Q", title="收盘价(美元)", format=".2f")],
            ).add_params(hover),
            alt.Chart(long).mark_point(filled=True, size=60, opacity=1).encode(
                x=x, y=y, color=color).transform_filter(hover),
        ]
    chart = alt.layer(*layers).properties(padding={"left": 4, "right": 92, "top": 8, "bottom": 4})
    return _finish(chart, width=width, height=height, font=font)


def history_chart(case: dict, *, interactive: bool, width: int | str = 640,
                  height: int = 240, font: str = WEB_FONT) -> alt.TopLevelMixin:
    """Next-day move after each of the last N announcements; the latest is solid."""
    h = pd.DataFrame(case["history"])
    h["label"] = h["announce"].map(lambda a: f"{a[2:4]}/{int(a[5:7])}")
    h["latest"] = h.index == h.index[-1]
    h["text"] = h["d1"].map(_pct)
    x = alt.X("label:N", sort=None, title=None, axis=alt.Axis(labelAngle=0, grid=False))
    y = alt.Y("d1:Q", title=None, axis=alt.Axis(labelExpr=PCT_LABEL, tickCount=5),
              scale=alt.Scale(nice=True, padding=18))
    tip = [alt.Tooltip("announce:N", title="公布日"), alt.Tooltip("est:Q", title="预期", format=".2f"),
           alt.Tooltip("act:Q", title="实际", format=".2f"),
           alt.Tooltip("surprise:Q", title="高出预期(%)", format="+.1f"),
           alt.Tooltip("d1:Q", title="第二天(%)", format="+.1f")] if interactive else alt.Undefined
    zero = alt.Chart(pd.DataFrame({"y": [0]})).mark_rule(color=AXIS, strokeWidth=1.5).encode(y="y:Q")
    bars = alt.Chart(h).mark_bar(color=BLUE, cornerRadiusEnd=4, size=26).encode(
        x=x, y=y, opacity=alt.condition("datum.latest", alt.value(1), alt.value(0.5)), tooltip=tip)
    up = alt.Chart(h).transform_filter("datum.d1 >= 0").mark_text(dy=-8, fontSize=12, color=INK)
    down = alt.Chart(h).transform_filter("datum.d1 < 0").mark_text(dy=10, fontSize=12, color=INK)
    labels = [c.encode(x=x, y="d1:Q", text="text:N") for c in (up, down)]
    return _finish(alt.layer(zero, bars, *labels), width=width, height=height, font=font)


def to_png(chart: alt.TopLevelMixin, *, scale: float = 2) -> bytes:
    import vl_convert as vlc

    vlc.register_font_directory("/usr/share/fonts/opentype/noto")
    return vlc.vegalite_to_png(chart.to_json(), scale=scale)
