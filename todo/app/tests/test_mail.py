import imaplib
import json
from datetime import date
from email.message import EmailMessage

import pytest

from todo_app import db, mail

TODAY = date(2026, 10, 28)  # a Wednesday


def make_mail(
    subject="Call the plumber",
    body="About the kitchen sink.",
    sender="Rikard <rikard@example.com>",
    to="rikard+todo@example.com",
    message_id="<1@example.com>",
    html=None,
) -> bytes:
    msg = EmailMessage()
    msg["From"] = sender
    msg["To"] = to
    msg["Subject"] = subject
    if message_id:
        msg["Message-ID"] = message_id
    if body is not None:
        msg.set_content(body)
    if html is not None:
        if body is None:
            msg.set_content(html, subtype="html")
        else:
            msg.add_alternative(html, subtype="html")
    return msg.as_bytes()


def parsed(**kw) -> mail.ParsedMail:
    return mail.parse_message(make_mail(**kw))


def config(**kw) -> mail.MailConfig:
    base = {"enabled": True, "host": "imap.example.com", "username": "rikard@example.com",
            "password": "secret", "folder": "Todo"}
    return mail.MailConfig(**{**base, **kw})


class FakeImap:
    """Just enough of imaplib.IMAP4 for check_mailbox()."""

    def __init__(self, messages, *, password="secret", folders=('"Todo"',)):
        self.messages = dict(messages)
        self.password = password
        self.folders = folders
        self.seen: set[bytes] = set()
        self.logged_out = False

    def login(self, user, password):
        if password != self.password:
            raise imaplib.IMAP4.error("[AUTHENTICATIONFAILED] Invalid credentials")
        return "OK", [b"Logged in"]

    def select(self, folder):
        if folder not in self.folders:
            return "NO", [b"[NONEXISTENT] Unknown Mailbox"]
        return "OK", [str(len(self.messages)).encode()]

    def uid(self, command, *args):
        if command == "SEARCH":
            unseen = [uid for uid in self.messages if uid not in self.seen]
            return "OK", [b" ".join(unseen)]
        if command == "FETCH":
            raw = self.messages[args[0]]
            return "OK", [(b"1 (UID " + args[0] + b" BODY[] {%d}" % len(raw), raw), b")"]
        if command == "STORE":
            assert args[1:] == ("+FLAGS", "(\\Seen)")
            self.seen.add(args[0])
            return "OK", [b""]
        raise AssertionError(command)

    def logout(self):
        self.logged_out = True


# ---------- parsing ----------

def test_parse_plain_message():
    m = parsed()
    assert m.message_id == "<1@example.com>"
    assert m.sender == "rikard@example.com"
    assert m.from_display == "Rikard <rikard@example.com>"
    assert m.recipients == ["rikard+todo@example.com"]
    assert m.subject == "Call the plumber"
    assert m.body == "About the kitchen sink."


def test_parse_decodes_non_ascii_subject_and_body():
    m = parsed(subject="Köp mjölk och ägg", body="Glöm inte grädden.")
    assert m.subject == "Köp mjölk och ägg"
    assert m.body == "Glöm inte grädden."


def test_parse_prefers_plain_over_html():
    m = parsed(body="plain version", html="<p>html version</p>")
    assert m.body == "plain version"


def test_parse_html_only_is_flattened_to_text():
    m = parsed(
        body=None,
        html="<html><head><style>p{color:red}</style></head>"
             "<body><p>First&nbsp;line</p><p>Second &amp; last<br>row</p></body></html>",
    )
    assert m.body == "First line\nSecond & last\nrow"


def test_parse_drops_signature():
    m = parsed(body="Fix the gate.\n\n-- \nRikard Pettersson\n070-123 45 67")
    assert m.body == "Fix the gate."
    # a plain "--" line is not a signature delimiter
    assert parsed(body="a\n--\nb").body == "a\n--\nb"


def test_parse_without_message_id_uses_content_hash():
    raw = make_mail(message_id=None)
    first, second = mail.parse_message(raw), mail.parse_message(raw)
    assert first.message_id.startswith("sha256:")
    assert first.message_id == second.message_id


# ---------- mail -> task fields ----------

def fields(subject="Call the plumber", tags=("hushall", "errands"), **kw):
    return mail.task_from_mail(
        parsed(subject=subject, **kw), allowed_tags=list(tags), today=TODAY
    )


def test_plain_subject_becomes_title_and_body_description():
    f = fields()
    assert f["title"] == "Call the plumber"
    assert f["description"] == "From: Rikard <rikard@example.com>\n\nAbout the kitchen sink."
    assert f == {**f, "priority": "normal", "due_date": None, "tags": [],
                 "workspace": "private", "planned_for": None}


def test_subject_syntax():
    f = fields("Call the plumber #hushall !high @work due:2026-11-02 @today")
    assert f["title"] == "Call the plumber"
    assert f["tags"] == ["hushall"]
    assert f["priority"] == "high"
    assert f["workspace"] == "work"
    assert f["due_date"] == "2026-11-02"
    assert f["planned_for"] == "2026-10-28"


