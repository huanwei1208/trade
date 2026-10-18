"""Learning-mail prototype (debug/learn_mail): web and email stay one lesson."""
from __future__ import annotations

import email
import json
import re
import sys
from html.parser import HTMLParser
from pathlib import Path

import pytest

pytest.importorskip("altair")
pytest.importorskip("vl_convert")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "debug"))

from learn_mail import charts, lessons, render, send  # noqa: E402

FAKE_PNG = b"\x89PNG\r\n\x1a\nfake"


def _case(d1s=(-2.0, 1.5, -7.3539), surprises=(4.4, 2.5, 6.7)) -> dict:
    hist = [dict(announce=f"2026-0{i + 1}-30", after_close=True, base_i=0, est=1.0, act=1.1,
                 surprise=s, d1=d, d5=d, d20=d, b1=0.72, b5=3.6, b20=4.0)
            for i, (d, s) in enumerate(zip(d1s, surprises, strict=True))]
    series = [dict(date=f"2026-08-{r + 4:02d}", rel=r, close=300 + r, stock=float(-r) if r else 0.0,
                   bench=r / 10) for r in range(-3, 22)]
    return dict(ticker="AAPL", bench="SPY", event=hist[-1], series=series, history=hist,
                base_close=300.0, data_through="2026-09-30")


class _Text(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts, self._skip = [], 0

    def handle_starttag(self, tag, attrs):
        self._skip += tag in ("script", "style", "title")

    def handle_endtag(self, tag):
        self._skip -= tag in ("script", "style", "title")

    def handle_data(self, data):
        if not self._skip and data.strip():
            self.parts.append(data.strip())


def _text(html: str) -> list[str]:
    p = _Text()
    p.feed(html)
    return p.parts


def _lesson(case=None):
    case = case or _case()
    return case, lessons.earnings_lesson(case, lessons.APPLE)


def test_web_and_email_carry_the_same_words() -> None:
    """The email may add a link to the page; the web may add a back link. Nothing else differs."""
    case, lesson = _lesson()
    web = _text(render.render_web(lesson, case))
    mail = _text(render.render_email_html(lesson, {"reaction": "a", "history": "b"}, "http://x/l/"))
    assert [t for t in web if t != "全部课程"] == [t for t in mail if "Tailscale" not in t
                                                    and "在网页上看" not in t and t != "http://x/l/"]


def test_email_charts_are_inline_and_every_reference_resolves() -> None:
    case, lesson = _lesson()
    msg = render.build_email(lesson, {"reaction": FAKE_PNG, "history": FAKE_PNG},
                             page_url="http://learn.example/lessons/x/", sender="a@x", to="b@x")
    parsed = email.message_from_bytes(bytes(msg))
    html = next(p for p in parsed.walk() if p.get_content_type() == "text/html").get_payload(decode=True).decode()
    refs = set(re.findall(r'src="cid:([^"]+)"', html))
    parts = {p["Content-ID"][1:-1] for p in parsed.walk() if p.get("Content-ID")}
    assert refs == parts and len(refs) == 2
    assert any(p.get_content_type() == "multipart/related" for p in parsed.walk())
    assert "http://learn.example/lessons/x/" in html
    assert parsed["Subject"] and "跌" not in str(email.header.make_header(email.header.decode_header(parsed["Subject"])))


def test_static_chart_is_the_interactive_one_minus_hover() -> None:
    case, _ = _lesson()
    web = charts.reaction_chart(case, "苹果", interactive=True, width="container").to_dict()
    png = charts.reaction_chart(case, "苹果", interactive=False, width=400).to_dict()
    assert web.get("params") or any("params" in layer for layer in web["layer"])
    assert len(web["layer"]) == len(png["layer"]) + 2      # hover rule + hover dots
    assert not any("params" in layer for layer in png["layer"])


def test_static_png_renders_with_chinese_font() -> None:
    case, _ = _lesson()
    pngs = render.static_pngs(case, "苹果")
    assert set(pngs) == {"reaction", "history"}
    assert all(b.startswith(b"\x89PNG") and len(b) > 5_000 for b in pngs.values())


@pytest.mark.parametrize("case,match", [
    (_case(surprises=(4.4, -1.0, 6.7)), "miss"),
    (_case(d1s=(1.0, 2.0, 3.0)), "every beat rose"),
])
def test_copy_refuses_cases_it_would_describe_falsely(case, match) -> None:
    with pytest.raises(ValueError, match=match):
        lessons.earnings_lesson(case, lessons.APPLE)


def test_reaction_headline_follows_the_data() -> None:
    _, lesson = _lesson()
    # -7.3539 must read 7.4: rounding happens once, at display time.
    assert lesson["reaction_heading"] == "第二天苹果跌了 7.4%,同一天大盘涨了 0.7%"
    assert "跌" not in lesson["title"]          # the guess comes before the answer


def test_site_index_lists_each_lesson_once(tmp_path) -> None:
    case, lesson = _lesson()
    pngs = {"reaction": FAKE_PNG, "history": FAKE_PNG}
    render.write_site(tmp_path, lesson, case, pngs)
    render.write_site(tmp_path, lesson, case, pngs)          # rebuilding must not duplicate
    manifest = json.loads((tmp_path / "lessons.json").read_text(encoding="utf-8"))
    assert [m["slug"] for m in manifest] == [lesson["slug"]]
    assert f'lessons/{lesson["slug"]}/' in (tmp_path / "index.html").read_text(encoding="utf-8")
    assert (tmp_path / "lessons" / lesson["slug"] / "reaction.png").read_bytes() == FAKE_PNG


def test_mail_config_names_what_is_missing() -> None:
    with pytest.raises(RuntimeError, match="LEARN_SMTP_PASSWORD"):
        send.MailConfig.from_env({"LEARN_MAIL_FROM": "a@x", "LEARN_MAIL_TO": "b@x"})


def test_send_uses_tls_and_login() -> None:
    calls = []

    class FakeSMTP:
        def __init__(self, host, port, timeout):
            calls.append(("connect", host, port))

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def starttls(self):
            calls.append(("starttls",))

        def login(self, user, pw):
            calls.append(("login", user))

        def send_message(self, msg):
            calls.append(("send", msg["To"]))

    cfg = send.MailConfig.from_env({"LEARN_MAIL_FROM": "a@x", "LEARN_MAIL_TO": "b@x", "LEARN_SMTP_PASSWORD": "p"})
    case, lesson = _lesson()
    msg = render.build_email(lesson, {"reaction": FAKE_PNG, "history": FAKE_PNG}, page_url="http://x/", sender=cfg.sender, to=cfg.to)
    send.send(msg, cfg, smtp_cls=FakeSMTP)
    assert calls == [("connect", "smtp.gmail.com", 587), ("starttls",), ("login", "a@x"), ("send", "b@x")]
