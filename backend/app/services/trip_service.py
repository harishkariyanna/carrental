import base64
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from math import asin, ceil, cos, radians, sin, sqrt
from secrets import randbelow
from typing import Any

from cryptography.fernet import Fernet
from fastapi import HTTPException

from ..config import Settings
from ..core.enums import BookingStatus, ExtraChargeType, OtpPurpose, Role
from ..repositories.trip_repository import TripRepository
from ..security import hash_password, verify_password
from .live_location_service import live_locations

ARRIVAL_RADIUS_METERS = 200
COMPLETION_RADIUS_METERS = 200


def distance_meters(first_lat: float, first_lng: float, second_lat: float, second_lng: float) -> float:
    earth_radius = 6_371_000
    lat_delta = radians(second_lat - first_lat)
    lng_delta = radians(second_lng - first_lng)
    first = radians(first_lat)
    second = radians(second_lat)
    value = sin(lat_delta / 2) ** 2 + cos(first) * cos(second) * sin(lng_delta / 2) ** 2
    return 2 * earth_radius * asin(sqrt(value))


def as_utc(value: datetime | str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00")) if isinstance(value, str) else value
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)


class TripService:
    def __init__(self, repository: TripRepository, settings: Settings):
        self.repository = repository
        key = base64.urlsafe_b64encode(sha256(settings.secret_key.encode()).digest())
        self.cipher = Fernet(key)

    async def update_location(self, booking_id: str, driver_id: str, latitude: float, longitude: float, accuracy: float | None) -> dict[str, Any]:
        booking = await self._assigned_booking(booking_id, driver_id)
        if booking["status"] not in {BookingStatus.DRIVER_ACCEPTED, BookingStatus.DRIVER_ON_THE_WAY, BookingStatus.DRIVER_ARRIVED, BookingStatus.TRIP_STARTED, BookingStatus.DESTINATION_REACHED, BookingStatus.COMPLETION_OTP_PENDING}:
            raise HTTPException(status_code=409, detail="Location updates are only accepted during an active assignment")
        location = live_locations.update(booking_id, driver_id, latitude, longitude, accuracy)
        response = {"latitude": latitude, "longitude": longitude, "accuracy": accuracy, "last_seen": location["last_seen"], "arrived": False}
        if booking["status"] == BookingStatus.DRIVER_ON_THE_WAY and booking.get("pickup_latitude") is not None and booking.get("pickup_longitude") is not None:
            distance = distance_meters(latitude, longitude, float(booking["pickup_latitude"]), float(booking["pickup_longitude"]))
            if distance <= ARRIVAL_RADIUS_METERS:
                await self._mark_arrived(booking)
                response["arrived"] = True
        return response

    async def arrived(self, booking_id: str, driver_id: str) -> dict[str, Any]:
        booking = await self._assigned_booking(booking_id, driver_id)
        if booking["status"] != BookingStatus.DRIVER_ON_THE_WAY:
            raise HTTPException(status_code=409, detail="Driver must be on the way before arrival")
        location = live_locations.get(booking_id)
        if booking.get("pickup_latitude") is not None:
            if not location:
                raise HTTPException(status_code=409, detail="Current location is required to confirm arrival")
            distance = distance_meters(float(location["latitude"]), float(location["longitude"]), float(booking["pickup_latitude"]), float(booking["pickup_longitude"]))
            if distance > ARRIVAL_RADIUS_METERS:
                raise HTTPException(status_code=409, detail=f"Driver must be within {ARRIVAL_RADIUS_METERS} metres of pickup to confirm arrival")
        return await self._mark_arrived(booking)

    async def _mark_arrived(self, booking: dict[str, Any]) -> dict[str, Any]:
        updated = await self.repository.update_booking(booking["_id"], {"status": BookingStatus.DRIVER_ARRIVED, "driver_arrived_at": datetime.now(UTC), "version": booking.get("version", 1) + 1})
        await self.create_otp(booking, OtpPurpose.START, Role.CUSTOMER)
        await self.repository.add_notification(booking["customer_id"], "DRIVER_ARRIVED", "Your driver has arrived", f"Your driver is within {ARRIVAL_RADIUS_METERS} metres of the pickup for booking {booking['public_id']}.")
        return updated or booking

    async def start_waiting(self, booking_id: str, driver_id: str) -> dict[str, Any]:
        booking = await self._assigned_booking(booking_id, driver_id)
        if booking["status"] != BookingStatus.DRIVER_ARRIVED or booking.get("service_type") != "NORMAL":
            raise HTTPException(status_code=409, detail="Local waiting can start only after arrival on a pickup and drop trip")
        if booking.get("waiting_started_at"):
            return booking
        return await self.repository.update_booking(booking_id, {"waiting_started_at": datetime.now(UTC), "version": booking.get("version", 1) + 1}) or booking

    async def create_otp(self, booking: dict[str, Any], purpose: OtpPurpose, target_role: Role) -> None:
        code = f"{randbelow(1_000_000):06d}"
        digest, salt = hash_password(code)
        await self.repository.add_otp({"booking_id": booking["_id"], "purpose": purpose.value, "target_role": target_role.value, "code_hash": digest, "code_salt": salt, "code_ciphertext": self.cipher.encrypt(code.encode()).decode(), "expires_at": datetime.now(UTC) + timedelta(minutes=15), "attempts": 0, "consumed": False, "status": "ACTIVE"})

    async def otp_for_role(self, booking_id: str, purpose: OtpPurpose, role: Role, user_id: str) -> dict[str, Any]:
        booking = await self._authorized_booking(booking_id, role, user_id)
        otp = await self.repository.active_otp(booking_id, purpose.value)
        can_regenerate = role == Role.CUSTOMER and ((purpose == OtpPurpose.START and booking.get("status") == BookingStatus.DRIVER_ARRIVED) or (purpose == OtpPurpose.DRIVER_END and booking.get("status") in {BookingStatus.DESTINATION_REACHED, BookingStatus.COMPLETION_OTP_PENDING}))
        if can_regenerate and (not otp or as_utc(otp["expires_at"]) < datetime.now(UTC) or otp.get("attempts", 0) >= 5):
            if otp:
                otp_status = "EXPIRED" if as_utc(otp["expires_at"]) < datetime.now(UTC) else "CANCELLED"
                await self.repository.consume_otp(otp["_id"], otp_status)
            await self.create_otp(booking, purpose, Role.CUSTOMER)
            otp = await self.repository.active_otp(booking_id, purpose.value)
        if not otp or otp["target_role"] != role.value or as_utc(otp["expires_at"]) < datetime.now(UTC):
            raise HTTPException(status_code=404, detail="No active OTP for this user")
        return {"purpose": purpose.value, "code": self.cipher.decrypt(otp["code_ciphertext"].encode()).decode(), "expires_at": as_utc(otp["expires_at"])}

    async def verify_start(self, booking_id: str, driver_id: str, code: str) -> dict[str, Any]:
        booking = await self._assigned_booking(booking_id, driver_id)
        if booking["status"] != BookingStatus.DRIVER_ARRIVED:
            raise HTTPException(status_code=409, detail="Driver must arrive before verifying the trip start OTP")
        await self._verify_otp(booking_id, OtpPurpose.START, code)
        verified_at = datetime.now(UTC)
        waiting_charge = self._airport_waiting_charge(booking, verified_at) if booking.get("service_type") == "AIRPORT" else self._local_waiting_charge(booking, verified_at)
        quoted_total = int(booking.get("quoted_total", booking.get("total", 0) - int(booking.get("waiting_charge", 0)) - int(booking.get("extra_total", 0))))
        paid_amount = int(booking.get("paid_amount", quoted_total if booking.get("payment_status") == "PAID" else 0))
        updated = await self.repository.update_booking(booking_id, {"status": BookingStatus.TRIP_STARTED, "trip_started_at": verified_at, "start_otp_verified_at": verified_at, "quoted_total": quoted_total, "paid_amount": paid_amount, "waiting_charge": waiting_charge, "version": booking.get("version", 1) + 1})
        await self.repository.add_notification(booking["customer_id"], "TRIP_STARTED", "Your trip has started", f"Booking {booking['public_id']} is now underway.")
        return await self._recalculate(updated or booking)

    async def add_extra(self, booking_id: str, driver_id: str, charge_type: ExtraChargeType, amount: int, note: str, media_id: str | None) -> dict[str, Any]:
        booking = await self._assigned_booking(booking_id, driver_id)
        if booking["status"] not in {BookingStatus.TRIP_STARTED, BookingStatus.DRIVER_ARRIVED}:
            raise HTTPException(status_code=409, detail="Charges can only be added during an active trip")
        extra = await self.repository.add_extra({"booking_id": booking_id, "driver_id": driver_id, "type": charge_type.value, "amount": amount, "note": note, "media_id": media_id, "status": "APPROVED"})
        await self._recalculate(booking)
        await self.repository.add_notification(booking["customer_id"], "TRIP_CHARGE_ADDED", "Trip charge added", f"A {charge_type.value.lower()} charge of ₹{amount} was added to booking {booking['public_id']}.")
        return {"id": extra["_id"], **{key: value for key, value in extra.items() if key != "_id"}}

    async def request_end(self, booking_id: str, actor_role: Role, user_id: str, latitude: float | None, longitude: float | None) -> dict[str, Any]:
        if actor_role != Role.DRIVER:
            raise HTTPException(status_code=403, detail="Only the assigned driver can complete a trip")
        booking = await self._assigned_booking(booking_id, user_id)
        if booking["status"] not in {BookingStatus.TRIP_STARTED, BookingStatus.DESTINATION_REACHED, BookingStatus.COMPLETION_OTP_PENDING}:
            raise HTTPException(status_code=409, detail="Trip must be started before completion")
        recalculated = await self._recalculate(booking)
        if int(recalculated.get("balance_due", 0)) > 0:
            raise HTTPException(status_code=409, detail=f"Record the final balance payment of ₹{recalculated['balance_due']} before completing the trip")
        booking = await self._assigned_booking(booking_id, user_id)
        distance = None
        if latitude is not None and longitude is not None and booking.get("drop_latitude") is not None and booking.get("drop_longitude") is not None:
            distance = distance_meters(latitude, longitude, float(booking["drop_latitude"]), float(booking["drop_longitude"]))
        reached_at = datetime.now(UTC)
        reached_destination = distance is not None and distance <= COMPLETION_RADIUS_METERS
        if reached_destination:
            booking = await self.repository.update_booking(booking_id, {"status": BookingStatus.DESTINATION_REACHED, "destination_reached_at": reached_at, "version": booking.get("version", 1) + 1}) or booking
            return await self.complete(booking)
        if booking["status"] == BookingStatus.TRIP_STARTED:
            changes = {"status": BookingStatus.COMPLETION_OTP_PENDING, "completion_otp_requested_at": reached_at, "version": booking.get("version", 1) + 1}
            booking = await self.repository.update_booking(booking_id, changes) or booking
        otp = await self.repository.active_otp(booking_id, OtpPurpose.DRIVER_END.value)
        if not otp or as_utc(otp["expires_at"]) < datetime.now(UTC) or otp.get("attempts", 0) >= 5:
            if otp:
                otp_status = "EXPIRED" if as_utc(otp["expires_at"]) < datetime.now(UTC) else "CANCELLED"
                await self.repository.consume_otp(otp["_id"], otp_status)
            await self.create_otp(booking, OtpPurpose.DRIVER_END, Role.CUSTOMER)
        await self.repository.add_notification(booking["customer_id"], "TRIP_COMPLETION_REQUESTED", "Trip completion requested", f"Share the completion OTP for booking {booking['public_id']} with your driver when you are ready to complete the trip.")
        return {
            "status": "OTP_REQUIRED",
            "purpose": OtpPurpose.DRIVER_END.value,
            "target_role": Role.CUSTOMER.value,
            "distance_m": round(distance) if distance is not None else None,
        }

    async def record_balance(self, booking_id: str, driver_id: str, method: str) -> dict[str, Any]:
        booking = await self._assigned_booking(booking_id, driver_id)
        if booking["status"] not in {BookingStatus.TRIP_STARTED, BookingStatus.DESTINATION_REACHED, BookingStatus.COMPLETION_OTP_PENDING}:
            raise HTTPException(status_code=409, detail="Final balance can only be recorded during an active trip")
        recalculated = await self._recalculate(booking)
        amount_due = int(recalculated.get("balance_due", 0))
        if amount_due <= 0:
            raise HTTPException(status_code=409, detail="This trip has no outstanding balance")
        collected_total = int(booking.get("driver_collected_amount", 0)) + amount_due
        updated = await self.repository.update_booking(booking_id, {"driver_collected_amount": collected_total, "balance_payment_method": method, "balance_collected_at": datetime.now(UTC), "balance_due": 0, "payment_status": "PAID", "version": booking.get("version", 1) + 1}) or booking
        await self.repository.add_notification(booking["customer_id"], "BALANCE_RECEIVED", "Final balance received", f"Your driver recorded the remaining ₹{amount_due} by {method} for booking {booking['public_id']}.")
        return {"booking": {key: value for key, value in updated.items() if key != "_id"} | {"id": updated["_id"]}, "amount_received": amount_due, "method": method}

    async def verify_end(self, booking_id: str, actor_role: Role, user_id: str, purpose: OtpPurpose, code: str) -> dict[str, Any]:
        if actor_role != Role.DRIVER or purpose != OtpPurpose.DRIVER_END:
            raise HTTPException(status_code=403, detail="Only the assigned driver can verify the customer completion OTP")
        booking = await self._assigned_booking(booking_id, user_id)
        if booking["status"] not in {BookingStatus.DESTINATION_REACHED, BookingStatus.COMPLETION_OTP_PENDING}:
            raise HTTPException(status_code=409, detail="Driver must request the completion OTP before completing the trip")
        otp = await self.repository.active_otp(booking_id, purpose.value)
        if not otp or otp["target_role"] != Role.CUSTOMER.value:
            raise HTTPException(status_code=404, detail="No customer completion OTP is active")
        await self._verify_otp(booking_id, purpose, code)
        return await self.complete(booking)

    async def complete(self, booking: dict[str, Any]) -> dict[str, Any]:
        recalculated = await self._recalculate(booking)
        if int(recalculated.get("balance_due", 0)) > 0:
            raise HTTPException(status_code=409, detail=f"Final balance of ₹{recalculated['balance_due']} is still pending")
        updated = await self.repository.update_booking(booking["_id"], {"status": BookingStatus.TRIP_COMPLETED, "trip_completed_at": datetime.now(UTC), "version": booking.get("version", 1) + 1})
        active_otp = await self.repository.active_otp(booking["_id"], OtpPurpose.DRIVER_END.value)
        if active_otp:
            await self.repository.consume_otp(active_otp["_id"], "CANCELLED")
        live_locations.remove(booking["_id"])
        completed = await self._recalculate(updated or booking)
        await self.repository.add_notification(booking["customer_id"], "TRIP_COMPLETED", "Trip completed", f"Booking {booking['public_id']} is complete. Final total: ₹{completed['total']}.")
        return completed

    async def trip_view(self, booking_id: str, role: Role, user_id: str) -> dict[str, Any]:
        booking = await self._authorized_booking(booking_id, role, user_id)
        driver_id = booking.get("driver_id")
        driver_user = await self.repository.user(driver_id) if driver_id else None
        driver_location = live_locations.get(booking_id)
        extras = await self.repository.extras(booking_id)
        driver_contact = {key: driver_user.get(key) for key in ("name", "phone", "profile_image_id") if driver_user.get(key) is not None} | {"id": driver_id} if driver_user else None
        extra_total = sum(int(item.get("amount", 0)) for item in extras if item.get("status") == "APPROVED")
        original_lines = [line for line in booking.get("line_items", []) if line.get("code") not in {"WAITING", "TRIP_EXTRA"}]
        quoted_total = int(booking.get("quoted_total", booking.get("paid_amount", booking.get("total", 0) - int(booking.get("waiting_charge", 0)) - int(booking.get("extra_total", 0))) or sum(int(line.get("amount", 0)) for line in original_lines)))
        paid_amount = int(booking.get("paid_amount", quoted_total if booking.get("payment_status") == "PAID" else 0))
        driver_collected_amount = int(booking.get("driver_collected_amount", 0))
        final_total = int(booking.get("total", quoted_total + int(booking.get("waiting_charge", 0)) + extra_total))
        payment_summary = {"quoted_total": quoted_total, "paid_amount": paid_amount, "driver_collected_amount": driver_collected_amount, "additional_charges": max(0, final_total - quoted_total), "final_total": final_total, "amount_to_collect": max(0, final_total - paid_amount - driver_collected_amount)}
        return {"booking": {key: value for key, value in booking.items() if key != "_id"} | {"id": booking["_id"]}, "driver": driver_contact, "driver_location": driver_location, "extras": [{key: value for key, value in item.items() if key != "_id"} | {"id": item["_id"]} for item in extras], "payment_summary": payment_summary}

    async def _recalculate(self, booking: dict[str, Any]) -> dict[str, Any]:
        extras = await self.repository.extras(booking["_id"])
        extra_total = sum(int(item.get("amount", 0)) for item in extras if item.get("status") == "APPROVED")
        waiting_charge = int(booking.get("waiting_charge", 0))
        original_lines = [line for line in booking.get("line_items", []) if line.get("code") not in {"WAITING", "TRIP_EXTRA"} and line.get("label") not in {"Airport waiting", "Trip extras"}]
        line_items = [*original_lines]
        if waiting_charge:
            line_items.append({"code": "WAITING", "label": "Airport waiting" if booking.get("service_type") == "AIRPORT" else "Pickup waiting", "amount": waiting_charge})
        if extra_total:
            line_items.append({"code": "TRIP_EXTRA", "label": "Trip extras", "amount": extra_total})
        base_total = int(booking.get("quoted_total", booking.get("paid_amount", booking.get("total", 0) - int(booking.get("waiting_charge", 0)) - int(booking.get("extra_total", 0))) or sum(int(line.get("amount", 0)) for line in original_lines)))
        final_total = base_total + waiting_charge + extra_total
        balance_due = max(0, final_total - int(booking.get("paid_amount", 0)) - int(booking.get("driver_collected_amount", 0)))
        updated = await self.repository.update_booking(booking["_id"], {"quoted_total": base_total, "line_items": line_items, "extra_total": extra_total, "waiting_charge": waiting_charge, "total": final_total, "balance_due": balance_due})
        return {key: value for key, value in (updated or booking).items() if key != "_id"} | {"id": booking["_id"]}

    def _airport_waiting_charge(self, booking: dict[str, Any], verified_at: datetime) -> int:
        if booking.get("service_type") != "AIRPORT" or booking.get("airport_direction") != "PICKUP":
            return 0
        scheduled = as_utc(booking["airport_pickup_at"] if booking.get("airport_pickup_at") else booking["scheduled_at"])
        grace_end = scheduled + timedelta(minutes=int(booking.get("airport_grace_minutes", 30)))
        overdue_seconds = max(0, (verified_at - grace_end).total_seconds())
        return ceil(overdue_seconds / 3600) * int(booking.get("airport_waiting_rate", 150)) if overdue_seconds else 0

    def _local_waiting_charge(self, booking: dict[str, Any], verified_at: datetime) -> int:
        started = booking.get("waiting_started_at")
        if booking.get("service_type") != "NORMAL" or not started:
            return 0
        grace_end = as_utc(started) + timedelta(minutes=int(booking.get("waiting_grace_minutes", 15)))
        overdue_seconds = max(0, (verified_at - grace_end).total_seconds())
        return ceil(overdue_seconds / 60) * int(booking.get("waiting_rate_per_minute", 5)) if overdue_seconds else 0

    async def _verify_otp(self, booking_id: str, purpose: OtpPurpose, code: str) -> None:
        otp = await self.repository.active_otp(booking_id, purpose.value)
        label = "Trip Start OTP" if purpose == OtpPurpose.START else "Trip completion OTP"
        if not otp or as_utc(otp["expires_at"]) < datetime.now(UTC):
            raise HTTPException(status_code=400, detail=f"{label} expired. Ask the customer to keep the live trip page open for a new code.")
        if otp.get("attempts", 0) >= 5:
            raise HTTPException(status_code=400, detail=f"{label} locked after too many attempts. Ask the customer to refresh the live trip page.")
        if not verify_password(code, otp["code_hash"], otp["code_salt"]):
            await self.repository.store.update("trip_otps", otp["_id"], {"attempts": otp.get("attempts", 0) + 1})
            raise HTTPException(status_code=400, detail=f"Incorrect {label}. Enter the latest code shown on the customer's live trip page.")
        await self.repository.consume_otp(otp["_id"])

    async def _assigned_booking(self, booking_id: str, driver_id: str) -> dict[str, Any]:
        booking = await self.repository.booking(booking_id)
        if not booking or booking.get("driver_id") != driver_id:
            raise HTTPException(status_code=404, detail="Assigned trip not found")
        return booking

    async def _authorized_booking(self, booking_id: str, role: Role, user_id: str) -> dict[str, Any]:
        booking = await self.repository.booking(booking_id)
        if not booking:
            raise HTTPException(status_code=404, detail="Booking not found")
        allowed = role == Role.ADMIN or (role == Role.CUSTOMER and booking.get("customer_id") == user_id) or (role == Role.DRIVER and booking.get("driver_id") == user_id)
        if not allowed:
            raise HTTPException(status_code=404, detail="Booking not found")
        return booking