def test_relative_due_dates():
    assert fields("Pay rent due:today")["due_date"] == "2026-10-28"
    assert fields("Pay rent due:tomorrow")["due_date"] == "2026-10-29"
    assert fields("Pay rent due:imorgon")["due_date"] == "2026-10-29"


def test_unrecognised_words_stay_in_the_title():
    f = fields("Fix #bug in due:soon release !urgent")
    assert f["title"] == "Fix #bug in due:soon release !urgent"
    assert f["tags"] == [] and f["due_date"] is None and f["priority"] == "normal"


def test_tags_match_case_insensitively_and_use_the_configured_spelling():
    f = fields("Buy milk #Errands #errands", tags=("errands",))
    assert f["tags"] == ["errands"]


def test_reply_and_forward_prefixes_are_stripped():
    assert fields("VB: SV: Re: Offert badrum")["title"] == "Offert badrum"
    assert fields("Fwd: FW: Invoice")["title"] == "Invoice"


def test_empty_subject_falls_back_to_first_body_line():
    assert fields("", body="\n\nRing Anna\nom helgen")["title"] == "Ring Anna"
    assert fields("!high", body="")["title"] == "Mail from rikard@example.com"


def test_plus_address_picks_workspace_and_subject_overrides_it():
    assert fields(to="rikard+work@example.com")["workspace"] == "work"
    assert fields(to="Me <rikard+private@example.com>")["workspace"] == "private"
    assert fields("Thing @private", to="rikard+work@example.com")["workspace"] == "private"
    # any other plus suffix is ignored
    assert fields(to="rikard+todo@example.com")["workspace"] == "private"


def test_default_workspace_is_configurable():
    f = mail.task_from_mail(parsed(), allowed_tags=[], default_workspace="work", today=TODAY)
    assert f["workspace"] == "work"


def test_long_body_and_title_are_truncated():
    f = fields("x" * 600, body="y" * 10_000)
    assert len(f["title"]) == 500
    assert f["description"].endswith("\n[...]")
    assert len(f["description"]) < mail.MAX_DESCRIPTION + 100


# ---------- senders, folders, config ----------

def test_sender_allowed():
    assert mail.sender_allowed("anyone@spam.com", ())
    allowed = ("me@example.com", "@work.se")
    assert mail.sender_allowed("me@example.com", allowed)
    assert mail.sender_allowed("boss@work.se", allowed)
    assert not mail.sender_allowed("boss@notwork.se", allowed)
    assert not mail.sender_allowed("other@example.com", allowed)


def test_imap_utf7_folder_names():
    assert mail.imap_utf7("Todo") == "Todo"
    assert mail.imap_utf7("Att göra") == "Att g&APY-ra"
    assert mail.imap_utf7("A&B") == "A&-B"
    assert mail._folder_arg('Saker "att" göra') == '"Saker \\"att\\" g&APY-ra"'


def test_config_from_options():
    c = mail.MailConfig.from_options({
        "mail_enabled": True, "imap_host": " imap.gmail.com ", "imap_port": 993,
        "imap_username": "me@gmail.com", "imap_password": "app-pass",
        "imap_folder": "Todo", "mail_allowed_senders": "Me@Gmail.com; @work.se,  ",
        "mail_default_workspace": "work", "mail_poll_minutes": -3,
    })
    assert c.active
    assert c.host == "imap.gmail.com"
    assert c.allowed_senders == ("me@gmail.com", "@work.se")
    assert c.default_workspace == "work"
    assert c.poll_minutes == 1
    assert "app-pass" not in repr(c)


def test_config_reports_missing_options():
    c = mail.MailConfig.from_options({"mail_enabled": True, "imap_host": "imap.x.com"})
    assert not c.active
    assert c.missing() == ["imap_username", "imap_password"]
    assert not mail.MailConfig.from_options({"mail_enabled": False, **{
        "imap_host": "h", "imap_username": "u", "imap_password": "p"}}).active


def test_load_config(tmp_path):
    assert mail.load_config(str(tmp_path / "missing.json")) == mail.MailConfig()
    path = tmp_path / "options.json"
    path.write_text(json.dumps({"log_level": "info", "mail_enabled": True, "imap_host": "h",
                                "imap_username": "u", "imap_password": "p"}))
    assert mail.load_config(str(path)).active
    path.write_text("{not json")
    assert mail.load_config(str(path)) == mail.MailConfig()


# ---------- polling ----------

def check(conn, fake, **kw):
    return mail.check_mailbox(conn, config(**kw), client_factory=lambda _: fake, today=TODAY)


