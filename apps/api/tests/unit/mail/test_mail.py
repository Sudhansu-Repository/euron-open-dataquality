"""The mail backends: log keeps an outbox, smtp and ses hand the message over, failures
become MailError."""

from __future__ import annotations

from typing import Any

import pytest

from dataquality.core import mail
from dataquality.core.config import Settings

pytestmark = pytest.mark.asyncio


async def test_the_log_backend_keeps_the_message_in_the_outbox() -> None:
    await mail.send(Settings(mail_backend="log"), "c@example.test", "Hi", "body with a link")
    assert mail.OUTBOX[-1].to == "c@example.test" and mail.OUTBOX[-1].text == "body with a link"


async def test_the_smtp_backend_sends_a_multipart_message(monkeypatch: pytest.MonkeyPatch) -> None:
    sent: list[Any] = []

    class FakeSMTP:
        def __init__(self, host: str, port: int, timeout: float) -> None:
            sent.append((host, port))

        def __enter__(self) -> FakeSMTP:
            return self

        def __exit__(self, *exc: object) -> None:
            pass

        def send_message(self, msg: Any) -> None:
            sent.append(msg)

    monkeypatch.setattr(mail.smtplib, "SMTP", FakeSMTP)
    settings = Settings(mail_backend="smtp", smtp_host="mailpit", smtp_port=1025)
    await mail.send(settings, "c@example.test", "Hi", "text", "<p>html</p>")
    assert sent[0] == ("mailpit", 1025)
    msg = sent[1]
    assert msg["To"] == "c@example.test" and msg["Subject"] == "Hi" and msg.is_multipart()


async def test_a_refused_message_raises_mail_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*_a: object, **_k: object) -> None:
        raise ConnectionRefusedError("no server")

    monkeypatch.setattr(mail.smtplib, "SMTP", boom)
    with pytest.raises(mail.MailError):
        await mail.send(Settings(mail_backend="smtp"), "c@example.test", "Hi", "text")


async def test_the_ses_backend_calls_send_email(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, Any]] = []

    class FakeSES:
        def send_email(self, **kwargs: Any) -> None:
            calls.append(kwargs)

    monkeypatch.setattr(mail, "aws_client", lambda _s, service: FakeSES())
    await mail.send(Settings(mail_backend="ses"), "c@example.test", "Hi", "text", "<p>x</p>")
    assert calls[0]["Destination"] == {"ToAddresses": ["c@example.test"]}
    assert set(calls[0]["Message"]["Body"]) == {"Text", "Html"}
