from __future__ import annotations

import hashlib
import json
import smtplib
import ssl
from datetime import datetime, timezone
from email.header import Header
from email.mime.text import MIMEText
from pathlib import Path
from typing import Callable


class DuplicateSendError(RuntimeError):
    pass


Transport = Callable[[str, str, str, str, str], None]


def send_report(
    *,
    sender: str,
    recipient: str,
    subject: str,
    html_body: str,
    report_date: str,
    auth_code: str,
    registry_path: Path,
    force: bool = False,
    transport: Transport | None = None,
) -> str:
    if not sender or not recipient:
        raise ValueError("显式发送邮件时必须提供发件人和收件人")
    if not auth_code:
        raise ValueError("显式发送邮件时必须提供 SMTP 授权码")
    digest = hashlib.sha256(html_body.encode("utf-8")).hexdigest()
    key_source = f"{recipient}\n{report_date}\n{digest}"
    send_key = hashlib.sha256(key_source.encode("utf-8")).hexdigest()
    registry_path = Path(registry_path)
    registry = _load_registry(registry_path)
    if send_key in registry["sends"] and not force:
        raise DuplicateSendError("相同收件人、截止日期和报告内容已发送；如确需重发请显式使用 --force-resend")

    (transport or _smtp_transport)(sender, recipient, subject, html_body, auth_code)
    registry["sends"][send_key] = {
        "recipient": recipient,
        "report_date": report_date,
        "content_sha256": digest,
        "sent_at_utc": datetime.now(timezone.utc).isoformat(),
        "forced": bool(force),
    }
    _save_registry(registry_path, registry)
    return send_key


def _smtp_transport(sender: str, recipient: str, subject: str, html_body: str, auth_code: str) -> None:
    message = MIMEText(html_body, "html", "utf-8")
    message["From"] = sender
    message["To"] = recipient
    message["Subject"] = Header(subject, "utf-8")
    with smtplib.SMTP_SSL("smtp.qq.com", 465, context=ssl.create_default_context(), timeout=35) as smtp:
        smtp.login(sender, auth_code)
        smtp.sendmail(sender, [recipient], message.as_string())


def _load_registry(path: Path) -> dict:
    if not path.exists():
        return {"version": 1, "sends": {}}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value.get("sends"), dict):
            raise ValueError("invalid registry")
        return value
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"邮件发送登记文件损坏，已停止发送：{path}") from exc


def _save_registry(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)