def test_check_creates_tasks_and_marks_mail_read(conn):
    db.add_allowed_tag(conn, "hushall")
    fake = FakeImap({
        b"1": make_mail("Call the plumber #hushall", message_id="<1@x>"),
        b"2": make_mail("Book dentist @today", message_id="<2@x>"),
    })
    created = check(conn, fake)
    assert [t["title"] for t in created] == ["Call the plumber", "Book dentist"]
    assert created[0]["tags"] == ["hushall"]
    assert created[1]["planned_for"] == "2026-10-28"
    assert fake.seen == {b"1", b"2"}
    assert fake.logged_out
    log = db.list_mail_imports(conn)
    assert {(r["message_id"], r["outcome"]) for r in log} == {("<1@x>", "created"),
                                                              ("<2@x>", "created")}


def test_same_mail_never_becomes_two_tasks(conn):
    fake = FakeImap({b"1": make_mail(message_id="<1@x>")})
    assert len(check(conn, fake)) == 1
    fake.seen.clear()  # read flag lost (another client marked it unread, say)
    assert check(conn, fake) == []
    assert len(db.list_tasks(conn)) == 1
    assert fake.seen == {b"1"}


def test_rejected_sender_is_logged_and_marked_read(conn):
    fake = FakeImap({b"1": make_mail(sender="spam@spam.com")})
    assert check(conn, fake, allowed_senders=("rikard@example.com",)) == []
    assert db.list_tasks(conn) == []
    assert fake.seen == {b"1"}
    [entry] = db.list_mail_imports(conn)
    assert entry["outcome"] == "rejected" and entry["sender"] == "spam@spam.com"


def test_one_bad_message_does_not_block_the_rest(conn, monkeypatch):
    real_create = db.create_task

    def flaky_create(conn, **fields):
        if fields["title"] == "boom":
            raise RuntimeError("disk full")
        return real_create(conn, **fields)

    monkeypatch.setattr(db, "create_task", flaky_create)
    fake = FakeImap({
        b"1": make_mail("boom", message_id="<1@x>"),
        b"2": make_mail("fine", message_id="<2@x>"),
    })
    assert [t["title"] for t in check(conn, fake)] == ["fine"]
    assert fake.seen == {b"2"}  # the failed one stays unread and is retried next pass


def test_pass_is_capped(conn, monkeypatch):
    monkeypatch.setattr(mail, "MAX_PER_PASS", 2)
    fake = FakeImap({str(i).encode(): make_mail(f"t{i}", message_id=f"<{i}@x>")
                     for i in range(1, 6)})
    assert len(check(conn, fake)) == 2
    assert len(check(conn, fake)) == 2
    assert len(check(conn, fake)) == 1


def test_login_failure_raises_mail_error(conn):
    fake = FakeImap({}, password="other")
    with pytest.raises(mail.MailError, match="Login failed"):
        check(conn, fake)
    assert fake.logged_out


def test_missing_folder_raises_mail_error(conn):
    with pytest.raises(mail.MailError, match="Cannot open folder 'Inkorg/Todo'"):
        check(conn, FakeImap({}), folder="Inkorg/Todo")


def test_connection_failure_raises_mail_error(conn):
    def refuse(_):
        raise ConnectionRefusedError("Connection refused")

    with pytest.raises(mail.MailError, match="Cannot connect to imap.example.com:993"):
        mail.check_mailbox(conn, config(), client_factory=refuse)


def test_run_check_records_status(conn):
    status = mail.status_for(config())
    mail.run_check(conn, config(), status, client_factory=lambda _: FakeImap({}))
    assert status["last_check"] and status["last_error"] is None
    with pytest.raises(mail.MailError):
        mail.run_check(conn, config(), status,
                       client_factory=lambda _: FakeImap({}, password="x"))
    assert "Login failed" in status["last_error"]


# ---------- API ----------

def test_api_status_when_off(client):
    body = client.get("/api/v1/mail").json()
    assert body["enabled"] is False and body["active"] is False
    assert body["recent"] == []
    assert "password" not in json.dumps(body)


def test_api_check_refuses_when_off_or_incomplete(app, client):
    assert client.post("/api/v1/mail/check").status_code == 409
    app.state.mail_config = config(password="")
    response = client.post("/api/v1/mail/check")
    assert response.status_code == 409
    assert "imap_password" in response.json()["detail"]


def test_api_check_creates_tasks(app, client):
    app.state.mail_config = config()
    app.state.mail_client_factory = lambda _: FakeImap({b"7": make_mail("From the API")})
    response = client.post("/api/v1/mail/check")
    assert response.status_code == 200
    assert [t["title"] for t in response.json()] == ["From the API"]
    status = client.get("/api/v1/mail").json()
    assert status["active"] and status["last_check"] and status["last_error"] is None
    assert status["recent"][0]["subject"] == "From the API"
    assert "secret" not in json.dumps(status)


def test_api_check_reports_mailbox_errors(app, client):
    app.state.mail_config = config()
    app.state.mail_client_factory = lambda _: FakeImap({}, password="nope")
    response = client.post("/api/v1/mail/check")
    assert response.status_code == 502
    assert "Login failed" in response.json()["detail"]
    assert "Login failed" in client.get("/api/v1/mail").json()["last_error"]
