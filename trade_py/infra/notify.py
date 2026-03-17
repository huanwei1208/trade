"""Lightweight hook notification dispatcher.

Reads `hooks.notify_url` from SettingsDB (or env var TRADE_NOTIFY_URL).
Dispatches start/success/failure events to DingTalk, Telegram, Feishu, or
a generic JSON webhook based on URL pattern.

Usage::

    from trade_py.infra.notify import dispatch
    dispatch("success", "kline_update", "K线同步: 500 symbols, 123456 行", data_root)
"""
from __future__ import annotations

import json
import logging
import os
import traceback
import urllib.request
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)
_CST = timezone(timedelta(hours=8))

_HEADER_COLOR = {
    "start":   "blue",
    "success": "green",
    "failure": "red",
}
_ICON = {
    "start":   "🔄",
    "success": "✅",
    "failure": "❌",
}


def _now_str() -> str:
    return datetime.now(_CST).strftime("%Y-%m-%d %H:%M:%S")


# ── Format builders ────────────────────────────────────────────────────────────

def _feishu_payload(event: str, job_name: str, message: str) -> dict:
    color = _HEADER_COLOR.get(event, "blue")
    icon = _ICON.get(event, "")
    label = {"start": "开始", "success": "完成", "failure": "失败"}.get(event, event)
    content = f"**[{icon} {label}]** {job_name}\n{message}\n_{_now_str()}_"
    return {
        "msg_type": "interactive",
        "card": {
            "elements": [
                {
                    "tag": "div",
                    "text": {"tag": "lark_md", "content": content},
                }
            ],
            "header": {
                "title": {"tag": "plain_text", "content": "Trade 调度通知"},
                "template": color,
            },
        },
    }


def _dingtalk_payload(event: str, job_name: str, message: str) -> dict:
    icon = _ICON.get(event, "")
    label = {"start": "开始", "success": "完成", "failure": "失败"}.get(event, event)
    title = f"Trade 调度 [{icon} {label}] {job_name}"
    text = f"### {title}\n\n{message}\n\n> {_now_str()}"
    return {
        "msgtype": "markdown",
        "markdown": {"title": title, "text": text},
    }


def _telegram_payload(url: str, event: str, job_name: str, message: str) -> dict:
    # chat_id must be a query param in the URL; the body carries text + parse_mode
    import urllib.parse
    parsed = urllib.parse.urlparse(url)
    params = dict(urllib.parse.parse_qsl(parsed.query))
    icon = _ICON.get(event, "")
    label = {"start": "开始", "success": "完成", "failure": "失败"}.get(event, event)
    text = f"{icon} *[{label}]* `{job_name}`\n{message}\n_{_now_str()}_"
    return {
        "chat_id": params.get("chat_id", ""),
        "text": text,
        "parse_mode": "Markdown",
    }


def _generic_payload(event: str, job_name: str, message: str) -> dict:
    return {
        "event": event,
        "job": job_name,
        "message": message,
        "ts": _now_str(),
    }


# ── HTTP sender ────────────────────────────────────────────────────────────────

def _post_json(url: str, payload: dict, timeout: int = 10) -> None:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        status = resp.getcode()
        if status not in (200, 201, 204):
            logger.warning("notify: unexpected HTTP %d from %s", status, url)


# ── Public API ─────────────────────────────────────────────────────────────────

def dispatch(event: str, job_name: str, message: str, data_root: str) -> None:
    """Send a notification if the URL is configured and the event is enabled.

    Parameters
    ----------
    event:     one of "start", "success", "failure"
    job_name:  human-readable job identifier
    message:   body text (may include newlines / stack trace excerpt)
    data_root: path to data directory (for reading SettingsDB)
    """
    # Resolve URL: env var takes priority over settings
    url = os.environ.get("TRADE_NOTIFY_URL", "").strip()
    if not url:
        try:
            from trade_py.db.settings_db import SettingsDB
            url = str(SettingsDB(data_root).get("hooks.notify_url", "") or "")
        except Exception:
            url = ""

    if not url:
        return  # notifications not configured

    # Check whether this event type is enabled
    notify_on_str = os.environ.get("TRADE_NOTIFY_ON", "").strip()
    if not notify_on_str:
        try:
            from trade_py.db.settings_db import SettingsDB
            notify_on_str = str(SettingsDB(data_root).get("hooks.notify_on", "failure,success") or "")
        except Exception:
            notify_on_str = "failure,success"

    enabled_events = {e.strip() for e in notify_on_str.split(",") if e.strip()}
    if event not in enabled_events:
        return

    # Build payload based on URL pattern
    try:
        if "open.feishu.cn" in url or "feishu.cn" in url:
            payload = _feishu_payload(event, job_name, message)
        elif "oapi.dingtalk.com" in url:
            payload = _dingtalk_payload(event, job_name, message)
        elif "api.telegram.org" in url:
            payload = _telegram_payload(url, event, job_name, message)
        else:
            payload = _generic_payload(event, job_name, message)

        _post_json(url, payload)
        logger.debug("notify: sent %s event for job=%s", event, job_name)
    except Exception as exc:
        # Never let notification failure crash the job
        logger.warning("notify: failed to send %s event for %s: %s", event, job_name, exc)
