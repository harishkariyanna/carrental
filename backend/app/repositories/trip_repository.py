from typing import Any

from ..database import Store, public, utcnow
from ..config import get_settings
from ..services.email_service import EmailDeliveryService


class TripRepository:
    def __init__(self, store: Store):
        self.store = store

    async def booking(self, booking_id: str) -> dict[str, Any] | None:
        return await self.store.find_one("bookings", {"_id": booking_id})

    async def update_booking(self, booking_id: str, changes: dict[str, Any]) -> dict[str, Any] | None:
        return await self.store.update("bookings", booking_id, changes)

    async def driver_profile(self, user_id: str) -> dict[str, Any] | None:
        return await self.store.find_one("drivers", {"user_id": user_id})

    async def user(self, user_id: str) -> dict[str, Any] | None:
        return await self.store.find_one("users", {"_id": user_id})

    async def add_notification(self, user_id: str, event_type: str, title: str, message: str) -> None:
        await self.store.insert("notifications", {"user_id": user_id, "event_type": event_type, "title": title, "message": message, "read": False})
        await EmailDeliveryService(self.store, get_settings()).enqueue_for_user(user_id, f"RideX: {title}", message, event_type)

    async def add_otp(self, document: dict[str, Any]) -> dict[str, Any]:
        return await self.store.insert("trip_otps", document)

    async def active_otp(self, booking_id: str, purpose: str) -> dict[str, Any] | None:
        items = await self.store.find_many("trip_otps", {"booking_id": booking_id, "purpose": purpose, "consumed": False}, limit=20)
        return sorted(items, key=lambda item: str(item.get("created_at", "")), reverse=True)[0] if items else None

    async def consume_otp(self, otp_id: str) -> None:
        await self.store.update("trip_otps", otp_id, {"consumed": True, "consumed_at": utcnow()})

    async def add_extra(self, document: dict[str, Any]) -> dict[str, Any]:
        return await self.store.insert("trip_extras", document)

    async def extras(self, booking_id: str) -> list[dict[str, Any]]:
        return await self.store.find_many("trip_extras", {"booking_id": booking_id}, limit=100)

    async def public_booking(self, booking_id: str) -> dict[str, Any] | None:
        return public(await self.booking(booking_id))