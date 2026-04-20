from __future__ import annotations

import json
import smtplib
from dataclasses import dataclass, field
from email.message import EmailMessage
from typing import Protocol
from urllib.request import Request, urlopen

from .models import NotificationChannel, NotificationDelivery


class Notifier(Protocol):
    def send(self, delivery: NotificationDelivery) -> str | None: ...


@dataclass(slots=True)
class ConsoleNotifier:
    channel: NotificationChannel
    sent_messages: list[dict[str, str]] = field(default_factory=list)

    def send(self, delivery: NotificationDelivery) -> str:
        self.sent_messages.append(
            {
                "destination": delivery.destination,
                "subject": delivery.subject,
                "body": delivery.body,
            }
        )
        return f"{self.channel.value}-{len(self.sent_messages)}"


@dataclass(slots=True)
class SMTPEmailNotifier:
    host: str
    port: int
    sender: str

    def send(self, delivery: NotificationDelivery) -> str:
        message = EmailMessage()
        message["From"] = self.sender
        message["To"] = delivery.destination
        message["Subject"] = delivery.subject
        message.set_content(delivery.body)
        with smtplib.SMTP(self.host, self.port, timeout=30) as client:
            client.send_message(message)
        return message["Message-ID"] or "smtp-sent"


@dataclass(slots=True)
class JsonWebhookNotifier:
    channel: NotificationChannel
    webhook_url: str

    def send(self, delivery: NotificationDelivery) -> str:
        payload = json.dumps(
            {
                "channel": self.channel.value,
                "destination": delivery.destination,
                "subject": delivery.subject,
                "body": delivery.body,
            }
        ).encode("utf-8")
        request = Request(
            self.webhook_url,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(request, timeout=30) as response:
            return response.headers.get("X-Message-Id") or f"{self.channel.value}-webhook"


@dataclass(slots=True)
class NotifierRegistry:
    notifiers: dict[NotificationChannel, Notifier]

    def get(self, channel: NotificationChannel) -> Notifier:
        return self.notifiers[channel]
