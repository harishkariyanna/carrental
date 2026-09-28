import asyncio
from contextlib import asynccontextmanager
from collections import Counter
from datetime import UTC, datetime, timedelta
from hashlib import sha256
import hmac
from io import BytesIO
import json
from secrets import randbelow
from typing import Any
from urllib.parse import urlencode
from uuid import uuid4

import httpx
import qrcode
from fastapi import Depends, FastAPI, HTTPException, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pymongo.errors import DuplicateKeyError
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

from .config import Settings
from .controllers.maps_controller import router as maps_router
from .controllers.media_controller import router as media_router
from .controllers.trip_controller import router as trip_router
from .database import public, utcnow
from .dependencies import require_active_driver, require_verified_driver, settings, store
from .schemas import BookingCreate, CouponInput, CustomerProfileUpdate, DriverAssignment, DriverCreate, DriverUpdate, LoginRequest, PlatformSettingsUpdate, PricingRuleInput, QuoteRequest, RegisterRequest, ReviewCreate, ReviewModeration, SavedLocationInput, ServiceType, TripTransition, UserUpdate, VehicleDriverAssignment, VehicleInput, VehicleUpdate
from .security import create_session_token, hash_password, optional_session_claims, require_roles, session_claims, verify_access_token, verify_password
from .services.map_service import MapService
from .services.email_service import EmailDeliveryService, email_worker
from .services.live_location_service import live_locations
from .services.pricing_service import calculate_vehicle_quote, public_vehicle

email_delivery = EmailDeliveryService(store, settings)

@asynccontextmanager
async def lifespan(_: FastAPI):
    await store.connect()
    stop_email_worker = asyncio.Event()
    email_task = asyncio.create_task(email_worker(email_delivery, stop_email_worker))
    try:
        yield
    finally:
        stop_email_worker.set()
        await email_task
        await store.close()


