"""Turn the facts of an earnings case into the words of a lesson.

The copy makes claims ("every quarter beat", "the market rose that day"). Each
claim is checked against the data here; when a case does not fit, building
fails loudly instead of printing a sentence that is no longer true.
"""
from __future__ import annotations

GLOSSARY = [
    ("财报", "公司每三个月公布一次的成绩单,写明这段时间卖了多少、赚了多少。"),
    ("每股盈利", "公司赚的钱除以股票总数。英文缩写是 EPS。"),
    ("分析师预期", "专门研究这家公司的人事先估的数,取平均。它是公开的,所以股价里已经算进去了。"),
    ("超预期", "实际公布的数比预期高。反过来叫不及预期。"),
    ("收盘后公布", "美股下午 4 点收盘。公司常在收盘后发财报,所以股价要到下一个交易日才反应。"),
    ("大盘", "市场整体。这里用标普 500 指数代表,它包含美国最大的 500 家上市公司。"),
    ("交易日", "股市开门的日子,不含周末和节假日。20 个交易日大约是一个月。"),
]


def pct(v: float, signed: bool = True) -> str:
    return f"{'+' if signed and v > 0 else ''}{v:.1f}%"


def _move(v: float) -> str:
    return f"{'涨' if v >= 0 else '跌'}了 {abs(v):.1f}%"


def earnings_lesson(case: dict, company: dict) -> dict:
    """``company`` carries what data cannot: name, one-line intro, the quarter."""
    ev, hist, name = case["event"], case["history"], company["name"]
    n, up = len(hist), sum(r["d1"] > 0 for r in hist)
    if not all(r["surprise"] > 0 for r in hist):
        raise ValueError("copy says every quarter beat; this case has a miss")
    if up == n:
        raise ValueError("copy teaches that beats can fall; here every beat rose")
    y, m, d = ev["announce"].split("-")
    when = "收盘后" if ev["after_close"] else "开盘前"

    vs = ev["d1"] - ev["b1"]
    if ev["d1"] < 0 < ev["b1"]:
        why_market = f"这一次大盘在涨,{name}在跌,所以这次下跌是冲着{name}来的。"
    elif ev["d1"] > 0 > ev["b1"]:
        why_market = f"这一次大盘在跌,{name}在涨,所以这次上涨是{name}自己的。"
    else:
        why_market = f"这一次两者同向,{name}比大盘{'多' if vs > 0 else '少'}{'涨' if ev['d1'] >= 0 else '跌'}了 {abs(vs):.1f} 个百分点,差出来的这部分才算{name}自己的。"

    after = [(label, pct(ev[a]), pct(ev[b]), f"{'+' if ev[a] - ev[b] > 0 else ''}{ev[a] - ev[b]:.1f} 个百分点")
             for label, a, b in (("第二天", "d1", "b1"), ("5 个交易日后", "d5", "b5"), ("20 个交易日后", "d20", "b20"))
             if ev[a] is not None]
    history_rows = [dict(announce=r["announce"], est=f"{r['est']:.2f}", act=f"{r['act']:.2f}",
                         surprise=pct(r["surprise"]), d1=pct(r["d1"]),
                         d20=pct(r["d20"]) if r["d20"] is not None else "还没到",
                         now=r is hist[-1]) for r in reversed(hist)]
    slug = f"{ev['announce']}-{case['ticker'].lower()}-earnings"
    return dict(
        slug=slug, ticker=case["ticker"], name=name,
        subject=f"[学习] {name}:一份超预期的财报之后",
        title=f"{name}财报之后,股价怎么走了?",
        subtitle=f"一个真实事件,练习看懂公司出了消息之后股价怎么反应。数据截至 {case['data_through']}。",
        who_heading=company["intro_heading"], who_body=company["intro"],
        what_heading=f"{y} 年 {int(m)} 月 {int(d)} 日{when},{name}公布了{company['quarter']}的业绩",
        what_body="大家最先看的数字是每股盈利:公司这三个月赚的钱,平摊到每一股上是多少美元。"
                  "公布之前,华尔街的分析师已经各自估过一个数,取平均就是“预期”。",
        stats=[(f"{ev['est']:.2f} 美元", "分析师事先的预期"), (f"{ev['act']:.2f} 美元", f"{name}实际公布"),
               (f"高出 {ev['surprise']:.1f}%", "这就叫“超预期”")],
        guess_question=f"你觉得第二天{name}的股价会涨还是跌?",
        guess_body="赚得比大家估的多,按常理是好消息。先想好你的答案,再往下看。",
        reaction_heading=f"第二天{name}{_move(ev['d1'])},同一天大盘{_move(ev['b1'])}",
        reaction_caption="两条线都以财报公布前最后一个收盘价为起点,记作 0%。往上是涨,往下是跌。虚线是财报公布的时刻。",
        after_rows=after,
        money=f"换成钱来看:财报公布前持有 10,000 美元的{name}股票,第二天收盘时还剩大约 "
              f"{10000 * (1 + ev['d1'] / 100):,.0f} 美元。",
        why_market="大盘指美国最大的 500 家公司的整体表现。如果那天所有股票都在跌,就不能算一家公司自己的问题。" + why_market,
        history_heading=f"过去 {n} 次财报全部超预期,第二天 {up} 次涨,{n - up} 次跌",
        history_caption="每根柱子是一次财报公布后第二天的涨跌。柱子朝上是涨,朝下是跌。颜色最深的是这一次。",
        history_rows=history_rows,
        learn_heading="“超预期”不等于“股价会涨”",
        learn_items=[
            ("好消息不保证上涨。", f"{n} 次财报每一次都比预期好,第二天上涨的有 {up} 次,下跌的有 {n - up} 次。"),
            ("股价在公布之前,就已经按大家的期待定好了。",
             "公布之后是涨是跌,要看结果和期待差多少。投资者还会看财报里的其他内容,比如公司对下一个季度怎么估计。"),
            (f"{n} 次太少,不能当成规律。", "它只够说明一件事:“超预期就买”这个想法站不住。"),
        ],
        open_question=f"这一次{name}具体为什么{'跌' if ev['d1'] < 0 else '涨'}。"
                      "答案在当天的新闻和财报原文里,这份材料还没有接入那部分内容。",
        glossary=GLOSSARY,
        footer="数据来自 Yahoo Finance,价格为复权收盘价。这份材料只陈述已经发生的事实,不是投资建议。",
    )


APPLE = dict(name="苹果", quarter="4 到 6 月",
             intro_heading="苹果,卖 iPhone 和 Mac 的那家",
             intro="它在美国上市,股票代码是 AAPL。每三个月,它要向所有人公布一次这段时间赚了多少钱,这份公告叫财报。")
