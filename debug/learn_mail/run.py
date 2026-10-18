"""Build one lesson as a web page + email, and optionally send it.

    uv run --extra learn python debug/learn_mail/run.py --site-dir data/learn/site
    uv run --extra learn python debug/learn_mail/run.py --site-dir data/learn/site --send

Without --send the email is only written as an .eml file next to the site, so
it can be inspected (or opened in a mail client) before anything goes out.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from learn_mail import lessons, render, send  # noqa: E402

DEFAULT_SITE_URL = "http://learn.server.sucicada.me"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--site-dir", required=True, type=Path, help="nginx 指向的静态网站目录")
    ap.add_argument("--case-json", type=Path, help="用已保存的数据,不重新联网取")
    ap.add_argument("--send", action="store_true", help="真的发出邮件(需要 .env 里的发信配置)")
    args = ap.parse_args(argv)

    if args.case_json:
        case = json.loads(args.case_json.read_text(encoding="utf-8"))
    else:
        from learn_mail.data import fetch_earnings_case
        case = fetch_earnings_case("AAPL")
    lesson = lessons.earnings_lesson(case, lessons.APPLE)

    pngs = render.static_pngs(case, lesson["name"])
    out = render.write_site(args.site_dir, lesson, case, pngs)
    print(f"网页:{out / 'index.html'}")

    from dotenv import load_dotenv
    load_dotenv()
    site_url = (os.environ.get("LEARN_SITE_URL") or DEFAULT_SITE_URL).rstrip("/")
    page_url = f"{site_url}/lessons/{lesson['slug']}/"
    sender = os.environ.get("LEARN_MAIL_FROM") or "learn@localhost"
    to = os.environ.get("LEARN_MAIL_TO") or "you@localhost"
    msg = render.build_email(lesson, pngs, page_url=page_url, sender=sender, to=to)
    eml = args.site_dir.parent / "outbox" / f"{lesson['slug']}.eml"
    eml.parent.mkdir(parents=True, exist_ok=True)
    eml.write_bytes(bytes(msg))
    print(f"邮件:{eml}")
    print(f"链接:{page_url}")

    if args.send:
        send.send(msg, send.MailConfig.from_env())
        print("已发送")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
