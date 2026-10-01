from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from bson import ObjectId
from pymongo import ASCENDING, AsyncMongoClient
from pymongo.errors import DuplicateKeyError

from .config import Settings
from .security import hash_password

VEHICLE_IMAGES = {
    "innova": "https://images.unsplash.com/photo-1549317661-bd32c8ce0db2?auto=format&fit=crop&w=1200&q=85",
    "city": "https://images.unsplash.com/photo-1552519507-da3b142c6e3d?auto=format&fit=crop&w=1200&q=85",
    "creta": "https://images.unsplash.com/photo-1606664515524-ed2f786a0bd6?auto=format&fit=crop&w=1200&q=85",
    "fortuner": "https://images.unsplash.com/photo-1519641471654-76ce0107ad1b?auto=format&fit=crop&w=1200&q=85",
}


def _id() -> str:
    return uuid4().hex


def utcnow() -> datetime:
    return datetime.now(UTC)


def _serialize_object_ids(value: Any) -> Any:
    if isinstance(value, ObjectId):
        return str(value)
    if isinstance(value, datetime):
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
    if isinstance(value, dict):
        return {key: _serialize_object_ids(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_serialize_object_ids(item) for item in value]
    return value


def public(document: dict[str, Any] | None) -> dict[str, Any] | None:
    if document is None:
        return None
    result = deepcopy(document)
    result["id"] = result.pop("_id")
    result.pop("password_hash", None)
    result.pop("password_salt", None)
    return _serialize_object_ids(result)


class Store:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.client: AsyncMongoClient | None = None
        self.db: Any = None
        self.memory: dict[str, list[dict[str, Any]]] = {}

    async def connect(self) -> None:
        if self.settings.demo_mode:
            self.memory = {name: [] for name in self.collection_names}
            await self.seed()
            await self._migrate_legacy_fleet()
            return
        self.client = AsyncMongoClient(self.settings.mongodb_uri)
        self.db = self.client[self.settings.mongodb_database]
        await self.client.admin.command("ping")
        await self._create_indexes()
        await self.bootstrap_admin()
        if self.settings.seed_demo_data:
            await self.seed()
        await self._migrate_legacy_fleet()

    async def close(self) -> None:
        if self.client:
            await self.client.close()

    @property
    def collection_names(self) -> tuple[str, ...]:
        return (
            "users", "drivers", "vehicles", "quotes", "bookings", "payments",
            "notifications", "reviews", "trip_events", "audit_logs",
            "support_requests", "vehicle_reservations", "driver_reservations", "payment_webhook_events",
            "password_reset_otps", "pricing_rules", "coupons", "coupon_redemptions", "platform_settings",
            "service_fee_settings", "service_fee_records",
            "google_review_snapshots",
            "saved_locations",
            "media_blobs", "trip_otps", "trip_extras", "email_outbox",
        )

    async def _create_indexes(self) -> None:
        await self.db.users.create_index("email", unique=True)
        await self.db.bookings.create_index("public_id", unique=True)
        await self.db.payments.create_index("provider_order_id", unique=True, sparse=True)
        await self.db.trip_events.create_index([("booking_id", ASCENDING), ("action_id", ASCENDING)], unique=True)
        await self.db.vehicles.create_index([("status", ASCENDING), ("category", ASCENDING)])
        await self.db.vehicles.create_index("registration_number", unique=True, sparse=True)
        await self.db.vehicle_reservations.create_index("booking_id")
        await self.db.vehicle_reservations.create_index("expires_at", expireAfterSeconds=0)
        await self.db.driver_reservations.create_index("booking_id")
        await self.db.driver_reservations.create_index("driver_id")
        await self.db.driver_reservations.create_index("expires_at", expireAfterSeconds=0)
        await self.db.payment_webhook_events.create_index("provider_event_id", unique=True)
        await self.db.service_fee_records.create_index("payment_id", unique=True)
        await self.db.service_fee_records.create_index("booking_id")
        await self.db.password_reset_otps.create_index("expires_at", expireAfterSeconds=0)
        await self.db.coupons.create_index("code", unique=True)
        await self.db.coupon_redemptions.create_index([("coupon_id", ASCENDING), ("customer_id", ASCENDING)], unique=True)
        await self.db.pricing_rules.create_index([("service_type", ASCENDING), ("vehicle_category", ASCENDING)])
        await self.db.saved_locations.create_index("customer_id")
        await self.db.media_blobs.create_index([("entity_type", ASCENDING), ("entity_id", ASCENDING)])
        await self.db.trip_otps.create_index("expires_at", expireAfterSeconds=0)
        await self.db.trip_otps.create_index([("booking_id", ASCENDING), ("purpose", ASCENDING), ("consumed", ASCENDING)])
        await self.db.trip_extras.create_index("booking_id")
        await self.db.email_outbox.create_index([("status", ASCENDING), ("created_at", ASCENDING)])
        await self.db.email_outbox.create_index([("user_id", ASCENDING), ("created_at", ASCENDING)])

    async def _migrate_legacy_fleet(self) -> None:
        await self.update_many("vehicles", {"status": {"$in": ["AVAILABLE", "BOOKED", "ON_TRIP"]}}, {"status": "ACTIVE"})
        supported = {"SEDAN_CNG", "SEDAN_NON_CNG", "SUV", "ERTIGA", "INNOVA", "INNOVA_CRYSTA", "TT"}
        for vehicle in await self.find_many("vehicles", limit=10_000):
            if vehicle.get("category") in supported:
                continue
            name = str(vehicle.get("name", "")).upper()
            category = str(vehicle.get("category", "")).upper()
            fuel = str(vehicle.get("fuel", "")).upper()
            if "SEDAN" in category:
                normalized = "SEDAN_CNG" if fuel == "CNG" else "SEDAN_NON_CNG"
            elif "CRYSTA" in name:
                normalized = "INNOVA_CRYSTA"
            elif "INNOVA" in name or "7 SEATER" in category:
                normalized = "INNOVA"
            elif "ERTIGA" in name:
                normalized = "ERTIGA"
            elif "TRAVELLER" in name or category == "TT":
                normalized = "TT"
            else:
                normalized = "SUV"
            await self.update("vehicles", vehicle["_id"], {"category": normalized})

    async def find_one(self, collection: str, query: dict[str, Any]) -> dict[str, Any] | None:
        if self.settings.demo_mode:
            return next((deepcopy(item) for item in self.memory[collection] if self._matches(item, query)), None)
        return await self.db[collection].find_one(query)

    async def find_many(
        self,
        collection: str,
        query: dict[str, Any] | None = None,
        *,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        query = query or {}
        if self.settings.demo_mode:
            return [deepcopy(item) for item in self.memory[collection] if self._matches(item, query)][:limit]
        return await self.db[collection].find(query).limit(limit).to_list(length=limit)

    async def insert(self, collection: str, document: dict[str, Any]) -> dict[str, Any]:
        item = deepcopy(document)
        item.setdefault("_id", _id())
        item.setdefault("created_at", utcnow())
        if self.settings.demo_mode:
            if await self.find_one(collection, {"_id": item["_id"]}):
                raise DuplicateKeyError(f"duplicate key in {collection}")
            if collection == "users" and await self.find_one("users", {"email": item.get("email")}):
                raise DuplicateKeyError("email already exists")
            self.memory[collection].append(item)
            return deepcopy(item)
        await self.db[collection].insert_one(item)
        return item

    async def update(self, collection: str, item_id: str, changes: dict[str, Any]) -> dict[str, Any] | None:
        changes = {**changes, "updated_at": utcnow()}
        if self.settings.demo_mode:
            for item in self.memory[collection]:
                if item["_id"] == item_id:
                    item.update(deepcopy(changes))
                    return deepcopy(item)
            return None
        return await self.db[collection].find_one_and_update(
            {"_id": item_id}, {"$set": changes}, return_document=True
        )

    async def delete_many(self, collection: str, query: dict[str, Any]) -> None:
        if self.settings.demo_mode:
            self.memory[collection] = [item for item in self.memory[collection] if not self._matches(item, query)]
            return
        await self.db[collection].delete_many(query)

    async def update_many(self, collection: str, query: dict[str, Any], changes: dict[str, Any]) -> None:
        if self.settings.demo_mode:
            for item in self.memory[collection]:
                if self._matches(item, query):
                    item.update(deepcopy(changes))
            return
        await self.db[collection].update_many(query, {"$set": changes})

    async def count(self, collection: str, query: dict[str, Any] | None = None) -> int:
        return len(await self.find_many(collection, query, limit=10_000))

    @staticmethod
    def _matches(item: dict[str, Any], query: dict[str, Any]) -> bool:
        for key, value in query.items():
            if isinstance(value, dict) and "$in" in value:
                if item.get(key) not in value["$in"]:
                    return False
            elif item.get(key) != value:
                return False
        return True

    async def seed(self) -> None:
        await self.bootstrap_admin()
        await self._ensure_seed_user("customer-demo", "Harish Kumar", self.settings.seed_customer_email, "+919876543210", "CUSTOMER", self.settings.seed_customer_password.get_secret_value())
        await self._ensure_seed_user("driver-demo", "Raj Kumar", self.settings.seed_driver_email, "+919800000002", "DRIVER", self.settings.seed_driver_password.get_secret_value())
        if not await self.find_one("drivers", {"_id": "driver-profile-demo"}):
            await self.insert("drivers", {"_id": "driver-profile-demo", "user_id": "driver-demo", "schedule_availability": "UNAVAILABLE", "online_status": "OFFLINE", "verification_status": "VERIFIED", "documents_status": "APPROVED", "rating": 4.8, "earnings": 18400, "license_expiry": "2028-12-31"})
        else:
            profile = await self.find_one("drivers", {"_id": "driver-profile-demo"})
            if profile and not profile.get("verification_status"):
                await self.update("drivers", profile["_id"], {"verification_status": "VERIFIED", "documents_status": "APPROVED"})
        if not await self.count("vehicles"):
            vehicles = [
                {"_id": "sedan-cng", "name": "Sedan CNG", "registration_number": "KA01CG1234", "category": "SEDAN_CNG", "seats": 4, "luggage": 2, "transmission": "Manual", "fuel": "CNG", "has_ac": True, "rating": 4.7, "base_rate": 1099, "image": VEHICLE_IMAGES["city"], "status": "ACTIVE", "amenities": ["Efficient", "Comfort seats"]},
                {"_id": "city", "name": "Sedan without CNG", "registration_number": "KA01AB1234", "category": "SEDAN_NON_CNG", "seats": 4, "luggage": 2, "transmission": "Automatic", "fuel": "Petrol", "has_ac": True, "rating": 4.7, "base_rate": 1199, "image": VEHICLE_IMAGES["city"], "status": "ACTIVE", "amenities": ["Comfort seats", "Music system"]},
                {"_id": "ertiga", "name": "Maruti Suzuki Ertiga", "registration_number": "KA04ER2026", "category": "ERTIGA", "seats": 7, "luggage": 3, "transmission": "Manual", "fuel": "Petrol", "has_ac": True, "rating": 4.7, "base_rate": 1599, "image": VEHICLE_IMAGES["creta"], "status": "ACTIVE", "amenities": ["Third row", "Rear AC"]},
                {"_id": "innova", "name": "Toyota Innova", "registration_number": "KA02KK6784", "category": "INNOVA", "seats": 7, "luggage": 4, "transmission": "Manual", "fuel": "Diesel", "has_ac": True, "rating": 4.8, "base_rate": 1799, "image": VEHICLE_IMAGES["innova"], "status": "ACTIVE", "amenities": ["Spacious", "Charging", "Large boot"]},
                {"_id": "innova-crysta", "name": "Toyota Innova Crysta", "registration_number": "KA02IC2026", "category": "INNOVA_CRYSTA", "seats": 7, "luggage": 4, "transmission": "Automatic", "fuel": "Diesel", "has_ac": True, "rating": 4.9, "base_rate": 2099, "image": VEHICLE_IMAGES["innova"], "status": "ACTIVE", "amenities": ["Premium seats", "Charging", "Large boot"]},
                {"_id": "tt", "name": "Force Traveller", "registration_number": "KA05TT2026", "category": "TT", "seats": 12, "luggage": 8, "transmission": "Manual", "fuel": "Diesel", "has_ac": True, "rating": 4.7, "base_rate": 2999, "image": VEHICLE_IMAGES["fortuner"], "status": "ACTIVE", "amenities": ["Group travel", "Large luggage bay"]},
            ]
            for vehicle in vehicles:
                await self.insert("vehicles", vehicle)
        await self.update_many("vehicles", {"status": {"$in": ["AVAILABLE", "BOOKED", "ON_TRIP"]}}, {"status": "ACTIVE"})
        if not await self.find_one("bookings", {"_id": "booking-demo"}):
            await self.insert("bookings", {
                "_id": "booking-demo",
                "public_id": "RXH20260928A1234",
                "customer_id": "customer-demo",
                "vehicle_id": "innova",
                "driver_id": "driver-demo",
                "service_type": "AIRPORT",
                "pickup": "Marathahalli, Bengaluru",
                "destination": "Kempegowda International Airport",
                "scheduled_at": (utcnow() + timedelta(days=2)).isoformat(),
                "passengers": 2,
                "luggage": 2,
                "status": "DRIVER_ASSIGNED",
                "payment_status": "PAID",
                "total": 3499,
                "currency": "INR",
                "version": 1,
            })
        if not await self.find_one("platform_settings", {"_id": "global"}):
            await self.insert("platform_settings", {"_id": "global", "platform_name": "RideX", "support_email": self.settings.smtp_from_email, "support_phone": "+91 800 123 4567", "cancellation_hours": 2, "cancellation_fee_percent": 0, "google_review_url": "https://www.google.com/maps", "maintenance_mode": False, "upi_id": "ridex@upi", "standard_advance_type": "PERCENTAGE", "standard_advance_value": 25, "airport_advance_type": "PERCENTAGE", "airport_advance_value": 25, "outstation_advance_type": "PERCENTAGE", "outstation_advance_value": 30})
        if not await self.find_one("service_fee_settings", {"_id": "current"}):
            await self.insert("service_fee_settings", {"_id": "current", "application_service_fee_percent": 2, "effective_at": utcnow(), "configured_by": "super-admin-demo"})
        if not await self.count("pricing_rules"):
            multipliers = {"NORMAL": 1, "AIRPORT": 1.25, "HOURLY": 1, "OUTSTATION": 1.9}
            for vehicle in await self.find_many("vehicles"):
                for service_type, multiplier in multipliers.items():
                    await self.insert("pricing_rules", {"service_type": service_type, "vehicle_category": vehicle["category"], "base_fare": round(vehicle["base_rate"] * multiplier), "per_km": 18, "extra_hour": 200, "driver_allowance": 300 if service_type == "OUTSTATION" else 0, "tax_percent": 5, "included_hours": 4, "round_trip_multiplier": 2, "status": "ACTIVE", "version": 1})

    async def bootstrap_admin(self) -> None:
        await self._ensure_seed_user("admin-demo", "Harish K", self.settings.seed_admin_email, "+919800000001", "ADMIN", self.settings.seed_admin_password.get_secret_value())
        await self._ensure_seed_user("super-admin-demo", "RideX Owner", self.settings.seed_super_admin_email, "+919800000000", "SUPER_ADMIN", self.settings.seed_super_admin_password.get_secret_value())

    async def _ensure_seed_user(self, user_id: str, name: str, email: str, phone: str, role: str, password: str) -> None:
        if not password:
            return
        existing = await self.find_one("users", {"_id": user_id})
        if existing and existing.get("email") == email and existing.get("password_salt"):
            return
        password_digest, password_salt = hash_password(password)
        user = {"name": name, "email": email.lower(), "phone": phone, "role": role, "status": "ACTIVE", "password_hash": password_digest, "password_salt": password_salt}
        if existing:
            await self.update("users", user_id, user)
        else:
            await self.insert("users", {"_id": user_id, **user})