app = FastAPI(title=settings.app_name, version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(maps_router, prefix=settings.api_prefix)
app.include_router(media_router, prefix=settings.api_prefix)
app.include_router(trip_router, prefix=settings.api_prefix)


def token_response(user: dict[str, Any]) -> dict[str, str]:
    return {
        "access_token": create_session_token(user["_id"], user["role"], user["name"], user["email"], user.get("phone", ""), settings),
        "token_type": "bearer",
    }


def clear_legacy_auth_cookies(response: Response) -> None:
    response.delete_cookie("ridex_session")
    response.delete_cookie("ridex_csrf")


async def current_user(claims: dict[str, str] = Depends(session_claims)) -> dict[str, Any]:
    user = await store.find_one("users", {"_id": claims["sub"]})
    if not user or user.get("status") != "ACTIVE":
        raise HTTPException(status_code=401, detail="Account unavailable")
    return user


async def quote_total(request: QuoteRequest, vehicle: dict[str, Any], distance_km: float | None = None) -> tuple[int, list[dict[str, Any]], dict[str, Any]]:
    rule = await store.find_one("pricing_rules", {"service_type": request.service_type.value, "vehicle_category": vehicle["category"], "status": "ACTIVE"})
    if not rule:
        if request.service_type.value in {"NORMAL", "OUTSTATION"}:
            rule = {"base_fare": vehicle.get("base_rate", 0), "driver_allowance": 0, "tax_percent": 5}
        else:
            raise HTTPException(status_code=422, detail=f"No active pricing rule for {request.service_type.value} / {vehicle['category']}")
    return calculate_vehicle_quote(service_type=request.service_type.value, vehicle=vehicle, rule=rule, distance_km=distance_km, round_trip=request.round_trip, scheduled_at=request.scheduled_at, return_at=request.return_at, package_hours=request.package_hours, ac_required=request.ac_required)


def reservation_slots(request_data: dict[str, Any]) -> list[str]:
    start = datetime.fromisoformat(request_data["scheduled_at"])
    hours = request_data.get("package_hours") or {"NORMAL": 3, "AIRPORT": 4, "OUTSTATION": 12}.get(request_data["service_type"], 3)
    if request_data.get("round_trip") and request_data.get("return_at"):
        hours = max(1, int((datetime.fromisoformat(request_data["return_at"]) - start).total_seconds() / 3600) + 1)
    start = start.replace(minute=0 if start.minute < 30 else 30, second=0, microsecond=0)
    return [(start + timedelta(minutes=30 * offset)).astimezone(UTC).isoformat() for offset in range(hours * 2)]


DRIVER_SCHEDULE_STATES = {"DRIVER_ASSIGNED", "DRIVER_ACCEPTED", "DRIVER_ON_THE_WAY", "DRIVER_ARRIVED", "TRIP_STARTED", "DESTINATION_REACHED", "COMPLETION_OTP_PENDING"}
DRIVER_ACTIVE_STATES = {"DRIVER_ON_THE_WAY", "DRIVER_ARRIVED", "TRIP_STARTED", "DESTINATION_REACHED", "COMPLETION_OTP_PENDING"}


def booking_schedule(booking: dict[str, Any]) -> tuple[datetime, datetime, list[str]]:
    slots = reservation_slots(booking)
    start = datetime.fromisoformat(booking["scheduled_at"].replace("Z", "+00:00"))
    end = datetime.fromisoformat(slots[-1].replace("Z", "+00:00")) + timedelta(minutes=30)
    return start, end, slots


async def driver_assignment_eligibility(driver_id: str, booking: dict[str, Any]) -> tuple[dict[str, Any] | None, dict[str, Any] | None, str | None]:
    driver = await store.find_one("users", {"_id": driver_id, "role": "DRIVER"})
    profile = await store.find_one("drivers", {"user_id": driver_id})
    if not driver or driver.get("status") != "ACTIVE":
        return driver, profile, "Driver account is inactive"
    if not profile or profile.get("verification_status") != "VERIFIED":
        return driver, profile, "Driver is not approved"
    if profile.get("schedule_availability", "AVAILABLE") != "AVAILABLE":
        return driver, profile, "Driver is marked unavailable by admin"
    requested_start, requested_end, _ = booking_schedule(booking)
    for existing in await store.find_many("bookings", {"driver_id": driver_id}, limit=10_000):
        if existing.get("_id") == booking.get("_id") or existing.get("status") not in DRIVER_SCHEDULE_STATES:
            continue
        if existing.get("status") in DRIVER_ACTIVE_STATES:
            return driver, profile, f"Active trip {existing.get('public_id', existing['_id'])} is in progress"
        existing_start, existing_end, _ = booking_schedule(existing)
        if requested_start < existing_end and requested_end > existing_start:
            return driver, profile, f"Overlaps {existing.get('public_id', existing['_id'])} from {existing_start.isoformat()} to {existing_end.isoformat()}"
    return driver, profile, None


async def claim_driver_schedule(driver_id: str, booking: dict[str, Any]) -> bool:
    _, schedule_end, slots = booking_schedule(booking)
    inserted_ids: list[str] = []
    for slot in slots:
        reservation_id = f"{driver_id}:{slot}"
        existing = await store.find_one("driver_reservations", {"_id": reservation_id})
        if existing:
            if existing.get("booking_id") == booking["_id"]:
                continue
            for inserted_id in inserted_ids:
                await store.delete_many("driver_reservations", {"_id": inserted_id})
            return False
        try:
            await store.insert("driver_reservations", {"_id": reservation_id, "driver_id": driver_id, "booking_id": booking["_id"], "slot": slot, "expires_at": schedule_end + timedelta(days=1)})
            inserted_ids.append(reservation_id)
        except DuplicateKeyError:
            winner = await store.find_one("driver_reservations", {"_id": reservation_id})
            if winner and winner.get("booking_id") == booking["_id"]:
                continue
            for inserted_id in inserted_ids:
                await store.delete_many("driver_reservations", {"_id": inserted_id})
            return False
    return True


async def add_notification(user_id: str, event_type: str, title: str, message: str) -> None:
    await store.insert("notifications", {"user_id": user_id, "event_type": event_type, "title": title, "message": message, "read": False})
    await email_delivery.enqueue_for_user(user_id, f"RideX: {title}", message, event_type)


async def assign_booking_driver(booking: dict[str, Any], driver_id: str, source: str, actor_id: str = "system") -> tuple[dict[str, Any] | None, str | None]:
    driver, _, reason = await driver_assignment_eligibility(driver_id, booking)
    if reason:
        return None, reason
    if not await claim_driver_schedule(driver_id, booking):
        return None, "Driver schedule was just reserved by another booking"
    previous_driver_id = booking.get("driver_id")
    updated = await store.update("bookings", booking["_id"], {"driver_id": driver_id, "status": "DRIVER_ASSIGNED", "assignment_status": source, "assignment_reason": None, "version": booking.get("version", 1) + 1})
    if not updated:
        await store.delete_many("driver_reservations", {"booking_id": booking["_id"], "driver_id": driver_id})
        return None, "Booking could not be updated"
    if previous_driver_id and previous_driver_id != driver_id:
        await store.delete_many("driver_reservations", {"booking_id": booking["_id"], "driver_id": previous_driver_id})
        await add_notification(previous_driver_id, "DRIVER_REASSIGNED", "Trip reassigned", f"Trip {booking['public_id']} was reassigned to another driver.")
    if previous_driver_id != driver_id:
        await add_notification(driver_id, "DRIVER_ASSIGNED", "New trip assigned", f"Trip {booking['public_id']} is ready for review.")
        await add_notification(booking["customer_id"], "DRIVER_ASSIGNED", "Driver assigned", f"{driver['name']} has been assigned to your ride.")
    await store.insert("audit_logs", {"actor_user_id": actor_id, "action": source, "entity_type": "booking", "entity_id": booking["_id"], "metadata": {"driver_id": driver_id, "previous_driver_id": previous_driver_id}})
    return updated, None


async def auto_assign_vehicle_driver(booking: dict[str, Any]) -> dict[str, Any]:
    default_profile = await store.find_one("drivers", {"assigned_vehicle_id": booking["vehicle_id"]})
    if not default_profile:
        return await store.update("bookings", booking["_id"], {"assignment_status": "AWAITING_ADMIN", "assignment_reason": "Vehicle has no default driver"}) or booking
    updated, reason = await assign_booking_driver(booking, default_profile["user_id"], "AUTO_ASSIGNED")
    if updated:
        return updated
    return await store.update("bookings", booking["_id"], {"assignment_status": "AWAITING_ADMIN", "assignment_reason": reason or "Default driver is unavailable"}) or booking


async def audit_admin(admin_id: str, action: str, entity_type: str, entity_id: str, metadata: dict[str, Any] | None = None) -> None:
    await store.insert("audit_logs", {"actor_user_id": admin_id, "action": action, "entity_type": entity_type, "entity_id": entity_id, "metadata": metadata or {}})


SENSITIVE_DATABASE_FIELDS = {"password_hash", "password_salt", "otp_hash", "otp_salt", "code_hash", "code_salt", "code_ciphertext", "data", "body"}
DATABASE_CLEANUP_COLLECTIONS = {"notifications", "email_outbox", "support_requests", "password_reset_otps", "quotes", "vehicle_reservations"}


def safe_database_record(document: dict[str, Any]) -> dict[str, Any]:
    record = public(document) or {}
    for key in SENSITIVE_DATABASE_FIELDS:
        if key in record:
            record[key] = "[REDACTED]"
    return record


def database_record_deletable(collection: str, document: dict[str, Any]) -> bool:
    if collection == "notifications":
        return True
    if collection == "email_outbox":
        return document.get("status") in {"SMTP_ACCEPTED", "FAILED", "SUPPRESSED_DEMO", "NOT_CONFIGURED"}
    if collection == "support_requests":
        return document.get("status") == "RESOLVED"
    if collection == "password_reset_otps":
        return bool(document.get("consumed")) or document.get("expires_at", utcnow()) <= utcnow()
    if collection in {"quotes", "vehicle_reservations"}:
        expiry = document.get("expires_at")
        if isinstance(expiry, str):
            expiry = datetime.fromisoformat(expiry.replace("Z", "+00:00"))
        return bool(expiry and expiry <= utcnow())
    return False


def day_key(value: Any) -> str:
    if isinstance(value, datetime):
        return value.astimezone(UTC).date().isoformat()
    if isinstance(value, str):
        return datetime.fromisoformat(value.replace("Z", "+00:00")).date().isoformat()
    return utcnow().date().isoformat()


def as_utc_datetime(value: datetime | str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00")) if isinstance(value, str) else value
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)


async def enrich_booking(booking: dict[str, Any]) -> dict[str, Any]:
    customer = await store.find_one("users", {"_id": booking.get("customer_id")})
    driver = await store.find_one("users", {"_id": booking.get("driver_id")}) if booking.get("driver_id") else None
    driver_profile = await store.find_one("drivers", {"user_id": booking.get("driver_id")}) if booking.get("driver_id") else None
    vehicle = await store.find_one("vehicles", {"_id": booking.get("vehicle_id")})
    default_profile = await store.find_one("drivers", {"assigned_vehicle_id": booking.get("vehicle_id")})
    default_driver = await store.find_one("users", {"_id": default_profile.get("user_id")}) if default_profile else None
    driver_location = live_locations.get(booking["_id"])
    if not driver_location and driver_profile and booking.get("status") in {"DRIVER_ACCEPTED", "DRIVER_ON_THE_WAY", "DRIVER_ARRIVED", "TRIP_STARTED", "DESTINATION_REACHED", "COMPLETION_OTP_PENDING"}:
        driver_location = {"latitude": driver_profile.get("latitude"), "longitude": driver_profile.get("longitude"), "last_seen": driver_profile.get("last_seen"), "online_status": driver_profile.get("online_status", "OFFLINE")}
    return {**(public(booking) or {}), "customer": public(customer), "driver": public(driver), "default_driver": public(default_driver), "driver_location": driver_location, "vehicle": public(vehicle)}


async def confirm_payment(payment: dict[str, Any], provider_payment_id: str) -> dict[str, Any]:
    booking = await store.find_one("bookings", {"_id": payment["booking_id"]})
    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found")
    if payment.get("status") == "PAID":
        if not booking.get("driver_id") and booking.get("status") == "CONFIRMED":
            return await auto_assign_vehicle_driver(booking)
        return booking
    if booking.get("coupon_id"):
        coupon = await store.find_one("coupons", {"_id": booking["coupon_id"]})
        if not coupon or coupon.get("used_count", 0) >= coupon.get("usage_limit", 1):
            raise HTTPException(status_code=409, detail="Coupon usage limit has been reached")
        try:
            await store.insert("coupon_redemptions", {"_id": f"{coupon['_id']}:{booking['customer_id']}", "coupon_id": coupon["_id"], "customer_id": booking["customer_id"], "booking_id": booking["_id"], "redeemed_at": utcnow()})
        except DuplicateKeyError as exc:
            raise HTTPException(status_code=409, detail="This coupon has already been used by this customer") from exc
        await store.update("coupons", coupon["_id"], {"used_count": coupon.get("used_count", 0) + 1})
    await store.update("payments", payment["_id"], {"status": "PAID", "provider_payment_id": provider_payment_id, "verified_at": utcnow()})
    paid_amount = int(booking.get("paid_amount", 0)) + int(payment["amount"])
    payment_status = "PAID" if paid_amount >= int(booking["total"]) else "ADVANCE_PAID"
    updated = await store.update("bookings", booking["_id"], {"status": "CONFIRMED", "payment_status": payment_status, "paid_amount": paid_amount, "balance_due": max(0, int(booking["total"]) - paid_amount), "version": booking.get("version", 1) + 1})
    _, scheduled_end, _ = booking_schedule(updated or booking)
    reservation_expiry = scheduled_end + timedelta(days=1)
    await store.update_many("vehicle_reservations", {"booking_id": booking["_id"]}, {"status": "ACTIVE", "expires_at": reservation_expiry})
    updated = await auto_assign_vehicle_driver(updated or booking)
    await add_notification(booking["customer_id"], "BOOKING_CONFIRMED", "Booking confirmed", f"Booking {booking['public_id']} is confirmed.")
    return updated or booking


async def payment_policy(booking: dict[str, Any]) -> tuple[int, str, dict[str, Any]]:
    platform = await store.find_one("platform_settings", {"_id": "global"}) or {}
    service_type = booking.get("service_type")
    if service_type == "AIRPORT":
        policy_type, value = platform.get("airport_advance_type", "PERCENTAGE"), int(platform.get("airport_advance_value", 25))
    elif service_type == "OUTSTATION":
        policy_type, value = platform.get("outstation_advance_type", "PERCENTAGE"), int(platform.get("outstation_advance_value", 30))
    else:
        policy_type, value = platform.get("standard_advance_type", "PERCENTAGE"), int(platform.get("standard_advance_value", 25))
    amount = round(int(booking["total"]) * value / 100) if policy_type == "PERCENTAGE" else value
    amount = max(1, min(int(booking["total"]), amount))
    return amount, "FULL" if amount >= int(booking["total"]) else f"ADVANCE_{policy_type}", platform


@app.get(f"{settings.api_prefix}/payment-policy/preview")
async def payment_policy_preview(service_type: str, total: int) -> dict[str, Any]:
    if service_type not in {item.value for item in ServiceType} or total <= 0:
        raise HTTPException(status_code=422, detail="Valid service type and total are required")
    amount, payment_type, _ = await payment_policy({"service_type": service_type, "total": total})
    return {"amount": amount, "remaining": max(0, total - amount), "booking_total": total, "payment_type": payment_type}


def upi_payment_uri(upi_id: str, amount: int, reference: str) -> str:
    return "upi://pay?" + urlencode({"pa": upi_id, "pn": settings.smtp_from_name, "am": f"{amount:.2f}", "cu": "INR", "tr": reference, "tn": f"RideX {reference}"})


async def applicable_coupon(code: str, customer_id: str | None, booking_total: int) -> tuple[dict[str, Any], int]:
    coupon = await store.find_one("coupons", {"code": code.upper(), "status": "ACTIVE"})
    now = utcnow()
    valid_from = as_utc_datetime(coupon["valid_from"]) if coupon and coupon.get("valid_from") else None
    valid_to = as_utc_datetime(coupon["valid_to"]) if coupon and coupon.get("valid_to") else None
    if not coupon or not valid_from or not valid_to or valid_from > now or valid_to < now:
        raise HTTPException(status_code=422, detail="Coupon is invalid or expired")
    if coupon.get("scope", "PUBLIC") == "PERSONAL":
        if not customer_id:
            raise HTTPException(status_code=401, detail="Sign in to use this personal coupon")
        if coupon.get("customer_id") != customer_id:
            raise HTTPException(status_code=403, detail="This coupon is assigned to another customer")
    if customer_id and await store.find_one("coupon_redemptions", {"coupon_id": coupon["_id"], "customer_id": customer_id}):
        raise HTTPException(status_code=409, detail="This coupon has already been used")
    if coupon.get("used_count", 0) >= coupon.get("usage_limit", 1):
        raise HTTPException(status_code=409, detail="Coupon usage limit has been reached")
    if booking_total < coupon.get("minimum_booking", 0):
        raise HTTPException(status_code=422, detail=f"Coupon requires a minimum fare of ₹{coupon['minimum_booking']}")
    discount = int(booking_total * coupon["value"] / 100) if coupon["discount_type"] == "PERCENTAGE" else int(coupon["value"])
    maximum = int(coupon.get("maximum_discount", 0))
    if maximum:
        discount = min(discount, maximum)
    return coupon, min(discount, booking_total)


@app.get("/")
async def root() -> dict[str, str]:
    return {"name": settings.app_name, "docs": "/docs", "health": "/health"}


@app.get("/health")
async def health() -> dict[str, str | bool]:
    return {"status": "ok", "database": "memory-demo" if settings.demo_mode else "mongodb-atlas", "demo_mode": settings.demo_mode}


@app.post(f"{settings.api_prefix}/auth/register", status_code=201)
async def register(payload: RegisterRequest, response: Response) -> dict[str, str]:
    password_digest, password_salt = hash_password(payload.password)
    user = {"_id": uuid4().hex, "name": payload.name.strip(), "email": payload.email.lower(), "phone": payload.phone, "role": payload.role, "status": "ACTIVE", "password_hash": password_digest, "password_salt": password_salt}
    try:
        await store.insert("users", user)
        if payload.role == "DRIVER":
            await store.insert("drivers", {"user_id": user["_id"], "schedule_availability": "AVAILABLE", "online_status": "OFFLINE", "verification_status": "PENDING", "license_number": payload.license_number, "license_expiry": payload.license_expiry, "documents_status": "INCOMPLETE", "rating": 0, "earnings": 0})
    except DuplicateKeyError as exc:
        raise HTTPException(status_code=409, detail="An account with this email already exists") from exc
    await add_notification(user["_id"], "ACCOUNT_CREATED", "Welcome to RideX" if payload.role == "CUSTOMER" else "Driver application started", "Your RideX account is ready." if payload.role == "CUSTOMER" else "Upload your licence, vehicle photos, and address proof to submit your driver application for review.")
    clear_legacy_auth_cookies(response)
    return token_response(user)


@app.post(f"{settings.api_prefix}/auth/login")
async def login(payload: LoginRequest, response: Response) -> dict[str, str]:
    user = await store.find_one("users", {"email": payload.email.lower()})
    if not user or not verify_password(payload.password, user["password_hash"], user.get("password_salt", "")):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    clear_legacy_auth_cookies(response)
    return token_response(user)


@app.post(f"{settings.api_prefix}/auth/logout")
async def logout(response: Response) -> dict[str, str]:
    clear_legacy_auth_cookies(response)
    return {"message": "Signed out"}


@app.get(f"{settings.api_prefix}/auth/me")
async def me(user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
    return public(user) or {}


@app.get(f"{settings.api_prefix}/auth/session")
async def session(claims: dict[str, str] | None = Depends(optional_session_claims)) -> dict[str, Any] | None:
    if not claims:
        return None
    user = await store.find_one("users", {"_id": claims["sub"]})
    return {"user": public(user), **token_response(user)} if user and user.get("status") == "ACTIVE" else None


@app.get(f"{settings.api_prefix}/customer/dashboard")
async def customer_dashboard(customer: dict[str, str] = Depends(require_roles("CUSTOMER"))) -> dict[str, Any]:
    user = await store.find_one("users", {"_id": customer["sub"]})
    bookings = await store.find_many("bookings", {"customer_id": customer["sub"]}, limit=1000)
    notifications = await store.find_many("notifications", {"user_id": customer["sub"]}, limit=1000)
    reviews = await store.find_many("reviews", {"customer_id": customer["sub"]}, limit=1000)
    locations = await store.find_many("saved_locations", {"customer_id": customer["sub"]}, limit=1000)
    upcoming_states = {"CONFIRMED", "DRIVER_ASSIGNED", "DRIVER_ACCEPTED"}
    active_states = {"DRIVER_ACCEPTED", "DRIVER_ON_THE_WAY", "DRIVER_ARRIVED", "TRIP_STARTED", "DESTINATION_REACHED", "COMPLETION_OTP_PENDING"}
    sorted_bookings = sorted(bookings, key=lambda item: str(item.get("scheduled_at", "")), reverse=True)
    active_booking = next((booking for booking in sorted_bookings if booking.get("status") in active_states), None)
    return {
        "customer": public(user),
        "stats": {
            "total_bookings": len(bookings),
            "upcoming": sum(booking.get("status") in upcoming_states for booking in bookings),
            "active": sum(booking.get("status") in active_states for booking in bookings),
            "completed": sum(booking.get("status") == "TRIP_COMPLETED" for booking in bookings),
            "unread_notifications": sum(not notification.get("read") for notification in notifications),
            "saved_locations": len(locations),
            "reviews": len(reviews),
        },
        "upcoming_bookings": [await enrich_booking(booking) for booking in sorted_bookings if booking.get("status") in upcoming_states][:3],
        "active_booking": await enrich_booking(active_booking) if active_booking else None,
        "recent_notifications": [public(item) for item in sorted(notifications, key=lambda row: str(row.get("created_at", "")), reverse=True)[:5]],
    }


@app.get(f"{settings.api_prefix}/customer/profile")
async def customer_profile(customer: dict[str, str] = Depends(require_roles("CUSTOMER"))) -> dict[str, Any]:
    user = await store.find_one("users", {"_id": customer["sub"]})
    return public(user) or {}


@app.patch(f"{settings.api_prefix}/customer/profile", dependencies=[Depends(verify_access_token)])
async def customer_update_profile(payload: CustomerProfileUpdate, customer: dict[str, str] = Depends(require_roles("CUSTOMER"))) -> dict[str, Any]:
    updated = await store.update("users", customer["sub"], payload.model_dump(exclude_none=True))
    if not updated:
        raise HTTPException(status_code=404, detail="Customer not found")
    return {"user": public(updated), **token_response(updated)}


@app.get(f"{settings.api_prefix}/customer/saved-locations")
async def customer_saved_locations(customer: dict[str, str] = Depends(require_roles("CUSTOMER"))) -> list[dict[str, Any]]:
    return [public(item) for item in await store.find_many("saved_locations", {"customer_id": customer["sub"]}) if item]


@app.post(f"{settings.api_prefix}/customer/saved-locations", status_code=201, dependencies=[Depends(verify_access_token)])
async def customer_create_saved_location(payload: SavedLocationInput, customer: dict[str, str] = Depends(require_roles("CUSTOMER"))) -> dict[str, Any]:
    location = await store.insert("saved_locations", {"customer_id": customer["sub"], **payload.model_dump()})
    return public(location) or {}


@app.delete(f"{settings.api_prefix}/customer/saved-locations/{{location_id}}", dependencies=[Depends(verify_access_token)])
async def customer_delete_saved_location(location_id: str, customer: dict[str, str] = Depends(require_roles("CUSTOMER"))) -> dict[str, str]:
    location = await store.find_one("saved_locations", {"_id": location_id, "customer_id": customer["sub"]})
    if not location:
        raise HTTPException(status_code=404, detail="Saved location not found")
    await store.delete_many("saved_locations", {"_id": location_id, "customer_id": customer["sub"]})
    return {"message": "Saved location removed"}


@app.get(f"{settings.api_prefix}/customer/reviews")
async def customer_reviews(customer: dict[str, str] = Depends(require_roles("CUSTOMER"))) -> list[dict[str, Any]]:
    reviews = await store.find_many("reviews", {"customer_id": customer["sub"]}, limit=1000)
    result = []
    for review in reviews:
        booking = await store.find_one("bookings", {"_id": review.get("booking_id")})
        result.append({**(public(review) or {}), "booking_public_id": booking.get("public_id") if booking else None})
    return result


@app.post(f"{settings.api_prefix}/auth/forgot-password")
async def forgot_password(payload: dict[str, str]) -> dict[str, str]:
    email = payload.get("email", "").strip().lower()
    user = await store.find_one("users", {"email": email})
    if user:
        otp = f"{randbelow(1_000_000):06d}"
        otp_hash, otp_salt = hash_password(otp)
        await store.insert("password_reset_otps", {"user_id": user["_id"], "email": email, "otp_hash": otp_hash, "otp_salt": otp_salt, "expires_at": utcnow() + timedelta(minutes=10), "attempts": 0, "consumed": False})
        await email_delivery.enqueue(email, "Your RideX password reset code", f"Your RideX password reset code is {otp}. It expires in 10 minutes. If you did not request this, ignore this email.", "PASSWORD_RESET", user["_id"])
    return {"message": "If the account exists, a reset code has been sent."}


@app.post(f"{settings.api_prefix}/auth/reset-password")
async def reset_password(payload: dict[str, str]) -> dict[str, str]:
    email = payload.get("email", "").strip().lower()
    otp = payload.get("otp", "")
    new_password = payload.get("new_password", "")
    if len(new_password) < 8:
        raise HTTPException(status_code=422, detail="Password must be at least 8 characters")
    user = await store.find_one("users", {"email": email})
    records = await store.find_many("password_reset_otps", {"email": email, "consumed": False}, limit=20)
    record = records[-1] if records else None
    if not user or not record or record["expires_at"] < utcnow() or record.get("attempts", 0) >= 5:
        raise HTTPException(status_code=400, detail="Invalid or expired reset code")
    if not verify_password(otp, record["otp_hash"], record["otp_salt"]):
        await store.update("password_reset_otps", record["_id"], {"attempts": record.get("attempts", 0) + 1})
        raise HTTPException(status_code=400, detail="Invalid or expired reset code")
    password_digest, password_salt = hash_password(new_password)
    await store.update("users", user["_id"], {"password_hash": password_digest, "password_salt": password_salt})
    await store.update("password_reset_otps", record["_id"], {"consumed": True})
    return {"message": "Password updated. You can now sign in."}


@app.get(f"{settings.api_prefix}/vehicles")
async def vehicles() -> list[dict[str, Any]]:
    return [public_vehicle(item, public) for item in await store.find_many("vehicles", {"status": "AVAILABLE"})]


@app.get(f"{settings.api_prefix}/vehicles/{{vehicle_id}}")
async def vehicle_detail(vehicle_id: str) -> dict[str, Any]:
    vehicle = await store.find_one("vehicles", {"_id": vehicle_id})
    if not vehicle:
        raise HTTPException(status_code=404, detail="Vehicle not found")
    return public_vehicle(vehicle, public)


@app.post(f"{settings.api_prefix}/quotes")
async def create_quotes(payload: QuoteRequest, claims: dict[str, str] | None = Depends(optional_session_claims)) -> dict[str, Any]:
    if payload.service_type.value != "HOURLY" and not payload.destination:
        raise HTTPException(status_code=422, detail="Destination is required for this service")
    available = await store.find_many("vehicles", {"status": "AVAILABLE"})
    eligible = [v for v in available if v["seats"] >= payload.passengers and v["luggage"] >= payload.luggage and (payload.service_type.value != "OUTSTATION" or not payload.ac_required or v.get("has_ac", False))]
    route = None
    if payload.service_type.value in {"NORMAL", "OUTSTATION"} and None not in {payload.pickup_latitude, payload.pickup_longitude, payload.drop_latitude, payload.drop_longitude}:
        route = await MapService().route(payload.pickup_latitude, payload.pickup_longitude, payload.drop_latitude, payload.drop_longitude)
    distance_km = float(route["distance_m"]) / 1000 if route else None
    results = []
    coupon_messages: set[str] = set()
    for vehicle in eligible:
        total, line_items, pricing = await quote_total(payload, vehicle, distance_km)
        pricing["estimated_duration_minutes"] = round(float(route["duration_s"]) / 60) if route else None
        coupon = None
        discount = 0
        if payload.coupon_code:
            try:
                coupon, discount = await applicable_coupon(payload.coupon_code, claims.get("sub") if claims and claims.get("role") == "CUSTOMER" else None, total)
            except HTTPException as exc:
                if exc.status_code == 422 and isinstance(exc.detail, str) and exc.detail.startswith("Coupon requires a minimum fare"):
                    pricing["coupon_ineligible_reason"] = exc.detail
                    coupon_messages.add(exc.detail)
                else:
                    raise
            if coupon:
                line_items.append({"code": "COUPON", "label": f"Coupon {coupon['code']}", "amount": -discount})
                total -= discount
                pricing["coupon"] = {"id": coupon["_id"], "code": coupon["code"], "discount": discount, "scope": coupon.get("scope", "PUBLIC")}
        quote = await store.insert("quotes", {"vehicle_id": vehicle["_id"], "request": payload.model_dump(mode="json"), "total": total, "currency": "INR", "line_items": line_items, "pricing": pricing, "coupon_id": coupon["_id"] if coupon else None, "coupon_code": coupon["code"] if coupon else None, "coupon_discount": discount, "expires_at": (utcnow() + timedelta(minutes=15)).isoformat()})
        results.append({"quote_id": quote["_id"], "vehicle": public_vehicle(vehicle, public), "total": total, "currency": "INR", "line_items": line_items, "pricing": pricing, "expires_at": quote["expires_at"]})
    coupon_message = " ".join(sorted(coupon_messages)) if coupon_messages else None
    return {"results": results, "count": len(results), "coupon_message": coupon_message, "route": {"distance_km": round(distance_km, 1), "estimated_duration_minutes": round(float(route["duration_s"]) / 60)} if route else None}


@app.post(f"{settings.api_prefix}/bookings", status_code=201, dependencies=[Depends(verify_access_token)])
async def create_booking(payload: BookingCreate, user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
    if user["role"] != "CUSTOMER":
        raise HTTPException(status_code=403, detail="Only customers can create bookings")
    quote = await store.find_one("quotes", {"_id": payload.quote_id})
    if not quote or quote["vehicle_id"] != payload.vehicle_id:
        raise HTTPException(status_code=404, detail="Quote not found")
    if datetime.fromisoformat(quote["expires_at"]) < utcnow():
        raise HTTPException(status_code=410, detail="Quote expired")
    if quote.get("coupon_code"):
        await applicable_coupon(quote["coupon_code"], user["_id"], int(quote["total"]) + int(quote.get("coupon_discount", 0)))
    request_data = quote["request"]
    existing = await store.find_one("bookings", {"customer_id": user["_id"], "quote_id": payload.quote_id, "status": "PENDING_PAYMENT"})
    if not existing:
        existing = await store.find_one("bookings", {"customer_id": user["_id"], "vehicle_id": payload.vehicle_id, "scheduled_at": request_data["scheduled_at"], "status": "PENDING_PAYMENT", "payment_status": "PENDING"})
    if existing:
        updated = await store.update("bookings", existing["_id"], {"quote_id": payload.quote_id, "coupon_id": quote.get("coupon_id"), "coupon_code": quote.get("coupon_code"), "coupon_discount": quote.get("coupon_discount", 0), "passenger_name": payload.passenger_name, "passenger_phone": payload.passenger_phone, "special_instructions": payload.special_instructions, "quoted_total": quote["total"], "total": quote["total"], "currency": quote["currency"], "line_items": quote["line_items"], "pricing": quote.get("pricing", {}), "version": existing.get("version", 1) + 1})
        return public(updated or existing) or {}
    booking_id = uuid4().hex
    try:
        for slot in reservation_slots(request_data):
            await store.insert("vehicle_reservations", {"_id": f"{payload.vehicle_id}:{slot}", "vehicle_id": payload.vehicle_id, "booking_id": booking_id, "slot": slot, "status": "HOLD", "expires_at": datetime.fromisoformat(quote["expires_at"])})
    except DuplicateKeyError as exc:
        await store.delete_many("vehicle_reservations", {"booking_id": booking_id})
        raise HTTPException(status_code=409, detail="This vehicle was just reserved. Please choose another car.") from exc
    tariff = quote.get("pricing", {}).get("vehicle_tariff", {})
    _, scheduled_end, _ = booking_schedule(request_data)
    booking = await store.insert("bookings", {"_id": booking_id, "quote_id": payload.quote_id, "public_id": f"RX{utcnow():%Y%m%d}{uuid4().hex[:5].upper()}", "customer_id": user["_id"], "vehicle_id": payload.vehicle_id, "driver_id": None, "service_type": request_data["service_type"], "pickup": request_data["pickup"], "destination": request_data.get("destination") or request_data["pickup"], "pickup_latitude": request_data.get("pickup_latitude"), "pickup_longitude": request_data.get("pickup_longitude"), "drop_latitude": request_data.get("drop_latitude"), "drop_longitude": request_data.get("drop_longitude"), "scheduled_at": request_data["scheduled_at"], "scheduled_end_at": scheduled_end.isoformat(), "return_at": request_data.get("return_at"), "airport_direction": request_data.get("airport_direction"), "airport_pickup_at": request_data.get("airport_pickup_at"), "airport_grace_minutes": 30, "airport_waiting_rate": 150, "waiting_grace_minutes": tariff.get("local_waiting_grace_minutes", 15), "waiting_rate_per_minute": tariff.get("local_waiting_rate_per_minute", 5), "flight_number": request_data.get("flight_number"), "passengers": request_data["passengers"], "luggage": request_data["luggage"], "package_hours": request_data.get("package_hours"), "round_trip": request_data.get("round_trip", False), "ac_required": request_data.get("ac_required", True), "coupon_id": quote.get("coupon_id"), "coupon_code": quote.get("coupon_code"), "coupon_discount": quote.get("coupon_discount", 0), "passenger_name": payload.passenger_name, "passenger_phone": payload.passenger_phone, "special_instructions": payload.special_instructions, "status": "PENDING_PAYMENT", "payment_status": "PENDING", "assignment_status": "PENDING_PAYMENT", "quoted_total": quote["total"], "total": quote["total"], "currency": quote["currency"], "line_items": quote["line_items"], "pricing": quote.get("pricing", {}), "version": 1})
    return public(booking) or {}


@app.get(f"{settings.api_prefix}/bookings")
async def list_bookings(user: dict[str, Any] = Depends(current_user)) -> list[dict[str, Any]]:
    query: dict[str, Any] = {}
    if user["role"] == "CUSTOMER":
        query = {"customer_id": user["_id"]}
    elif user["role"] == "DRIVER":
        query = {"driver_id": user["_id"]}
    return [public(item) for item in await store.find_many("bookings", query) if item]


@app.post(f"{settings.api_prefix}/bookings/{{booking_id}}/cancel", dependencies=[Depends(verify_access_token)])
async def cancel_booking(booking_id: str, user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
    booking = await store.find_one("bookings", {"_id": booking_id})
    if not booking or (user["role"] == "CUSTOMER" and booking["customer_id"] != user["_id"]):
        raise HTTPException(status_code=404, detail="Booking not found")
    if user["role"] not in {"CUSTOMER", "ADMIN"}:
        raise HTTPException(status_code=403, detail="Insufficient permission")
    if booking["status"] in {"TRIP_STARTED", "DESTINATION_REACHED", "COMPLETION_OTP_PENDING", "TRIP_COMPLETED", "CANCELLED", "REFUND_PENDING", "REFUNDED"}:
        raise HTTPException(status_code=409, detail="Booking can no longer be cancelled")
    paid = booking.get("payment_status") in {"PAID", "ADVANCE_PAID"}
    updated = await store.update("bookings", booking_id, {"status": "REFUND_PENDING" if paid else "CANCELLED", "payment_status": "REFUND_PENDING" if paid else booking.get("payment_status"), "version": booking.get("version", 1) + 1})
    await store.delete_many("vehicle_reservations", {"booking_id": booking_id})
    await store.delete_many("driver_reservations", {"booking_id": booking_id})
    await add_notification(booking["customer_id"], "BOOKING_CANCELLED", "Booking cancelled", f"Booking {booking['public_id']} was cancelled." + (" Your refund is being processed." if paid else ""))
    return public(updated) or {}


@app.get(f"{settings.api_prefix}/bookings/{{booking_id}}")
async def booking_detail(booking_id: str, user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
    booking = await store.find_one("bookings", {"_id": booking_id})
    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found")
    if user["role"] == "CUSTOMER" and booking["customer_id"] != user["_id"]:
        raise HTTPException(status_code=404, detail="Booking not found")
    if user["role"] == "DRIVER" and booking.get("driver_id") != user["_id"]:
        raise HTTPException(status_code=404, detail="Booking not found")
    vehicle = await store.find_one("vehicles", {"_id": booking["vehicle_id"]})
    driver = await store.find_one("users", {"_id": booking.get("driver_id")}) if booking.get("driver_id") else None
    return {**(public(booking) or {}), "vehicle": public(vehicle), "driver": public(driver)}


@app.post(f"{settings.api_prefix}/bookings/{{booking_id}}/payment-order", dependencies=[Depends(verify_access_token)])
async def payment_order(booking_id: str, user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
    booking = await store.find_one("bookings", {"_id": booking_id})
    if not booking or (user["role"] == "CUSTOMER" and booking["customer_id"] != user["_id"]):
        raise HTTPException(status_code=404, detail="Booking not found")
    test_payments_enabled = settings.app_env != "production" or settings.allow_test_payments
    existing = await store.find_one("payments", {"booking_id": booking_id})
    if existing:
        if existing.get("status") == "PAID":
            return {**(public(existing) or {}), "qr_url": None}
        amount, payment_type, platform = await payment_policy(booking)
        upi_id = platform.get("upi_id", "ridex@upi")
        stale_order = not existing.get("upi_uri") or int(existing.get("amount", 0)) != amount or int(existing.get("booking_total", 0)) != int(booking["total"]) or existing.get("payment_type") != payment_type or existing.get("upi_id") != upi_id
        if stale_order:
            order_id = f"ridex_{uuid4().hex[:16]}"
            existing = await store.update("payments", existing["_id"], {"provider_order_id": order_id, "amount": amount, "booking_total": booking["total"], "currency": booking["currency"], "status": "CREATED", "method": "UPI_QR", "payment_type": payment_type, "upi_id": upi_id, "upi_uri": upi_payment_uri(upi_id, amount, order_id), "demo": test_payments_enabled}) or existing
        return {**(public(existing) or {}), "demo": test_payments_enabled, "qr_url": f"/payments/{existing['_id']}/qr"}
    amount, payment_type, platform = await payment_policy(booking)
    order_id = f"ridex_{uuid4().hex[:16]}"
    upi_id = platform.get("upi_id", "ridex@upi")
    payment = await store.insert("payments", {"booking_id": booking_id, "provider_order_id": order_id, "amount": amount, "booking_total": booking["total"], "currency": booking["currency"], "status": "CREATED", "method": "UPI_QR", "payment_type": payment_type, "upi_id": upi_id, "upi_uri": upi_payment_uri(upi_id, amount, order_id), "demo": test_payments_enabled})
    return {**(public(payment) or {}), "qr_url": f"/payments/{payment['_id']}/qr"}


@app.get(f"{settings.api_prefix}/payments/{{payment_id}}/qr")
async def payment_qr(payment_id: str, user: dict[str, Any] = Depends(current_user)) -> StreamingResponse:
    payment = await store.find_one("payments", {"_id": payment_id})
    booking = await store.find_one("bookings", {"_id": payment.get("booking_id")}) if payment else None
    if not payment or not booking or (user["role"] == "CUSTOMER" and booking["customer_id"] != user["_id"]):
        raise HTTPException(status_code=404, detail="Payment not found")
    if payment.get("status") != "CREATED":
        raise HTTPException(status_code=410, detail="This payment QR is no longer active")
    image = qrcode.make(payment["upi_uri"])
    stream = BytesIO()
    image.save(stream, format="PNG")
    stream.seek(0)
    return StreamingResponse(stream, media_type="image/png", headers={"Cache-Control": "no-store"})


@app.post(f"{settings.api_prefix}/payments/{{payment_id}}/demo-confirm", dependencies=[Depends(verify_access_token)])
async def demo_confirm(payment_id: str, user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
    if settings.app_env == "production" and not settings.allow_test_payments:
        raise HTTPException(status_code=404, detail="Not available")
    payment = await store.find_one("payments", {"_id": payment_id})
    if not payment:
        raise HTTPException(status_code=404, detail="Payment not found")
    booking = await store.find_one("bookings", {"_id": payment["booking_id"]})
    if not booking or (user["role"] == "CUSTOMER" and booking["customer_id"] != user["_id"]):
        raise HTTPException(status_code=404, detail="Booking not found")
    updated = await confirm_payment(payment, f"pay_demo_{uuid4().hex[:12]}")
    return public(updated) or {}


@app.post(f"{settings.api_prefix}/payments/{{payment_id}}/verify", dependencies=[Depends(verify_access_token)])
async def verify_checkout_payment(payment_id: str, payload: dict[str, str], user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
    payment = await store.find_one("payments", {"_id": payment_id})
    if not payment:
        raise HTTPException(status_code=404, detail="Payment not found")
    booking = await store.find_one("bookings", {"_id": payment["booking_id"]})
    if not booking or (user["role"] == "CUSTOMER" and booking["customer_id"] != user["_id"]):
        raise HTTPException(status_code=404, detail="Booking not found")
    provider_payment_id = payload.get("razorpay_payment_id", "")
    signature = payload.get("razorpay_signature", "")
    signed = f"{payment['provider_order_id']}|{provider_payment_id}".encode()
    expected = hmac.new(settings.razorpay_key_secret.encode(), signed, sha256).hexdigest()
    if not settings.razorpay_key_secret or not hmac.compare_digest(signature, expected):
        raise HTTPException(status_code=400, detail="Invalid payment signature")
    return public(await confirm_payment(payment, provider_payment_id)) or {}


@app.post(f"{settings.api_prefix}/webhooks/razorpay")
async def razorpay_webhook(request: Request) -> dict[str, bool]:
    body = await request.body()
    signature = request.headers.get("X-Razorpay-Signature", "")
    expected = hmac.new(settings.razorpay_webhook_secret.encode(), body, sha256).hexdigest()
    if not settings.razorpay_webhook_secret or not hmac.compare_digest(signature, expected):
        raise HTTPException(status_code=400, detail="Invalid webhook signature")
    event_id = request.headers.get("X-Razorpay-Event-Id") or sha256(body).hexdigest()
    if await store.find_one("payment_webhook_events", {"provider_event_id": event_id}):
        return {"accepted": True}
    event = json.loads(body)
    await store.insert("payment_webhook_events", {"provider_event_id": event_id, "event_type": event.get("event"), "signature_valid": True, "status": "RECEIVED"})
    if event.get("event") in {"payment.captured", "order.paid"}:
        entity = event.get("payload", {}).get("payment", {}).get("entity", {})
        payment = await store.find_one("payments", {"provider_order_id": entity.get("order_id")})
        if payment:
            if entity.get("amount") != payment["amount"] * 100 or entity.get("currency") != payment["currency"]:
                raise HTTPException(status_code=400, detail="Webhook payment amount mismatch")
            await confirm_payment(payment, entity.get("id", ""))
    webhook_record = await store.find_one("payment_webhook_events", {"provider_event_id": event_id})
    if webhook_record:
        await store.update("payment_webhook_events", webhook_record["_id"], {"status": "PROCESSED"})
    return {"accepted": True}


@app.get(f"{settings.api_prefix}/notifications")
async def notifications(user: dict[str, Any] = Depends(current_user)) -> list[dict[str, Any]]:
    return [public(item) for item in await store.find_many("notifications", {"user_id": user["_id"]}) if item]


@app.post(f"{settings.api_prefix}/notifications/{{notification_id}}/read", dependencies=[Depends(verify_access_token)])
async def read_notification(notification_id: str, user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
    notification = await store.find_one("notifications", {"_id": notification_id, "user_id": user["_id"]})
    if not notification:
        raise HTTPException(status_code=404, detail="Notification not found")
    return public(await store.update("notifications", notification_id, {"read": True})) or {}


@app.get(f"{settings.api_prefix}/reviews")
async def public_reviews() -> list[dict[str, Any]]:
    return [public(item) for item in await store.find_many("reviews", {"status": "PUBLISHED"}) if item]


@app.post(f"{settings.api_prefix}/bookings/{{booking_id}}/reviews", status_code=201, dependencies=[Depends(verify_access_token)])
async def create_review(booking_id: str, payload: ReviewCreate, user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
    booking = await store.find_one("bookings", {"_id": booking_id, "customer_id": user["_id"]})
    if not booking or booking["status"] != "TRIP_COMPLETED":
        raise HTTPException(status_code=422, detail="Only completed bookings can be reviewed")
    if await store.find_one("reviews", {"booking_id": booking_id}):
        raise HTTPException(status_code=409, detail="Review already submitted")
    review = await store.insert("reviews", {"booking_id": booking_id, "customer_id": user["_id"], "driver_id": booking.get("driver_id"), "vehicle_id": booking["vehicle_id"], "rating": payload.rating, "comment": payload.comment, "status": "PUBLISHED"})
    return public(review) or {}


@app.post(f"{settings.api_prefix}/support-requests", status_code=201, dependencies=[Depends(verify_access_token)])
async def support_request(payload: dict[str, str], user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
    message = payload.get("message", "").strip()
    if len(message) < 10 or len(message) > 2000:
        raise HTTPException(status_code=422, detail="Support message must be between 10 and 2000 characters")
    ticket = await store.insert("support_requests", {"user_id": user["_id"], "booking_id": payload.get("booking_id"), "message": message, "status": "OPEN"})
    return public(ticket) or {}


@app.get(f"{settings.api_prefix}/bookings/{{booking_id}}/receipt.pdf")
async def receipt_pdf(booking_id: str, user: dict[str, Any] = Depends(current_user)) -> StreamingResponse:
    booking = await store.find_one("bookings", {"_id": booking_id})
    if not booking or (user["role"] == "CUSTOMER" and booking["customer_id"] != user["_id"]):
        raise HTTPException(status_code=404, detail="Booking not found")
    if user["role"] == "DRIVER":
        raise HTTPException(status_code=403, detail="Insufficient permission")
    customer = await store.find_one("users", {"_id": booking["customer_id"]})
    vehicle = await store.find_one("vehicles", {"_id": booking["vehicle_id"]})
    buffer = BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4
    pdf.setTitle(f"RideX Receipt {booking['public_id']}")
    pdf.setFont("Helvetica-Bold", 22)
    pdf.drawString(52, height - 65, "RideX")
    pdf.setFont("Helvetica", 10)
    pdf.drawString(52, height - 82, "Chauffeur-Driven Mobility, Bengaluru")
    pdf.line(52, height - 98, width - 52, height - 98)
    rows = [
        ("BOOKING RECEIPT", ""), ("Booking ID", booking["public_id"]),
        ("Customer", customer["name"] if customer else "Customer"),
        ("Service", booking["service_type"]), ("Pickup", booking["pickup"]),
        ("Destination", booking["destination"]), ("Date", booking["scheduled_at"]),
        ("Vehicle", vehicle["name"] if vehicle else "Assigned vehicle"),
        ("Payment status", booking["payment_status"]), ("Total paid", f"INR {booking.get('paid_amount', 0):,}"), ("Balance due", f"INR {max(0, booking['total'] - booking.get('paid_amount', 0)):,}"),
    ]
    y = height - 130
    for label, value in rows:
        pdf.setFont("Helvetica-Bold" if not value else "Helvetica", 12 if not value else 10)
        pdf.drawString(52, y, label)
        if value:
            pdf.drawRightString(width - 52, y, str(value)[:85])
        y -= 27
    pdf.line(52, y, width - 52, y)
    pdf.drawString(52, y - 28, "Cancellation policy: Refer to the policy accepted at booking.")
    pdf.drawString(52, y - 48, f"Support: {settings.smtp_from_email}")
    pdf.save()
    buffer.seek(0)
    return StreamingResponse(buffer, media_type="application/pdf", headers={"Content-Disposition": f'attachment; filename="{booking["public_id"]}-receipt.pdf"'})


@app.get(f"{settings.api_prefix}/admin/dashboard")
async def admin_dashboard(_: dict[str, str] = Depends(require_roles("ADMIN"))) -> dict[str, Any]:
    bookings = await store.find_many("bookings", limit=10_000)
    users = await store.find_many("users")
    vehicles_list = await store.find_many("vehicles")
    today = utcnow().date()
    days = [(today - timedelta(days=offset)).isoformat() for offset in range(6, -1, -1)]
    booking_counts = Counter(day_key(booking.get("created_at")) for booking in bookings)
    revenue_counts = Counter()
    for booking in bookings:
        if booking.get("payment_status") == "PAID":
            revenue_counts[day_key(booking.get("created_at"))] += booking.get("total", 0)
    service_counts = Counter(booking.get("service_type", "UNKNOWN") for booking in bookings)
    recent = sorted(bookings, key=lambda item: str(item.get("created_at", "")), reverse=True)[:5]
    recent_customers = sorted([user for user in users if user["role"] == "CUSTOMER"], key=lambda item: str(item.get("created_at", "")), reverse=True)[:5]
    driver_profiles = await store.find_many("drivers")
    return {
        "total_bookings": len(bookings),
        "today_bookings": sum(day_key(booking.get("created_at")) == today.isoformat() for booking in bookings),
        "revenue": sum(booking.get("paid_amount", booking.get("total", 0)) for booking in bookings if booking.get("payment_status") in {"PAID", "ADVANCE_PAID"}),
        "customers": sum(user["role"] == "CUSTOMER" for user in users),
        "drivers": sum(user["role"] == "DRIVER" for user in users),
        "vehicles": len(vehicles_list),
        "active_trips": sum(booking["status"] in {"DRIVER_ACCEPTED", "DRIVER_ON_THE_WAY", "DRIVER_ARRIVED", "TRIP_STARTED", "DESTINATION_REACHED", "COMPLETION_OTP_PENDING"} for booking in bookings),
        "pending_payments": sum(booking.get("payment_status") in {"PENDING", "PROCESSING"} for booking in bookings),
        "cancelled_bookings": sum(booking["status"] in {"CANCELLED", "REFUND_PENDING", "REFUNDED"} for booking in bookings),
        "active_drivers": sum(profile.get("schedule_availability", "AVAILABLE") == "AVAILABLE" for profile in driver_profiles),
        "booking_trends": [{"date": day, "count": booking_counts[day]} for day in days],
        "revenue_trends": [{"date": day, "amount": revenue_counts[day]} for day in days],
        "service_breakdown": [{"service": key, "count": value} for key, value in service_counts.items()],
        "recent_bookings": [await enrich_booking(booking) for booking in recent],
        "recent_customers": [public(user) for user in recent_customers],
    }


@app.get(f"{settings.api_prefix}/admin/users")
async def admin_users(_: dict[str, str] = Depends(require_roles("ADMIN"))) -> list[dict[str, Any]]:
    users = await store.find_many("users", limit=1000)
    bookings = await store.find_many("bookings", limit=10_000)
    reviews = await store.find_many("reviews", limit=10_000)
    return [{**(public(item) or {}), "booking_count": sum(b.get("customer_id") == item["_id"] for b in bookings), "review_count": sum(r.get("customer_id") == item["_id"] for r in reviews), "total_spent": sum(b.get("total", 0) for b in bookings if b.get("customer_id") == item["_id"] and b.get("payment_status") == "PAID")} for item in users]


@app.patch(f"{settings.api_prefix}/admin/users/{{user_id}}", dependencies=[Depends(verify_access_token)])
async def admin_update_user(user_id: str, payload: UserUpdate, admin: dict[str, str] = Depends(require_roles("ADMIN"))) -> dict[str, Any]:
    changes = payload.model_dump(exclude_none=True)
    updated = await store.update("users", user_id, changes)
    if not updated:
        raise HTTPException(status_code=404, detail="User not found")
    await audit_admin(admin["sub"], "USER_UPDATED", "user", user_id, changes)
    return public(updated) or {}


@app.get(f"{settings.api_prefix}/admin/drivers")
async def admin_drivers(_: dict[str, str] = Depends(require_roles("ADMIN"))) -> list[dict[str, Any]]:
    users = await store.find_many("users", {"role": "DRIVER"})
    result = []
    for user in users:
        profile = await store.find_one("drivers", {"user_id": user["_id"]})
        result.append({**(public(user) or {}), "profile": public(profile)})
    return result


@app.post(f"{settings.api_prefix}/admin/drivers", status_code=201, dependencies=[Depends(verify_access_token)])
async def admin_create_driver(payload: DriverCreate, admin: dict[str, str] = Depends(require_roles("ADMIN"))) -> dict[str, Any]:
    if await store.find_one("users", {"email": payload.email.lower()}):
        raise HTTPException(status_code=409, detail="Email already exists")
    password_digest, password_salt = hash_password(payload.password)
    user = await store.insert("users", {"name": payload.name, "email": payload.email.lower(), "phone": payload.phone, "role": "DRIVER", "status": "ACTIVE", "password_hash": password_digest, "password_salt": password_salt})
    profile = await store.insert("drivers", {"user_id": user["_id"], "schedule_availability": "AVAILABLE", "online_status": "OFFLINE", "verification_status": "PENDING", "license_number": payload.license_number, "license_expiry": payload.license_expiry, "rating": 0, "earnings": 0})
    await audit_admin(admin["sub"], "DRIVER_CREATED", "driver", user["_id"])
    return {**(public(user) or {}), "profile": public(profile)}


@app.patch(f"{settings.api_prefix}/admin/drivers/{{driver_id}}", dependencies=[Depends(verify_access_token)])
async def admin_update_driver(driver_id: str, payload: DriverUpdate, admin: dict[str, str] = Depends(require_roles("ADMIN"))) -> dict[str, Any]:
    user = await store.find_one("users", {"_id": driver_id, "role": "DRIVER"})
    if not user:
        raise HTTPException(status_code=404, detail="Driver not found")
    changes = payload.model_dump(exclude_none=True)
    user_status = changes.pop("status", None)
    if user_status:
        user = await store.update("users", driver_id, {"status": user_status}) or user
    profile = await store.find_one("drivers", {"user_id": driver_id})
    if changes.get("verification_status") == "VERIFIED" and (not profile or profile.get("documents_status") != "SUBMITTED"):
        raise HTTPException(status_code=409, detail="Driver must submit all required documents before approval")
    if changes.get("verification_status") == "VERIFIED":
        changes["documents_status"] = "APPROVED"
    elif changes.get("verification_status") == "REJECTED":
        changes["documents_status"] = "REJECTED"
    assigned_vehicle_id = changes.get("assigned_vehicle_id")
    if assigned_vehicle_id:
        if not await store.find_one("vehicles", {"_id": assigned_vehicle_id}):
            raise HTTPException(status_code=404, detail="Vehicle not found")
        existing_assignment = await store.find_one("drivers", {"assigned_vehicle_id": assigned_vehicle_id})
        if existing_assignment and existing_assignment.get("user_id") != driver_id:
            raise HTTPException(status_code=409, detail="Vehicle is already assigned to another driver")
    if changes and profile:
        profile = await store.update("drivers", profile["_id"], changes)
    if payload.verification_status in {"VERIFIED", "REJECTED"}:
        approved = payload.verification_status == "VERIFIED"
        await add_notification(driver_id, "DRIVER_APPROVAL", "Driver application approved" if approved else "Driver application needs attention", "Your RideX driver account is approved. You can now receive and accept trips." if approved else "Your driver documents were not approved. Please upload clear replacement documents.")
    await audit_admin(admin["sub"], "DRIVER_UPDATED", "driver", driver_id, payload.model_dump(exclude_none=True))
    return {**(public(user) or {}), "profile": public(profile)}


@app.get(f"{settings.api_prefix}/admin/bookings")
async def admin_bookings(_: dict[str, str] = Depends(require_roles("ADMIN"))) -> list[dict[str, Any]]:
    return [await enrich_booking(item) for item in await store.find_many("bookings", limit=1000)]


@app.get(f"{settings.api_prefix}/admin/bookings/{{booking_id}}")
async def admin_booking_detail(booking_id: str, _: dict[str, str] = Depends(require_roles("ADMIN"))) -> dict[str, Any]:
    booking = await store.find_one("bookings", {"_id": booking_id})
    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found")
    events = [public(item) for item in await store.find_many("trip_events", {"booking_id": booking_id})]
    payment = public(await store.find_one("payments", {"booking_id": booking_id}))
    return {**(await enrich_booking(booking)), "events": events, "payment": payment}


@app.get(f"{settings.api_prefix}/admin/payments")
async def admin_payments(_: dict[str, str] = Depends(require_roles("ADMIN"))) -> list[dict[str, Any]]:
    payments = await store.find_many("payments", limit=500)
    result = []
    for payment in payments:
        booking = await store.find_one("bookings", {"_id": payment["booking_id"]})
        customer = await store.find_one("users", {"_id": booking["customer_id"]}) if booking else None
        result.append({
            **(public(payment) or {}),
            "booking_public_id": booking.get("public_id") if booking else None,
            "customer_name": customer.get("name") if customer else None,
            "service_type": booking.get("service_type") if booking else None,
            "booking_total": booking.get("total", payment.get("booking_total", 0)) if booking else payment.get("booking_total", 0),
            "paid_amount": booking.get("paid_amount", 0) if booking else 0,
            "driver_collected_amount": booking.get("driver_collected_amount", 0) if booking else 0,
            "balance_due": booking.get("balance_due", payment.get("booking_total", 0)) if booking else payment.get("booking_total", 0),
            "balance_payment_method": booking.get("balance_payment_method") if booking else None,
        })
    return result


@app.get(f"{settings.api_prefix}/admin/vehicles")
async def admin_vehicles(_: dict[str, str] = Depends(require_roles("ADMIN"))) -> list[dict[str, Any]]:
    return [public_vehicle(item, public) for item in await store.find_many("vehicles", limit=1000)]


@app.post(f"{settings.api_prefix}/admin/vehicles", status_code=201, dependencies=[Depends(verify_access_token)])
async def admin_create_vehicle(payload: VehicleInput, admin: dict[str, str] = Depends(require_roles("ADMIN"))) -> dict[str, Any]:
    if await store.find_one("vehicles", {"registration_number": payload.registration_number}):
        raise HTTPException(status_code=409, detail="Vehicle number is already registered")
    vehicle = await store.insert("vehicles", {**payload.model_dump(), "rating": 5.0, "amenities": []})
    await audit_admin(admin["sub"], "VEHICLE_CREATED", "vehicle", vehicle["_id"])
    return public(vehicle) or {}


@app.patch(f"{settings.api_prefix}/admin/vehicles/{{vehicle_id}}", dependencies=[Depends(verify_access_token)])
async def admin_update_vehicle(vehicle_id: str, payload: VehicleUpdate, admin: dict[str, str] = Depends(require_roles("ADMIN"))) -> dict[str, Any]:
    changes = payload.model_dump(exclude_none=True)
    if changes.get("registration_number"):
        duplicate = await store.find_one("vehicles", {"registration_number": changes["registration_number"]})
        if duplicate and duplicate["_id"] != vehicle_id:
            raise HTTPException(status_code=409, detail="Vehicle number is already registered")
    updated = await store.update("vehicles", vehicle_id, changes)
    if not updated:
        raise HTTPException(status_code=404, detail="Vehicle not found")
    await audit_admin(admin["sub"], "VEHICLE_UPDATED", "vehicle", vehicle_id, changes)
    return public(updated) or {}


@app.post(f"{settings.api_prefix}/admin/vehicles/{{vehicle_id}}/assign-driver", dependencies=[Depends(verify_access_token)])
async def assign_vehicle_driver(vehicle_id: str, payload: VehicleDriverAssignment, admin: dict[str, str] = Depends(require_roles("ADMIN"))) -> dict[str, Any]:
    vehicle = await store.find_one("vehicles", {"_id": vehicle_id})
    if not vehicle:
        raise HTTPException(status_code=404, detail="Vehicle not found")
    active_states = ["DRIVER_ASSIGNED", "DRIVER_ACCEPTED", "DRIVER_ON_THE_WAY", "DRIVER_ARRIVED", "TRIP_STARTED", "DESTINATION_REACHED", "COMPLETION_OTP_PENDING"]
    current_profile = await store.find_one("drivers", {"assigned_vehicle_id": vehicle_id})
    if current_profile and current_profile.get("user_id") != payload.driver_id:
        active_trip = await store.find_one("bookings", {"driver_id": current_profile["user_id"], "status": {"$in": active_states}})
        if active_trip:
            raise HTTPException(status_code=409, detail="The currently assigned driver has an active trip")
        await store.update("drivers", current_profile["_id"], {"assigned_vehicle_id": None})
    assigned_driver = None
    if payload.driver_id:
        assigned_driver = await store.find_one("users", {"_id": payload.driver_id, "role": "DRIVER", "status": "ACTIVE"})
        profile = await store.find_one("drivers", {"user_id": payload.driver_id})
        if not assigned_driver or not profile or profile.get("verification_status") != "VERIFIED":
            raise HTTPException(status_code=409, detail="Only an active approved driver can be assigned")
        active_trip = await store.find_one("bookings", {"driver_id": payload.driver_id, "status": {"$in": active_states}})
        if active_trip and profile.get("assigned_vehicle_id") not in {None, vehicle_id}:
            raise HTTPException(status_code=409, detail="Driver has an active trip with another vehicle")
        await store.update("drivers", profile["_id"], {"assigned_vehicle_id": vehicle_id})
    await audit_admin(admin["sub"], "VEHICLE_DRIVER_ASSIGNED", "vehicle", vehicle_id, {"driver_id": payload.driver_id})
    return {"vehicle_id": vehicle_id, "assigned_driver": public(assigned_driver)}


@app.delete(f"{settings.api_prefix}/admin/vehicles/{{vehicle_id}}", dependencies=[Depends(verify_access_token)])
async def admin_delete_vehicle(vehicle_id: str, admin: dict[str, str] = Depends(require_roles("ADMIN"))) -> dict[str, str]:
    vehicle = await store.find_one("vehicles", {"_id": vehicle_id})
    if not vehicle:
        raise HTTPException(status_code=404, detail="Vehicle not found")
    active = await store.find_one("bookings", {"vehicle_id": vehicle_id, "status": {"$in": ["PENDING_PAYMENT", "CONFIRMED", "DRIVER_ASSIGNED", "DRIVER_ACCEPTED", "DRIVER_ON_THE_WAY", "DRIVER_ARRIVED", "TRIP_STARTED", "DESTINATION_REACHED", "COMPLETION_OTP_PENDING"]}})
    if active:
        raise HTTPException(status_code=409, detail="Vehicle has an active or upcoming booking and cannot be deleted")
    await store.update("vehicles", vehicle_id, {"status": "INACTIVE", "archived_at": utcnow()})
    await audit_admin(admin["sub"], "VEHICLE_ARCHIVED", "vehicle", vehicle_id)
    return {"message": "Vehicle deleted"}


@app.get(f"{settings.api_prefix}/admin/pricing-rules")
async def admin_pricing_rules(_: dict[str, str] = Depends(require_roles("ADMIN"))) -> list[dict[str, Any]]:
    return [public(item) for item in await store.find_many("pricing_rules", limit=1000) if item]


@app.post(f"{settings.api_prefix}/admin/pricing-rules", status_code=201, dependencies=[Depends(verify_access_token)])
async def admin_create_pricing_rule(payload: PricingRuleInput, admin: dict[str, str] = Depends(require_roles("ADMIN"))) -> dict[str, Any]:
    rule = await store.insert("pricing_rules", {**payload.model_dump(mode="json"), "version": 1})
    await audit_admin(admin["sub"], "PRICING_RULE_CREATED", "pricing_rule", rule["_id"])
    return public(rule) or {}


@app.patch(f"{settings.api_prefix}/admin/pricing-rules/{{rule_id}}", dependencies=[Depends(verify_access_token)])
async def admin_update_pricing_rule(rule_id: str, payload: PricingRuleInput, admin: dict[str, str] = Depends(require_roles("ADMIN"))) -> dict[str, Any]:
    current = await store.find_one("pricing_rules", {"_id": rule_id})
    if not current:
        raise HTTPException(status_code=404, detail="Pricing rule not found")
    updated = await store.update("pricing_rules", rule_id, {**payload.model_dump(mode="json"), "version": current.get("version", 1) + 1})
    await audit_admin(admin["sub"], "PRICING_RULE_UPDATED", "pricing_rule", rule_id)
    return public(updated) or {}


@app.get(f"{settings.api_prefix}/admin/coupons")
async def admin_coupons(_: dict[str, str] = Depends(require_roles("ADMIN"))) -> list[dict[str, Any]]:
    return [public(item) for item in await store.find_many("coupons", limit=1000) if item]


@app.get(f"{settings.api_prefix}/coupons/public")
async def public_coupons() -> list[dict[str, Any]]:
    now = utcnow()
    coupons = await store.find_many("coupons", {"scope": "PUBLIC", "status": "ACTIVE"}, limit=100)
    result = []
    for item in coupons:
        valid_from = as_utc_datetime(item["valid_from"]) if item.get("valid_from") else None
        valid_to = as_utc_datetime(item["valid_to"]) if item.get("valid_to") else None
        if valid_from and valid_to and valid_from <= now <= valid_to and item.get("used_count", 0) < item.get("usage_limit", 1):
            result.append({"code": item["code"], "discount_type": item["discount_type"], "value": item["value"], "minimum_booking": item["minimum_booking"], "maximum_discount": item["maximum_discount"], "valid_to": item["valid_to"]})
    return result


@app.post(f"{settings.api_prefix}/admin/coupons", status_code=201, dependencies=[Depends(verify_access_token)])
async def admin_create_coupon(payload: CouponInput, admin: dict[str, str] = Depends(require_roles("ADMIN"))) -> dict[str, Any]:
    data = payload.model_dump()
    data["code"] = data["code"].upper()
    if data["scope"] == "PERSONAL":
        customer = await store.find_one("users", {"_id": data["customer_id"], "role": "CUSTOMER", "status": "ACTIVE"})
        if not customer:
            raise HTTPException(status_code=404, detail="Active customer not found")
        data["usage_limit"] = 1
    data["used_count"] = 0
    try:
        coupon = await store.insert("coupons", data)
    except DuplicateKeyError as exc:
        raise HTTPException(status_code=409, detail="Coupon code already exists") from exc
    await audit_admin(admin["sub"], "COUPON_CREATED", "coupon", coupon["_id"])
    return public(coupon) or {}


@app.patch(f"{settings.api_prefix}/admin/coupons/{{coupon_id}}", dependencies=[Depends(verify_access_token)])
async def admin_update_coupon(coupon_id: str, payload: CouponInput, admin: dict[str, str] = Depends(require_roles("ADMIN"))) -> dict[str, Any]:
    changes = {**payload.model_dump(), "code": payload.code.upper()}
    if changes["scope"] == "PERSONAL":
        customer = await store.find_one("users", {"_id": changes["customer_id"], "role": "CUSTOMER", "status": "ACTIVE"})
        if not customer:
            raise HTTPException(status_code=404, detail="Active customer not found")
        changes["usage_limit"] = 1
    updated = await store.update("coupons", coupon_id, changes)
    if not updated:
        raise HTTPException(status_code=404, detail="Coupon not found")
    await audit_admin(admin["sub"], "COUPON_UPDATED", "coupon", coupon_id)
    return public(updated) or {}


@app.get(f"{settings.api_prefix}/admin/reviews")
async def admin_reviews(_: dict[str, str] = Depends(require_roles("ADMIN"))) -> list[dict[str, Any]]:
    reviews = await store.find_many("reviews", limit=1000)
    result = []
    for review in reviews:
        customer = await store.find_one("users", {"_id": review.get("customer_id")})
        booking = await store.find_one("bookings", {"_id": review.get("booking_id")})
        result.append({**(public(review) or {}), "customer_name": customer.get("name") if customer else None, "booking_public_id": booking.get("public_id") if booking else None})
    return result


@app.patch(f"{settings.api_prefix}/admin/reviews/{{review_id}}", dependencies=[Depends(verify_access_token)])
async def admin_moderate_review(review_id: str, payload: ReviewModeration, admin: dict[str, str] = Depends(require_roles("ADMIN"))) -> dict[str, Any]:
    updated = await store.update("reviews", review_id, payload.model_dump())
    if not updated:
        raise HTTPException(status_code=404, detail="Review not found")
    await audit_admin(admin["sub"], "REVIEW_MODERATED", "review", review_id, payload.model_dump())
    return public(updated) or {}


@app.get(f"{settings.api_prefix}/admin/notifications")
async def admin_notifications(_: dict[str, str] = Depends(require_roles("ADMIN"))) -> list[dict[str, Any]]:
    notifications = await store.find_many("notifications", limit=1000)
    result = []
    for notification in notifications:
        recipient = await store.find_one("users", {"_id": notification.get("user_id")})
        result.append({**(public(notification) or {}), "recipient_name": recipient.get("name") if recipient else None, "recipient_email": recipient.get("email") if recipient else None})
    return result


@app.get(f"{settings.api_prefix}/admin/email-deliveries")
async def admin_email_deliveries(_: dict[str, str] = Depends(require_roles("ADMIN"))) -> list[dict[str, Any]]:
    deliveries = await store.find_many("email_outbox", limit=1000)
    safe = []
    for delivery in sorted(deliveries, key=lambda item: str(item.get("created_at", "")), reverse=True):
        item = public(delivery) or {}
        item.pop("body", None)
        item["recipient_domain"] = item.get("original_recipient", "").partition("@")[2]
        item["delivery_note"] = "SMTP acceptance does not confirm final inbox delivery." if item.get("status") == "SMTP_ACCEPTED" else None
        safe.append(item)
    return safe


@app.post(f"{settings.api_prefix}/admin/email-deliveries/{{delivery_id}}/retry", dependencies=[Depends(verify_access_token)])
async def retry_email_delivery(delivery_id: str, admin: dict[str, str] = Depends(require_roles("ADMIN"))) -> dict[str, Any]:
    updated = await email_delivery.retry(delivery_id)
    if not updated:
        raise HTTPException(status_code=404, detail="Email delivery not found")
    await audit_admin(admin["sub"], "EMAIL_RETRY_REQUESTED", "email_delivery", delivery_id)
    return public(updated) or {}


@app.get(f"{settings.api_prefix}/admin/support-requests")
async def admin_support_requests(_: dict[str, str] = Depends(require_roles("ADMIN"))) -> list[dict[str, Any]]:
    tickets = await store.find_many("support_requests", limit=1000)
    result = []
    for ticket in tickets:
        requester = await store.find_one("users", {"_id": ticket.get("user_id")})
        result.append({**(public(ticket) or {}), "requester": public(requester)})
    return result


@app.patch(f"{settings.api_prefix}/admin/support-requests/{{ticket_id}}", dependencies=[Depends(verify_access_token)])
async def admin_update_support_request(ticket_id: str, payload: dict[str, str], admin: dict[str, str] = Depends(require_roles("ADMIN"))) -> dict[str, Any]:
    ticket_status = payload.get("status")
    if ticket_status not in {"OPEN", "IN_PROGRESS", "RESOLVED"}:
        raise HTTPException(status_code=422, detail="Invalid support status")
    updated = await store.update("support_requests", ticket_id, {"status": ticket_status})
    if not updated:
        raise HTTPException(status_code=404, detail="Support request not found")
    await audit_admin(admin["sub"], "SUPPORT_UPDATED", "support_request", ticket_id, {"status": ticket_status})
    return public(updated) or {}


@app.get(f"{settings.api_prefix}/admin/reports/summary")
async def admin_reports_summary(_: dict[str, str] = Depends(require_roles("ADMIN"))) -> dict[str, Any]:
    bookings = await store.find_many("bookings", limit=10_000)
    users = await store.find_many("users", limit=10_000)
    vehicles = await store.find_many("vehicles", limit=10_000)
    reviews = await store.find_many("reviews", limit=10_000)
    service_counts = Counter(booking.get("service_type", "UNKNOWN") for booking in bookings)
    vehicle_counts = Counter(booking.get("vehicle_id") for booking in bookings)
    customer_spend = Counter()
    for booking in bookings:
        if booking.get("payment_status") in {"PAID", "ADVANCE_PAID"}:
            customer_spend[booking.get("customer_id")] += booking.get("paid_amount", booking.get("total", 0))
    return {
        "service_breakdown": [{"label": key, "value": value} for key, value in service_counts.items()],
        "status_breakdown": [{"label": key, "value": value} for key, value in Counter(booking.get("status") for booking in bookings).items()],
        "top_vehicles": [{"vehicle": next((v.get("name") for v in vehicles if v["_id"] == vehicle_id), "Unknown"), "bookings": count} for vehicle_id, count in vehicle_counts.most_common(5)],
        "top_customers": [{"customer": next((u.get("name") for u in users if u["_id"] == customer_id), "Unknown"), "spent": spent} for customer_id, spent in customer_spend.most_common(5)],
        "average_rating": round(sum(review.get("rating", 0) for review in reviews) / len(reviews), 2) if reviews else 0,
        "total_revenue": sum(customer_spend.values()),
        "total_bookings": len(bookings),
    }


@app.get(f"{settings.api_prefix}/admin/settings")
async def admin_get_settings(_: dict[str, str] = Depends(require_roles("ADMIN"))) -> dict[str, Any]:
    current = await store.find_one("platform_settings", {"_id": "global"})
    if not current:
        current = await store.insert("platform_settings", {"_id": "global", "platform_name": "RideX", "support_email": settings.smtp_from_email, "support_phone": "+91 800 123 4567", "cancellation_hours": 2, "cancellation_fee_percent": 0, "google_review_url": "https://www.google.com/maps", "maintenance_mode": False, "upi_id": "ridex@upi", "standard_advance_type": "PERCENTAGE", "standard_advance_value": 25, "airport_advance_type": "PERCENTAGE", "airport_advance_value": 25, "outstation_advance_type": "PERCENTAGE", "outstation_advance_value": 30})
    defaults = {"upi_id": "ridex@upi", "standard_advance_type": "PERCENTAGE", "standard_advance_value": 25, "airport_advance_type": "PERCENTAGE", "airport_advance_value": 25, "outstation_advance_type": "PERCENTAGE", "outstation_advance_value": 30}
    return {**defaults, **(public(current) or {}), "database": "mongodb-atlas" if not settings.demo_mode else "memory-demo", "email_configured": bool(settings.smtp_host and settings.smtp_password), "payments_configured": bool((current or {}).get("upi_id") or settings.razorpay_key_id)}


@app.patch(f"{settings.api_prefix}/admin/settings", dependencies=[Depends(verify_access_token)])
async def admin_update_settings(payload: PlatformSettingsUpdate, admin: dict[str, str] = Depends(require_roles("ADMIN"))) -> dict[str, Any]:
    changes = payload.model_dump(exclude_none=True, mode="json")
    current = await store.find_one("platform_settings", {"_id": "global"})
    updated = await store.update("platform_settings", "global", changes) if current else await store.insert("platform_settings", {"_id": "global", **changes})
    await audit_admin(admin["sub"], "SETTINGS_UPDATED", "platform_settings", "global", changes)
    return public(updated) or {}


@app.get(f"{settings.api_prefix}/admin/audit-logs")
async def admin_audit_logs(_: dict[str, str] = Depends(require_roles("ADMIN"))) -> list[dict[str, Any]]:
    logs = await store.find_many("audit_logs", limit=1000)
    return [public(item) for item in sorted(logs, key=lambda row: str(row.get("created_at", "")), reverse=True) if item]


@app.get(f"{settings.api_prefix}/admin/database/collections")
async def admin_database_collections(_: dict[str, str] = Depends(require_roles("ADMIN"))) -> list[dict[str, Any]]:
    return [{"name": collection, "count": await store.count(collection), "cleanup_enabled": collection in DATABASE_CLEANUP_COLLECTIONS} for collection in store.collection_names]


@app.get(f"{settings.api_prefix}/admin/database/{{collection}}")
async def admin_database_records(collection: str, limit: int = 100, _: dict[str, str] = Depends(require_roles("ADMIN"))) -> list[dict[str, Any]]:
    if collection not in store.collection_names:
        raise HTTPException(status_code=404, detail="Collection not found")
    records = await store.find_many(collection, limit=min(max(limit, 1), 200))
    return [{"record": safe_database_record(item), "deletable": database_record_deletable(collection, item)} for item in records]


@app.delete(f"{settings.api_prefix}/admin/database/{{collection}}/{{record_id}}", dependencies=[Depends(verify_access_token)])
async def admin_delete_database_record(collection: str, record_id: str, admin: dict[str, str] = Depends(require_roles("ADMIN"))) -> dict[str, str]:
    if collection not in DATABASE_CLEANUP_COLLECTIONS:
        raise HTTPException(status_code=403, detail="This collection is protected from direct deletion")
    records = await store.find_many(collection, limit=10_000)
    record = next((item for item in records if str(item.get("_id")) == record_id), None)
    if not record:
        raise HTTPException(status_code=404, detail="Record not found")
    if not database_record_deletable(collection, record):
        raise HTTPException(status_code=409, detail="This record is still operational and cannot be deleted")
    await store.delete_many(collection, {"_id": record["_id"]})
    await audit_admin(admin["sub"], "DATABASE_RECORD_DELETED", collection, record_id)
    return {"message": "Record deleted"}


@app.delete(f"{settings.api_prefix}/admin/database/{{collection}}", dependencies=[Depends(verify_access_token)])
async def admin_cleanup_database_collection(collection: str, admin: dict[str, str] = Depends(require_roles("ADMIN"))) -> dict[str, Any]:
    if collection not in DATABASE_CLEANUP_COLLECTIONS:
        raise HTTPException(status_code=403, detail="This collection is protected from direct cleanup")
    records = await store.find_many(collection, limit=10_000)
    deletable = [item for item in records if database_record_deletable(collection, item)]
    for item in deletable:
        await store.delete_many(collection, {"_id": item["_id"]})
    await audit_admin(admin["sub"], "DATABASE_COLLECTION_CLEANED", collection, collection, {"deleted": len(deletable)})
    return {"message": "Eligible records deleted", "deleted": len(deletable)}


@app.post(f"{settings.api_prefix}/admin/bookings/{{booking_id}}/assign-driver", dependencies=[Depends(verify_access_token)])
async def assign_driver(booking_id: str, payload: DriverAssignment, admin: dict[str, str] = Depends(require_roles("ADMIN"))) -> dict[str, Any]:
    booking = await store.find_one("bookings", {"_id": booking_id})
    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found")
    if booking["payment_status"] not in {"PAID", "ADVANCE_PAID"}:
        raise HTTPException(status_code=422, detail="Driver can only be assigned after payment")
    if booking["status"] not in {"CONFIRMED", "DRIVER_ASSIGNED", "DRIVER_ACCEPTED"}:
        raise HTTPException(status_code=409, detail="Driver can no longer be changed for this booking")
    updated, reason = await assign_booking_driver(booking, payload.driver_id, "ADMIN_ASSIGNED", admin["sub"])
    if not updated:
        raise HTTPException(status_code=409, detail=reason or "Driver is unavailable")
    return await enrich_booking(updated)


@app.get(f"{settings.api_prefix}/admin/bookings/{{booking_id}}/available-drivers")
async def available_booking_drivers(booking_id: str, _: dict[str, str] = Depends(require_roles("ADMIN"))) -> list[dict[str, Any]]:
    booking = await store.find_one("bookings", {"_id": booking_id})
    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found")
    result = []
    for user in await store.find_many("users", {"role": "DRIVER"}, limit=1000):
        _, profile, reason = await driver_assignment_eligibility(user["_id"], booking)
        result.append({**(public(user) or {}), "profile": public(profile), "available": reason is None, "unavailable_reason": reason})
    return result


@app.get(f"{settings.api_prefix}/driver/dashboard")
async def driver_dashboard(driver: dict[str, str] = Depends(require_active_driver)) -> dict[str, Any]:
    trips = await store.find_many("bookings", {"driver_id": driver["sub"]})
    profile = await store.find_one("drivers", {"user_id": driver["sub"]})
    user = await store.find_one("users", {"_id": driver["sub"]})
    completed_trips = [trip for trip in trips if trip["status"] == "TRIP_COMPLETED"]
    return {"driver": public(user), "today": len(trips) if profile and profile.get("verification_status") == "VERIFIED" else 0, "upcoming": sum(t["status"] in {"DRIVER_ASSIGNED", "DRIVER_ACCEPTED"} for t in trips) if profile and profile.get("verification_status") == "VERIFIED" else 0, "completed": len(completed_trips), "online_status": profile.get("online_status", "OFFLINE") if profile else "OFFLINE", "schedule_availability": profile.get("schedule_availability", "AVAILABLE") if profile else "UNAVAILABLE", "earnings": sum(int(trip.get("total", 0)) for trip in completed_trips), "latitude": profile.get("latitude") if profile else None, "longitude": profile.get("longitude") if profile else None, "last_seen": profile.get("last_seen") if profile else None, "verification_status": profile.get("verification_status", "PENDING") if profile else "PENDING", "documents_status": profile.get("documents_status", "INCOMPLETE") if profile else "INCOMPLETE"}


@app.get(f"{settings.api_prefix}/driver/trips")
async def driver_trips(driver: dict[str, str] = Depends(require_verified_driver)) -> list[dict[str, Any]]:
    return [public(item) for item in await store.find_many("bookings", {"driver_id": driver["sub"]}) if item]


@app.patch(f"{settings.api_prefix}/driver/availability", dependencies=[Depends(verify_access_token)])
async def driver_availability(payload: dict[str, str], driver: dict[str, str] = Depends(require_verified_driver)) -> dict[str, Any]:
    online_status = payload.get("online_status") or ("ONLINE" if payload.get("availability") == "AVAILABLE" else payload.get("availability"))
    if online_status not in {"ONLINE", "OFFLINE"}:
        raise HTTPException(status_code=422, detail="Online status must be ONLINE or OFFLINE")
    profile = await store.find_one("drivers", {"user_id": driver["sub"]})
    if not profile:
        raise HTTPException(status_code=404, detail="Driver profile not found")
    changes: dict[str, Any] = {"online_status": online_status, "last_seen": utcnow()}
    if online_status == "ONLINE":
        try:
            changes["latitude"] = float(payload["latitude"])
            changes["longitude"] = float(payload["longitude"])
        except (KeyError, TypeError, ValueError) as exc:
            raise HTTPException(status_code=422, detail="Current location is required to go online") from exc
    return public(await store.update("drivers", profile["_id"], changes)) or {}


TRIP_TRANSITIONS = {"accept": ("DRIVER_ASSIGNED", "DRIVER_ACCEPTED"), "on-the-way": ("DRIVER_ACCEPTED", "DRIVER_ON_THE_WAY")}


@app.post(f"{settings.api_prefix}/driver/trips/{{booking_id}}/{{command}}", dependencies=[Depends(verify_access_token)])
async def transition_trip(booking_id: str, command: str, payload: TripTransition, driver: dict[str, str] = Depends(require_verified_driver)) -> dict[str, Any]:
    if command not in TRIP_TRANSITIONS:
        raise HTTPException(status_code=404, detail="Unknown trip command")
    existing = await store.find_one("trip_events", {"booking_id": booking_id, "action_id": payload.action_id})
    if existing:
        booking = await store.find_one("bookings", {"_id": booking_id})
        return public(booking) or {}
    booking = await store.find_one("bookings", {"_id": booking_id, "driver_id": driver["sub"]})
    expected, target = TRIP_TRANSITIONS[command]
    if not booking:
        raise HTTPException(status_code=404, detail="Trip not found")
    if booking["status"] != expected:
        raise HTTPException(status_code=409, detail=f"Trip must be {expected} before {command}")
    await store.insert("trip_events", {"booking_id": booking_id, "driver_id": driver["sub"], "action_id": payload.action_id, "from_status": expected, "to_status": target, "occurred_at": utcnow()})
    updated = await store.update("bookings", booking_id, {"status": target, "version": booking.get("version", 1) + 1})
    await add_notification(booking["customer_id"], target, target.replace("_", " ").title(), f"Booking {booking['public_id']} is now {target.replace('_', ' ').lower()}.")
    return public(updated) or {}
