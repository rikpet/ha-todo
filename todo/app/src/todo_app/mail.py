"""Turn mail in an IMAP folder into tasks.

The add-on polls one folder for unread messages. Each one becomes a task: the
subject is the title (with a little inline syntax for tags, priority, workspace
and due date) and the body becomes the description. Processed messages are
flagged as read, and their Message-ID is logged in the database so a message
can never turn into two tasks, even if the read flag is lost.
"""

from __future__ import annotations

import base64
import email
import email.policy
import hashlib
import html
import imaplib
import json
import logging
import os
import re
import ssl
import threading
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from email.message import EmailMessage
from email.utils import getaddresses, parseaddr
from pathlib import Path
from typing import Any, Callable

from . import db

log = logging.getLogger("todo_app.mail")

MAX_PER_PASS = 20  # a misconfigured folder full of unread mail must not flood the list
MAX_DESCRIPTION = 4000
TIMEOUT_SECONDS = 30

# one pass at a time: the scheduler and "check now" must not import the same mail twice
_poll_lock = threading.Lock()


class MailError(Exception):
    """Mailbox unreachable or misconfigured; the message is safe to show the user."""


# ---------- configuration ----------


@dataclass(frozen=True)
class MailConfig:
    enabled: bool = False
    host: str = ""
    port: int = 993
    username: str = ""
    password: str = field(default="", repr=False)
    folder: str = "Todo"
    allowed_senders: tuple[str, ...] = ()
    default_workspace: str = "private"
    poll_minutes: int = 5

    @classmethod
    def from_options(cls, options: dict[str, Any]) -> MailConfig:
        senders = options.get("mail_allowed_senders") or ""
        if isinstance(senders, str):
            senders = senders.replace(";", ",").split(",")
        workspace = options.get("mail_default_workspace") or "private"
        if workspace not in db.WORKSPACES:
            workspace = "private"
        return cls(
            enabled=bool(options.get("mail_enabled")),
            host=(options.get("imap_host") or "").strip(),
            port=int(options.get("imap_port") or 993),
            username=(options.get("imap_username") or "").strip(),
            password=options.get("imap_password") or "",
            folder=(options.get("imap_folder") or "").strip() or "INBOX",
            allowed_senders=tuple(s.strip().lower() for s in senders if s.strip()),
            default_workspace=workspace,
            poll_minutes=max(1, int(options.get("mail_poll_minutes") or 5)),
        )

    def missing(self) -> list[str]:
        required = {"imap_host": self.host, "imap_username": self.username,
                    "imap_password": self.password}
        return [name for name, value in required.items() if not value]

    @property
    def active(self) -> bool:
        return self.enabled and not self.missing()


def load_config(path: str | None = None) -> MailConfig:
    """Read the add-on options; anything unreadable means mail import is off."""
    path = path or os.environ.get("TODO_OPTIONS_PATH", "/data/options.json")
    try:
        options = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return MailConfig()
    try:
        return MailConfig.from_options(options)
    except (TypeError, ValueError):
        log.warning("Mail options in %s are invalid; mail import is off", path)
        return MailConfig()


def status_for(config: MailConfig) -> dict[str, Any]:
    return {
        "enabled": config.enabled,
        "active": config.active,
        "missing": config.missing() if config.enabled else [],
        "host": config.host,
        "username": config.username,
        "folder": config.folder,
        "poll_minutes": config.poll_minutes,
        "allowed_senders": list(config.allowed_senders),
        "default_workspace": config.default_workspace,
        "last_check": None,
        "last_error": None,
    }


# ---------- parsing ----------


@dataclass
class ParsedMail:
    message_id: str
    sender: str  # bare address, lower-case
    from_display: str  # the From header as written, for the description
    recipients: list[str]
    subject: str
    body: str


_REPLY_PREFIX = re.compile(r"^\s*((re|fw|fwd|sv|vb|aw|wg|tr)\s*:\s*)+", re.IGNORECASE)


def _header(msg: EmailMessage, name: str) -> str:
    value = msg.get(name)
    return " ".join(str(value).split()) if value is not None else ""


def _html_to_text(markup: str) -> str:
    markup = re.sub(r"(?is)<(script|style|head)\b.*?</\1\s*>", "", markup)
    markup = re.sub(r"(?i)<br\s*/?>|</(p|div|li|tr|h[1-6])\s*>", "\n", markup)
    markup = re.sub(r"(?s)<[^>]+>", "", markup)
    return html.unescape(markup).replace("\xa0", " ")


