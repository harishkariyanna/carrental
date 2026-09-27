import asyncio
from datetime import UTC, datetime
from email.message import EmailMessage
from email.utils import format_datetime, make_msgid
import smtplib
from typing import Any

from ..config import Settings
from ..database import Store


class EmailDeliveryService:
    def __init__(self, store: Store, settings: Settings):
        self.store = store
        self.settings = settings

    async def enqueue(self, recipient: str, subject: str, body: str, event_type: str, user_id: str | None = None) -> dict[str, Any]:
        original_recipient = recipient.strip().lower()
        disposable_redirect = self.settings.email_redirect_disposable_domains and original_recipient.endswith("@mailinator.com") and bool(self.settings.smtp_username)
        redirect_target = self.settings.email_test_redirect_to.strip().lower() or (self.settings.smtp_username.strip().lower() if disposable_redirect else "")
        redirected = bool(redirect_target and self.settings.app_env != "production")
        actual_recipient = redirect_target if redirected else original_recipient
        configured = bool(self.settings.email_delivery_enabled and self.settings.smtp_host and self.settings.smtp_password and actual_recipient)
        status = "SUPPRESSED_DEMO" if self.settings.demo_mode else "PENDING" if configured else "NOT_CONFIGURED"
        return await self.store.insert("email_outbox", {
            "user_id": user_id,
            "event_type": event_type,
            "original_recipient": original_recipient,
            "recipient": actual_recipient,
            "redirected": redirected,
            "subject": subject,
            "body": body,
            "status": status,
            "attempts": 0,
        })

    async def enqueue_for_user(self, user_id: str, subject: str, body: str, event_type: str) -> dict[str, Any] | None:
        user = await self.store.find_one("users", {"_id": user_id})
        if not user or not user.get("email"):
            return None
        return await self.enqueue(user["email"], subject, body, event_type, user_id)

    async def process_pending(self) -> int:
        pending = await self.store.find_many("email_outbox", {"status": "PENDING"}, limit=20)
        delivered = 0
        for delivery in pending:
            try:
                await asyncio.to_thread(self._send_smtp, delivery)
                await self.store.update("email_outbox", delivery["_id"], {"status": "SMTP_ACCEPTED", "attempts": delivery.get("attempts", 0) + 1, "smtp_accepted_at": datetime.now(UTC), "last_error": None})
                delivered += 1
            except Exception as exc:
                await self.store.update("email_outbox", delivery["_id"], {"status": "FAILED", "attempts": delivery.get("attempts", 0) + 1, "failed_at": datetime.now(UTC), "last_error": str(exc)[:1000]})
        return delivered

    async def retry(self, delivery_id: str) -> dict[str, Any] | None:
        delivery = await self.store.find_one("email_outbox", {"_id": delivery_id})
        if not delivery:
            return None
        return await self.store.update("email_outbox", delivery_id, {"status": "PENDING", "last_error": None})

    def _send_smtp(self, delivery: dict[str, Any]) -> None:
        message = EmailMessage()
        message["From"] = f"{self.settings.smtp_from_name} <{self.settings.smtp_from_email}>"
        message["To"] = delivery["recipient"]
        message["Reply-To"] = self.settings.smtp_from_email
        message["Subject"] = f"[Test for {delivery['original_recipient']}] {delivery['subject']}" if delivery.get("redirected") else delivery["subject"]
        message["Date"] = format_datetime(datetime.now(UTC))
        message["Message-ID"] = make_msgid(domain=self.settings.smtp_from_email.split("@")[-1])
        message["X-RideX-Event"] = delivery["event_type"]
        if delivery.get("redirected"):
            message["X-RideX-Original-Recipient"] = delivery["original_recipient"]
        redirect_notice = f"Development delivery redirect\nOriginally intended for: {delivery['original_recipient']}\n\n" if delivery.get("redirected") else ""
        message.set_content(f"{redirect_notice}{delivery['body']}")
        with smtplib.SMTP(self.settings.smtp_host, self.settings.smtp_port, timeout=20) as server:
            if self.settings.smtp_use_tls:
                server.starttls()
            if self.settings.smtp_username:
                server.login(self.settings.smtp_username, self.settings.smtp_password)
            refused = server.send_message(message, from_addr=self.settings.smtp_from_email, to_addrs=[delivery["recipient"]])
            if refused:
                raise smtplib.SMTPRecipientsRefused(refused)


async def email_worker(service: EmailDeliveryService, stop_event: asyncio.Event) -> None:
    while not stop_event.is_set():
        await service.process_pending()
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=max(1, service.settings.email_worker_interval_seconds))
        except TimeoutError:
            pass
