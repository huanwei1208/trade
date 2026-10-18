"""Assemble a lesson into a web page directory and an email message."""
from __future__ import annotations

import json
from email.message import EmailMessage
from email.utils import make_msgid
from pathlib import Path

import altair as alt
from jinja2 import Environment, FileSystemLoader, StrictUndefined

from . import charts

_ENV = Environment(loader=FileSystemLoader(Path(__file__).parent / "templates"),
                   autoescape=True, undefined=StrictUndefined, keep_trailing_newline=True)
VERSIONS = dict(vega=alt.VEGA_VERSION, vegalite=alt.VEGALITE_VERSION, embed=alt.VEGAEMBED_VERSION)
CHART_IDS = ("reaction", "history")
EMAIL_CHART_WIDTH = 400


def build_charts(case: dict, name: str, *, interactive: bool, width, font: str) -> dict:
    return {"reaction": charts.reaction_chart(case, name, interactive=interactive, width=width, font=font),
            "history": charts.history_chart(case, interactive=interactive, width=width, font=font)}


def static_pngs(case: dict, name: str) -> dict[str, bytes]:
    """The email's charts: the same definitions as the web, minus hover layers."""
    # Drawn at phone width: the email is mostly read on a phone, and a wider
    # drawing shrunk to fit makes the labels unreadable. scale=3 keeps it sharp.
    built = build_charts(case, name, interactive=False, width=EMAIL_CHART_WIDTH, font=charts.PNG_FONT)
    return {k: charts.to_png(v, scale=3) for k, v in built.items()}


def render_web(lesson: dict, case: dict) -> str:
    specs = {k: v.to_dict() for k, v in
             build_charts(case, lesson["name"], interactive=True, width="container", font=charts.WEB_FONT).items()}
    return _ENV.get_template("lesson.html.j2").render(mode="web", L=lesson, specs=specs, versions=VERSIONS)


def render_email_html(lesson: dict, cids: dict[str, str], page_url: str) -> str:
    return _ENV.get_template("lesson.html.j2").render(mode="email", L=lesson, cids=cids, page_url=page_url)


def write_site(site_dir: Path, lesson: dict, case: dict, pngs: dict[str, bytes]) -> Path:
    """Write the lesson page, its PNG fallbacks, and refresh the course index."""
    out = site_dir / "lessons" / lesson["slug"]
    out.mkdir(parents=True, exist_ok=True)
    (out / "index.html").write_text(render_web(lesson, case), encoding="utf-8")
    (out / "case.json").write_text(json.dumps(case, ensure_ascii=False, indent=1), encoding="utf-8")
    for k, png in pngs.items():
        (out / f"{k}.png").write_bytes(png)

    manifest_path = site_dir / "lessons.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else []
    manifest = [m for m in manifest if m["slug"] != lesson["slug"]]
    manifest.append(dict(slug=lesson["slug"], title=lesson["title"], date=case["event"]["announce"]))
    manifest.sort(key=lambda m: m["date"], reverse=True)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    (site_dir / "index.html").write_text(_ENV.get_template("index.html.j2").render(lessons=manifest),
                                         encoding="utf-8")
    return out


def build_email(lesson: dict, pngs: dict[str, bytes], *, page_url: str,
                sender: str, to: str) -> EmailMessage:
    """HTML body with the charts inline (multipart/related), plus a text fallback."""
    cids = {k: make_msgid(domain="learn.local") for k in pngs}
    msg = EmailMessage()
    msg["Subject"], msg["From"], msg["To"] = lesson["subject"], sender, to
    msg.set_content(f"{lesson['title']}\n\n这封邮件是网页格式。如果显示不正常,请打开:\n{page_url}\n")
    msg.add_alternative(render_email_html(lesson, {k: c[1:-1] for k, c in cids.items()}, page_url),
                        subtype="html")
    html_part = msg.get_payload()[1]
    for k, png in pngs.items():
        html_part.add_related(png, maintype="image", subtype="png", cid=cids[k], filename=f"{k}.png")
    return msg
