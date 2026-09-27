from datetime import UTC, datetime, timedelta
from typing import Any


class LiveLocationService:
    def __init__(self, ttl_minutes: int = 30):
        self.ttl = timedelta(minutes=ttl_minutes)
        self.locations: dict[str, dict[str, Any]] = {}

    def update(self, booking_id: str, driver_id: str, latitude: float, longitude: float, accuracy: float | None) -> dict[str, Any]:
        self._discard_expired()
        location = {"driver_id": driver_id, "latitude": latitude, "longitude": longitude, "accuracy": accuracy, "last_seen": datetime.now(UTC)}
        self.locations[booking_id] = location
        return location

    def get(self, booking_id: str) -> dict[str, Any] | None:
        self._discard_expired()
        return self.locations.get(booking_id)

    def remove(self, booking_id: str) -> None:
        self.locations.pop(booking_id, None)

    def _discard_expired(self) -> None:
        cutoff = datetime.now(UTC) - self.ttl
        expired = [booking_id for booking_id, location in self.locations.items() if location["last_seen"] < cutoff]
        for booking_id in expired:
            self.locations.pop(booking_id, None)


live_locations = LiveLocationService()