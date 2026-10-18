"""Send a built message over SMTP. Settings come from the environment (.env)."""
from __future__ import annotations

import os
import smtplib
from dataclasses import dataclass
from email.message import EmailMessage

REQUIRED = ("LEARN_MAIL_FROM", "LEARN_MAIL_TO", "LEARN_SMTP_PASSWORD")


@dataclass(frozen=True)
class MailConfig:
    sender: str
    to: str
    password: str
    user: str
    host: str = "smtp.gmail.com"
    port: int = 587

    @classmethod
    def from_env(cls, env: dict | None = None) -> MailConfig:
        env = os.environ if env is None else env
        missing = [k for k in REQUIRED if not env.get(k)]
        if missing:
            raise RuntimeError("发信配置缺失,请在 .env 里加上:" + ", ".join(missing))
        return cls(sender=env["LEARN_MAIL_FROM"], to=env["LEARN_MAIL_TO"],
                   password=env["LEARN_SMTP_PASSWORD"],
                   user=env.get("LEARN_SMTP_USER") or env["LEARN_MAIL_FROM"],
                   host=env.get("LEARN_SMTP_HOST") or "smtp.gmail.com",
                   port=int(env.get("LEARN_SMTP_PORT") or 587))


def send(msg: EmailMessage, cfg: MailConfig, *, smtp_cls=smtplib.SMTP) -> None:
    with smtp_cls(cfg.host, cfg.port, timeout=30) as s:
        s.starttls()
        s.login(cfg.user, cfg.password)
        s.send_message(msg)