def _tidy(text: str) -> str:
    lines = [line.rstrip() for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n")]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def _body_text(msg: EmailMessage) -> str:
    part = msg.get_body(preferencelist=("plain", "html"))
    if part is None:
        return ""
    try:
        content = part.get_content()
    except (LookupError, UnicodeDecodeError, KeyError):
        content = (part.get_payload(decode=True) or b"").decode("utf-8", "replace")
    if not isinstance(content, str):
        return ""
    if part.get_content_type() == "text/html":
        content = _html_to_text(content)
    # everything under the standard "-- " delimiter is a signature
    content = re.split(r"(?m)^-- $", content.replace("\r\n", "\n"), maxsplit=1)[0]
    return _tidy(content)


def parse_message(raw: bytes) -> ParsedMail:
    msg = email.message_from_bytes(raw, policy=email.policy.default)
    message_id = _header(msg, "Message-ID")
    if not message_id:
        message_id = "sha256:" + hashlib.sha256(raw).hexdigest()
    from_display = _header(msg, "From")
    recipient_headers = [
        str(value)
        for name in ("To", "Cc", "Delivered-To", "X-Original-To")
        for value in (msg.get_all(name) or [])
    ]
    return ParsedMail(
        message_id=message_id,
        sender=parseaddr(from_display)[1].lower(),
        from_display=from_display,
        recipients=[addr.lower() for _, addr in getaddresses(recipient_headers) if addr],
        subject=_header(msg, "Subject"),
        body=_body_text(msg),
    )


def sender_allowed(sender: str, allowed: tuple[str, ...] | list[str]) -> bool:
    """An empty list allows everyone; entries are addresses or '@domain'."""
    if not allowed:
        return True
    domain = sender.rpartition("@")[2]
    for entry in allowed:
        entry = entry.lower()
        if entry.startswith("@") and domain == entry[1:]:
            return True
        if sender == entry:
            return True
    return False


def _workspace_from_recipients(recipients: list[str]) -> str | None:
    """Plus addressing picks the workspace: you+work@example.com -> work."""
    for address in recipients:
        local = address.partition("@")[0]
        if "+" in local:
            suffix = local.split("+", 1)[1]
            if suffix in db.WORKSPACES:
                return suffix
    return None


def _parse_due(value: str, today: date) -> str | None:
    word = value.lower()
    if word in ("today", "idag"):
        return today.isoformat()
    if word in ("tomorrow", "imorgon"):
        return (today + timedelta(days=1)).isoformat()
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError:
        return None


def task_from_mail(
    mail: ParsedMail,
    *,
    allowed_tags: list[str],
    default_workspace: str = "private",
    today: date | None = None,
) -> dict[str, Any]:
    """Map a mail to create_task() fields.

    Subject syntax, each word optional and anywhere in the subject:
    #tag (configured tags only), !high / !low, @work / @private,
    @today (My Day), @claude (hand to Claude), due:2026-11-02 / due:today /
    due:tomorrow. Words that do not match stay in the title untouched.
    The extra "for_claude" key is not a create_task() field; pop it first.
    """
    today = today or date.today()
    known_tags = {tag.lower(): tag for tag in allowed_tags}
    tags: list[str] = []
    priority = "normal"
    workspace = _workspace_from_recipients(mail.recipients) or default_workspace
    due_date = planned_for = None
    for_claude = False

    words = []
    for word in _REPLY_PREFIX.sub("", mail.subject).split():
        lower = word.lower()
        if lower.startswith("#") and lower[1:] in known_tags:
            if known_tags[lower[1:]] not in tags:
                tags.append(known_tags[lower[1:]])
        elif lower in ("!high", "!low", "!normal"):
            priority = lower[1:]
        elif lower in tuple(f"@{name}" for name in db.WORKSPACES):
            workspace = lower[1:]
        elif lower in ("@today", "@idag"):
            planned_for = today.isoformat()
        elif lower == "@claude":
            for_claude = True
        elif lower.startswith("due:") and _parse_due(word[4:], today):
            due_date = _parse_due(word[4:], today)
        else:
            words.append(word)

    title = " ".join(words)
    if not title:
        first_line = next((line.strip() for line in mail.body.splitlines() if line.strip()), "")
        title = first_line or f"Mail from {mail.sender or 'unknown sender'}"

    body = mail.body
    if len(body) > MAX_DESCRIPTION:
        body = body[:MAX_DESCRIPTION].rstrip() + "\n[...]"
    description = f"From: {mail.from_display}" + (f"\n\n{body}" if body else "")

    return {
        "title": title[:500],
        "description": description,
        "priority": priority,
        "due_date": due_date,
        "tags": tags,
        "workspace": workspace,
        "planned_for": planned_for,
        "for_claude": for_claude,
    }


def import_message(
    conn, raw: bytes, config: MailConfig, *, today: date | None = None
) -> dict[str, Any] | None:
    """Create a task from one raw message. None if it was a duplicate or rejected."""
    mail = parse_message(raw)
    if db.mail_seen(conn, mail.message_id):
        return None
    if not sender_allowed(mail.sender, config.allowed_senders):
        log.warning("Mail from %s ignored (not an allowed sender): %s", mail.sender, mail.subject)
        db.record_mail(conn, message_id=mail.message_id, outcome="rejected",
                       sender=mail.sender, subject=mail.subject)
        return None
    fields = task_from_mail(
        mail,
        allowed_tags=db.allowed_tags(conn),
        default_workspace=config.default_workspace,
        today=today,
    )
    for_claude = fields.pop("for_claude")
    task = db.create_task(conn, **fields)
    db.record_mail(conn, message_id=mail.message_id, outcome="created", task_id=task["id"],
                   sender=mail.sender, subject=mail.subject)
    if for_claude:
        # the mail body is already the description, which is what Claude reads first
        task = db.give_to_claude(conn, task["id"])
    log.info("Task created from mail%s: #%s %s", " for Claude" if for_claude else "",
             task["id"], task["title"])
    return task


# ---------- IMAP ----------


def imap_utf7(name: str) -> str:
    """Encode a folder name in IMAP's modified UTF-7 ('Att göra' -> 'Att g&APY-ra')."""
    out: list[str] = []
    pending: list[str] = []

    def flush() -> None:
        if pending:
            encoded = base64.b64encode("".join(pending).encode("utf-16-be")).decode("ascii")
            out.append("&" + encoded.rstrip("=").replace("/", ",") + "-")
            pending.clear()

    for char in name:
        if 0x20 <= ord(char) <= 0x7E:
            flush()
            out.append("&-" if char == "&" else char)
        else:
            pending.append(char)
    flush()
    return "".join(out)


def _folder_arg(folder: str) -> str:
    encoded = imap_utf7(folder).replace("\\", "\\\\").replace('"', '\\"')
    return f'"{encoded}"'


def open_client(config: MailConfig) -> imaplib.IMAP4:
    context = ssl.create_default_context()
    if config.port == 143:
        client = imaplib.IMAP4(config.host, config.port, timeout=TIMEOUT_SECONDS)
        client.starttls(ssl_context=context)
        return client
    return imaplib.IMAP4_SSL(config.host, config.port, ssl_context=context,
                             timeout=TIMEOUT_SECONDS)


def _response_text(data: Any) -> str:
    parts = data if isinstance(data, list) else [data]
    return " ".join(p.decode("utf-8", "replace") if isinstance(p, bytes) else str(p)
                    for p in parts if p)


def _fetch_raw(client: imaplib.IMAP4, uid: bytes) -> bytes | None:
    # BODY.PEEK leaves the read flag alone until the task actually exists
    typ, data = client.uid("FETCH", uid, "(BODY.PEEK[])")
    if typ != "OK":
        return None
    for part in data or []:
        if isinstance(part, tuple) and len(part) == 2:
            return part[1]
    return None


def check_mailbox(
    conn,
    config: MailConfig,
    *,
    client_factory: Callable[[MailConfig], Any] | None = None,
    today: date | None = None,
) -> list[dict[str, Any]]:
    """One pass over the folder's unread mail. Raises MailError on mailbox problems."""
    created: list[dict[str, Any]] = []
    with _poll_lock:
        try:
            client = (client_factory or open_client)(config)
        except (OSError, imaplib.IMAP4.error) as exc:
            raise MailError(f"Cannot connect to {config.host}:{config.port}: {exc}") from exc
        try:
            try:
                client.login(config.username, config.password)
            except imaplib.IMAP4.error as exc:
                raise MailError(f"Login failed for {config.username}: {exc}") from exc
            typ, data = client.select(_folder_arg(config.folder))
            if typ != "OK":
                raise MailError(f"Cannot open folder '{config.folder}': {_response_text(data)}")
            typ, data = client.uid("SEARCH", None, "UNSEEN")
            if typ != "OK":
                raise MailError(f"Searching '{config.folder}' failed: {_response_text(data)}")
            uids = data[0].split() if data and data[0] else []
            for uid in uids[:MAX_PER_PASS]:
                raw = _fetch_raw(client, uid)
                if raw is None:
                    continue
                try:
                    task = import_message(conn, raw, config, today=today)
                except Exception:  # one odd message must not block the rest
                    log.exception("Could not turn mail %s into a task", uid)
                    continue
                client.uid("STORE", uid, "+FLAGS", "(\\Seen)")
                if task:
                    created.append(task)
        except (OSError, imaplib.IMAP4.error) as exc:
            raise MailError(f"Mailbox error: {exc}") from exc
        finally:
            try:
                client.logout()
            except Exception:
                pass
    return created


def run_check(
    conn,
    config: MailConfig,
    status: dict[str, Any],
    *,
    client_factory: Callable[[MailConfig], Any] | None = None,
) -> list[dict[str, Any]]:
    """check_mailbox(), recording the outcome in `status` for the API to report."""
    status["last_check"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    try:
        created = check_mailbox(conn, config, client_factory=client_factory)
    except MailError as exc:
        status["last_error"] = str(exc)
        raise
    status["last_error"] = None
    return created
