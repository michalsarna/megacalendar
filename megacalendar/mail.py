"""SMTP sending for account confirmation, password reset and test emails.

Deliberately has no knowledge of the database: callers pass the mail server settings in (any
object with the right attributes, e.g. models.MailSettings) so this module stays trivial to test.
"""
from __future__ import annotations

import smtplib
from email.message import EmailMessage
from typing import Protocol


class MailNotConfigured(Exception):
    """Raised when a send is attempted before the master has configured a mail server."""


class MailServer(Protocol):
    host: str | None
    port: int
    username: str | None
    password: str | None
    use_tls: bool
    from_email: str | None
    from_name: str | None


def send_smtp_mail(host: str | None, port: int, username: str | None, password: str | None, use_tls: bool,
                   from_email: str | None, from_name: str | None, to_email: str, subject: str, body: str) -> None:
    if not host or not from_email:
        raise MailNotConfigured("the mail server is not configured; ask the master user to set it up")
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = f"{from_name} <{from_email}>" if from_name else from_email
    msg["To"] = to_email
    msg.set_content(body)
    with smtplib.SMTP(host, port, timeout=15) as smtp:
        if use_tls:
            smtp.starttls()
        if username:
            smtp.login(username, password or "")
        smtp.send_message(msg)


def send_confirmation_email(settings: MailServer, to_email: str, code: str) -> None:
    subject = "Confirm your megacalendar account"
    body = (f"Your confirmation code is {code}.\n\n"
           "Enter it on the confirmation page to activate your account. The code expires in 30 minutes.")
    send_smtp_mail(settings.host, settings.port, settings.username, settings.password, settings.use_tls,
                  settings.from_email, settings.from_name, to_email, subject, body)


def send_reset_email(settings: MailServer, to_email: str, code: str) -> None:
    subject = "Reset your megacalendar password"
    body = (f"Your password reset code is {code}.\n\n"
           "Enter it on the reset password page to choose a new password. The code expires in 30 minutes. "
           "If you did not request this, you can ignore this email.")
    send_smtp_mail(settings.host, settings.port, settings.username, settings.password, settings.use_tls,
                  settings.from_email, settings.from_name, to_email, subject, body)


def send_test_email(settings: MailServer, to_email: str) -> None:
    send_smtp_mail(settings.host, settings.port, settings.username, settings.password, settings.use_tls,
                  settings.from_email, settings.from_name, to_email, "megacalendar test email",
                  "This is a test email confirming your mail server settings work.")
