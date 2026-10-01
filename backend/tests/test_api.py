import os
import jwt
from bson import ObjectId
from datetime import UTC, datetime, timedelta

os.environ["DEMO_MODE"] = "true"
os.environ["SEED_DEMO_DATA"] = "true"
os.environ["SEED_ADMIN_EMAIL"] = "admin@mailinator.com"
os.environ["SEED_ADMIN_PASSWORD"] = "AdminTest@123"
os.environ["SEED_SUPER_ADMIN_EMAIL"] = "owner@mailinator.com"
os.environ["SEED_SUPER_ADMIN_PASSWORD"] = "OwnerTest@123"
os.environ["SEED_CUSTOMER_EMAIL"] = "ridex.customer@mailinator.com"
os.environ["SEED_CUSTOMER_PASSWORD"] = "Customer@123"
os.environ["SEED_DRIVER_EMAIL"] = "ridex.driver@mailinator.com"
os.environ["SEED_DRIVER_PASSWORD"] = "Driver@123"

from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.main import app, payment_policy, store
from app.database import public
from app.config import Settings, get_settings
from app.security import hash_password, verify_password
from app.services.pricing_service import calculate_vehicle_quote
from app.services.email_service import EmailDeliveryService
from app.services.google_review_refresh_service import GoogleReviewRefreshService


def login(client: TestClient, email: str, password: str) -> str:
    response = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200
    token = response.json()["access_token"]
    client.headers["Authorization"] = f"Bearer {token}"
    return token


def test_passwords_use_distinct_random_salts() -> None:
    first_hash, first_salt = hash_password("SamePassword123")
    second_hash, second_salt = hash_password("SamePassword123")
    assert first_salt != second_salt
    assert first_hash != second_hash
    assert verify_password("SamePassword123", first_hash, first_salt)
    assert not verify_password("WrongPassword123", first_hash, first_salt)


def test_public_documents_serialize_mongo_object_ids() -> None:
    document_id = ObjectId()
    result = public({"_id": document_id, "nested": {"reference": document_id}, "items": [document_id]})
    assert result == {"id": str(document_id), "nested": {"reference": str(document_id)}, "items": [str(document_id)]}


def test_admin_can_manually_refresh_google_review_snapshot(monkeypatch) -> None:
    place_data = r'''[null,[null,null,null,["https://search.google.com/local/reviews?placeid\u003dChIJiVvOuNwbrjsRDAOYVBwSl6M","4 reviews",null],null,null,null,4.8,4],"Konanur Tours and Travels","No. 87, Konanur Tours and Travels, Budigere, Bangalore, Karnataka 562129"]'''
    parsed = GoogleReviewRefreshService.parse_place_data(place_data)
    assert parsed["rating"] == 4.8
    assert parsed["review_count"] == 4

    async def fetched(_service):
        return parsed

    monkeypatch.setattr("app.main.GoogleReviewRefreshService.fetch", fetched)
    with TestClient(app) as client:
        login(client, "admin@mailinator.com", "AdminTest@123")
        refreshed = client.post("/api/v1/admin/reviews/google/refresh")
        assert refreshed.status_code == 200
        assert refreshed.json()["rating"] == 4.8
        assert refreshed.json()["review_count"] == 4
        assert client.get("/api/v1/reviews/google").json()["review_count"] == 4

        async def blocked(_service):
            raise HTTPException(status_code=502, detail="Changed Google payload")

        monkeypatch.setattr("app.main.GoogleReviewRefreshService.fetch", blocked)
        unchanged = client.post("/api/v1/admin/reviews/google/refresh")
        assert unchanged.status_code == 200
        assert unchanged.json()["review_count"] == 4
        assert "unchanged" in unchanged.json()["refresh_warning"]

        login(client, "ridex.customer@mailinator.com", "Customer@123")
        assert client.post("/api/v1/admin/reviews/google/refresh").status_code == 403


def test_vehicle_specific_local_and_outstation_pricing() -> None:
    vehicle = {"local_base_fare": 400, "local_included_km": 4, "local_per_km": 20, "outstation_one_way_base_fare": 2000, "outstation_one_way_per_km": 16, "outstation_one_way_included_km_per_day": 80, "outstation_one_way_extra_km_rate": 20, "outstation_one_way_driver_bata_per_day": 600, "outstation_round_trip_day_rate": 3200, "outstation_included_km_per_day": 250, "outstation_extra_km_rate": 18, "driver_bata_per_day": 500}
    rule = {"base_fare": 1000, "tax_percent": 5, "driver_allowance": 0}
    scheduled_at = datetime(2026, 10, 1, 8, tzinfo=UTC)

    local_total, local_lines, local_meta = calculate_vehicle_quote(service_type="NORMAL", vehicle=vehicle, rule=rule, distance_km=14.2, round_trip=False, scheduled_at=scheduled_at, return_at=None, package_hours=None)
    assert local_meta["billable_distance_km"] == 11
    assert local_total == 651
    assert local_lines[1]["amount"] == 220

    one_way_total, _, one_way_meta = calculate_vehicle_quote(service_type="OUTSTATION", vehicle=vehicle, rule=rule, distance_km=100, round_trip=False, scheduled_at=scheduled_at, return_at=None, package_hours=None)
    assert one_way_meta["included_distance_km"] == 80
    assert one_way_meta["billable_distance_km"] == 20
    assert one_way_total == 3150

    non_ac_total, non_ac_lines, non_ac_meta = calculate_vehicle_quote(service_type="OUTSTATION", vehicle=vehicle, rule=rule, distance_km=100, round_trip=False, scheduled_at=scheduled_at, return_at=None, package_hours=None, ac_required=False)
    assert non_ac_total == 2646
    assert non_ac_meta["ac_required"] is False
    assert non_ac_lines[0]["label"] == "One-way non-AC package (includes 80 km)"

    round_total, round_lines, round_meta = calculate_vehicle_quote(service_type="OUTSTATION", vehicle=vehicle, rule=rule, distance_km=300, round_trip=True, scheduled_at=scheduled_at, return_at=scheduled_at + timedelta(days=2), package_hours=None)
    assert round_meta["distance_km"] == 600
    assert round_meta["one_way_distance_km"] == 300
    assert round_meta["billable_distance_km"] == 100
    assert round_meta["trip_days"] == 2
    assert round_meta["included_distance_km"] == 500
    assert round_meta["vehicle_tariff"]["driver_bata_per_day"] == 500
    assert round_lines[1]["amount"] == 1800
    assert round_total == 9660


def test_local_quote_uses_route_distance_and_vehicle_tariff(monkeypatch) -> None:
    async def route(*_args, **_kwargs):
        return {"distance_m": 14_200, "duration_s": 1_800, "coordinates": []}

    monkeypatch.setattr("app.main.MapService.route", route)
    with TestClient(app) as client:
        login(client, "admin@mailinator.com", "AdminTest@123")
        updated = client.patch("/api/v1/admin/vehicles/innova", json={"local_base_fare": 400, "local_included_km": 4, "local_per_km": 20})
        assert updated.status_code == 200
        login(client, "ridex.customer@mailinator.com", "Customer@123")
        response = client.post("/api/v1/quotes", json={"service_type": "NORMAL", "pickup": "MG Road", "destination": "Bangalore Palace", "scheduled_at": "2026-10-01T10:00:00+05:30", "passengers": 2, "luggage": 1, "pickup_latitude": 12.975, "pickup_longitude": 77.606, "drop_latitude": 12.998, "drop_longitude": 77.592})
        assert response.status_code == 200
        assert response.json()["route"] == {"distance_km": 14.2, "estimated_duration_minutes": 30}
        quote = next(item for item in response.json()["results"] if item["vehicle"]["id"] == "innova")
        assert quote["total"] == 651
        assert quote["pricing"]["billable_distance_km"] == 11
        assert quote["line_items"][1]["label"] == "Distance charge (11 km × ₹20)"


def test_admin_can_update_and_archive_unused_vehicle() -> None:
    with TestClient(app) as client:
        login(client, "admin@mailinator.com", "AdminTest@123")
        assert client.delete("/api/v1/admin/vehicles/innova").status_code == 409
        created = client.post("/api/v1/admin/vehicles", json={"name": "Archive Test Car", "registration_number": "ka09zz6784", "category": "SEDAN_NON_CNG", "seats": 4, "luggage": 2, "transmission": "Automatic", "fuel": "Petrol", "base_rate": 1000, "local_per_km": 21, "outstation_round_trip_day_rate": 3500})
        assert created.status_code == 201
        assert created.json()["registration_number"] == "KA09ZZ6784"
        vehicle_id = created.json()["id"]
        changed = client.patch(f"/api/v1/admin/vehicles/{vehicle_id}", json={"name": "Updated Test Car", "local_per_km": 24})
        assert changed.status_code == 200
        assert changed.json()["name"] == "Updated Test Car"
        assert changed.json()["local_per_km"] == 24
        deleted = client.delete(f"/api/v1/admin/vehicles/{vehicle_id}")
        assert deleted.status_code == 200
        archived = next(item for item in store.memory["vehicles"] if item["_id"] == vehicle_id)
        assert archived["status"] == "INACTIVE"


def test_public_coupon_is_visible_and_usable_once_per_customer() -> None:
    with TestClient(app) as client:
        admin_token = login(client, "admin@mailinator.com", "AdminTest@123")
        created = client.post("/api/v1/admin/coupons", json={"code": "WELCOME10", "discount_type": "PERCENTAGE", "value": 10, "minimum_booking": 500, "maximum_discount": 500, "valid_from": (datetime.now(UTC) - timedelta(days=1)).isoformat(), "valid_to": (datetime.now(UTC) + timedelta(days=30)).isoformat(), "usage_limit": 100, "scope": "PUBLIC", "status": "ACTIVE"})
        assert created.status_code == 201
        offers = client.get("/api/v1/coupons/public")
        assert offers.status_code == 200
        assert any(item["code"] == "WELCOME10" for item in offers.json())

        client.headers.pop("Authorization")
        preview = client.post("/api/v1/quotes", json={"service_type": "AIRPORT", "pickup": "Marathahalli", "destination": "BLR Airport", "scheduled_at": "2026-11-01T09:00:00+05:30", "passengers": 2, "luggage": 1, "coupon_code": "WELCOME10"})
        assert preview.status_code == 200

        customer_token = login(client, "ridex.customer@mailinator.com", "Customer@123")
        quote_response = client.post("/api/v1/quotes", json={"service_type": "AIRPORT", "pickup": "Marathahalli", "destination": "BLR Airport", "scheduled_at": "2026-11-01T10:00:00+05:30", "passengers": 2, "luggage": 1, "coupon_code": "WELCOME10"})
        assert quote_response.status_code == 200
        quote = quote_response.json()["results"][0]
        assert quote["line_items"][-1]["code"] == "COUPON"
        assert quote["line_items"][-1]["amount"] < 0
        booking = client.post("/api/v1/bookings", json={"quote_id": quote["quote_id"], "vehicle_id": quote["vehicle"]["id"], "passenger_name": "Harish Kumar", "passenger_phone": "+919876543210", "special_instructions": ""}).json()
        payment = client.post(f"/api/v1/bookings/{booking['id']}/payment-order").json()
        assert client.post(f"/api/v1/payments/{payment['id']}/demo-confirm").status_code == 200
        reused = client.post("/api/v1/quotes", json={"service_type": "AIRPORT", "pickup": "Marathahalli", "destination": "BLR Airport", "scheduled_at": "2026-11-02T10:00:00+05:30", "passengers": 2, "luggage": 1, "coupon_code": "WELCOME10"})
        assert reused.status_code == 409


def test_personal_coupon_is_restricted_to_selected_customer() -> None:
    with TestClient(app) as client:
        login(client, "admin@mailinator.com", "AdminTest@123")
        created = client.post("/api/v1/admin/coupons", json={"code": "HARISHONLY", "discount_type": "FIXED", "value": 300, "minimum_booking": 500, "maximum_discount": 300, "valid_from": (datetime.now(UTC) - timedelta(days=1)).isoformat(), "valid_to": (datetime.now(UTC) + timedelta(days=30)).isoformat(), "usage_limit": 50, "scope": "PERSONAL", "customer_id": "customer-demo", "status": "ACTIVE"})
        assert created.status_code == 201
        assert created.json()["usage_limit"] == 1
        assert all(item["code"] != "HARISHONLY" for item in client.get("/api/v1/coupons/public").json())

        second = client.post("/api/v1/auth/register", json={"name": "Second Customer", "email": "second.customer@mailinator.com", "phone": "+919833334444", "password": "Second@123"})
        client.headers["Authorization"] = f"Bearer {second.json()['access_token']}"
        denied = client.post("/api/v1/quotes", json={"service_type": "AIRPORT", "pickup": "Marathahalli", "destination": "BLR Airport", "scheduled_at": "2026-11-03T10:00:00+05:30", "passengers": 2, "luggage": 1, "coupon_code": "HARISHONLY"})
        assert denied.status_code == 403

        login(client, "ridex.customer@mailinator.com", "Customer@123")
        allowed = client.post("/api/v1/quotes", json={"service_type": "AIRPORT", "pickup": "Marathahalli", "destination": "BLR Airport", "scheduled_at": "2026-11-03T10:00:00+05:30", "passengers": 2, "luggage": 1, "coupon_code": "HARISHONLY"})
        assert allowed.status_code == 200
        assert allowed.json()["results"][0]["pricing"]["coupon"]["discount"] == 300


def test_coupon_minimum_does_not_hide_ineligible_cars() -> None:
    with TestClient(app) as client:
        login(client, "admin@mailinator.com", "AdminTest@123")
        created = client.post("/api/v1/admin/coupons", json={"code": "MIXEDFARE", "discount_type": "PERCENTAGE", "value": 10, "minimum_booking": 1800, "maximum_discount": 500, "valid_from": (datetime.now(UTC) - timedelta(days=1)).isoformat(), "valid_to": (datetime.now(UTC) + timedelta(days=30)).isoformat(), "usage_limit": 100, "scope": "PUBLIC", "status": "ACTIVE"})
        assert created.status_code == 201
        coupon_record = next(item for item in store.memory["coupons"] if item["code"] == "MIXEDFARE")
        coupon_record["valid_from"] = coupon_record["valid_from"].replace(tzinfo=None)
        coupon_record["valid_to"] = coupon_record["valid_to"].replace(tzinfo=None)
        assert any(item["code"] == "MIXEDFARE" for item in client.get("/api/v1/coupons/public").json())
        login(client, "ridex.customer@mailinator.com", "Customer@123")
        response = client.post("/api/v1/quotes", json={"service_type": "AIRPORT", "pickup": "Whitefield", "destination": "BLR Airport", "scheduled_at": "2027-02-01T10:00:00+05:30", "passengers": 2, "luggage": 1, "coupon_code": "MIXEDFARE"})
        assert response.status_code == 200
        body = response.json()
        assert len(body["results"]) == 6
        assert any(item["pricing"].get("coupon") for item in body["results"])
        assert any(item["pricing"].get("coupon_ineligible_reason") for item in body["results"])
        assert body["coupon_message"].startswith("Coupon requires a minimum fare")


def test_local_waiting_is_driver_started_and_automatically_billed() -> None:
    with TestClient(app) as client:
        driver_token = login(client, "ridex.driver@mailinator.com", "Driver@123")
        booking = next(item for item in store.memory["bookings"] if item["_id"] == "booking-demo")
        booking.update({"service_type": "NORMAL", "status": "DRIVER_ON_THE_WAY", "pickup_latitude": 12.9716, "pickup_longitude": 77.5946, "waiting_grace_minutes": 15, "waiting_rate_per_minute": 5, "paid_amount": booking["total"]})
        assert client.post("/api/v1/trip-operations/booking-demo/location", json={"latitude": 13.0716, "longitude": 77.6946, "accuracy": 10}).json()["arrived"] is False
        assert client.post("/api/v1/trip-operations/booking-demo/arrived").status_code == 409
        assert client.post("/api/v1/trip-operations/booking-demo/location", json={"latitude": 12.9716, "longitude": 77.5946, "accuracy": 10}).json()["arrived"] is True
        waiting = client.post("/api/v1/trip-operations/booking-demo/start-waiting")
        assert waiting.status_code == 200
        booking["waiting_started_at"] = datetime.now(UTC) - timedelta(minutes=19)

        customer_token = login(client, "ridex.customer@mailinator.com", "Customer@123")
        otp = client.get("/api/v1/trip-operations/booking-demo/otp/START").json()["code"]
        client.headers["Authorization"] = f"Bearer {driver_token}"
        started = client.post("/api/v1/trip-operations/booking-demo/start", json={"code": otp})
        assert started.status_code == 200
        assert started.json()["waiting_charge"] == 25
        view = client.get("/api/v1/trip-operations/booking-demo").json()
        assert view["payment_summary"]["paid_amount"] == 3499
        assert view["payment_summary"]["amount_to_collect"] == 25


def test_health_and_catalog() -> None:
    with TestClient(app) as client:
        assert client.get("/health").json()["status"] == "ok"
        vehicles = client.get("/api/v1/vehicles")
        assert vehicles.status_code == 200
        assert len(vehicles.json()) == 6
        assert {item["category"] for item in vehicles.json()} == {"SEDAN_CNG", "SEDAN_NON_CNG", "ERTIGA", "INNOVA", "INNOVA_CRYSTA", "TT"}


def test_driver_registration_creates_pending_profile() -> None:
    with TestClient(app) as client:
        response = client.post("/api/v1/auth/register", json={"name": "New Driver", "email": "new.driver@mailinator.com", "phone": "+919811112222", "password": "DriverNew@123", "role": "DRIVER", "license_number": "KA01-2026-12345", "license_expiry": "2029-12-31"})
        assert response.status_code == 201
        claims = jwt.decode(response.json()["access_token"], get_settings().secret_key, algorithms=["HS256"])
        assert claims["role"] == "DRIVER"
        profile = next(item for item in store.memory["drivers"] if item["user_id"] == claims["sub"])
        assert profile["verification_status"] == "PENDING"
        assert profile["documents_status"] == "INCOMPLETE"
        client.headers["Authorization"] = f"Bearer {response.json()['access_token']}"
        assert client.get("/api/v1/driver/trips").status_code == 403
        assert client.patch("/api/v1/driver/availability", json={"availability": "AVAILABLE", "latitude": "12.97", "longitude": "77.59"}).status_code == 403
        for document_type, filename, content in (("LICENSE", "licence.pdf", b"%PDF-1.4 licence"), ("VEHICLE_PHOTO", "car.png", b"\x89PNG\r\n\x1a\ncar"), ("ADDRESS_PROOF", "address.pdf", b"%PDF-1.4 address")):
            upload = client.post(f"/api/v1/driver/documents/{document_type}", files={"file": (filename, content, "application/pdf" if filename.endswith(".pdf") else "image/png")})
            assert upload.status_code == 201
        assert upload.json()["documents_status"] == "SUBMITTED"
        driver_token = response.json()["access_token"]
        admin_token = login(client, "admin@mailinator.com", "AdminTest@123")
        approval = client.patch(f"/api/v1/admin/drivers/{claims['sub']}", json={"verification_status": "VERIFIED"})
        assert approval.status_code == 200
        assert approval.json()["profile"]["documents_status"] == "APPROVED"
        client.headers["Authorization"] = f"Bearer {driver_token}"
        assert client.get("/api/v1/driver/trips").status_code == 200


def test_session_refreshes_stale_role_claim() -> None:
    with TestClient(app) as client:
        response = client.post("/api/v1/auth/register", json={"name": "Corrected Driver", "email": "corrected.driver@mailinator.com", "phone": "+919822223333", "password": "Corrected@123"})
        stale_token = response.json()["access_token"]
        claims = jwt.decode(stale_token, get_settings().secret_key, algorithms=["HS256"])
        user = next(item for item in store.memory["users"] if item["_id"] == claims["sub"])
        user["role"] = "DRIVER"
        client.headers["Authorization"] = f"Bearer {stale_token}"
        session = client.get("/api/v1/auth/session")
        assert session.status_code == 200
        assert session.json()["user"]["role"] == "DRIVER"
        refreshed = jwt.decode(session.json()["access_token"], get_settings().secret_key, algorithms=["HS256"])
        assert refreshed["role"] == "DRIVER"


def test_customer_quote_booking_and_payment() -> None:
    with TestClient(app) as client:
        csrf = login(client, "ridex.customer@mailinator.com", "Customer@123")
        quote = client.post("/api/v1/quotes", json={"service_type": "AIRPORT", "pickup": "Marathahalli", "destination": "BLR Airport", "scheduled_at": "2026-09-28T10:00:00+05:30", "passengers": 2, "luggage": 2}).json()["results"][0]
        booking_response = client.post("/api/v1/bookings", headers={"X-CSRF-Token": csrf}, json={"quote_id": quote["quote_id"], "vehicle_id": quote["vehicle"]["id"], "passenger_name": "Harish Kumar", "passenger_phone": "+919876543210", "special_instructions": "Terminal 1"})
        assert booking_response.status_code == 201
        booking = booking_response.json()
        conflict = client.post("/api/v1/bookings", headers={"X-CSRF-Token": csrf}, json={"quote_id": quote["quote_id"], "vehicle_id": quote["vehicle"]["id"], "passenger_name": "Harish Kumar", "passenger_phone": "+919876543210", "special_instructions": "Duplicate"})
        assert conflict.status_code == 201
        assert conflict.json()["id"] == booking["id"]
        payment = client.post(f"/api/v1/bookings/{booking['id']}/payment-order", headers={"X-CSRF-Token": csrf}).json()
        confirmed = client.post(f"/api/v1/payments/{payment['id']}/demo-confirm", headers={"X-CSRF-Token": csrf})
        assert confirmed.status_code == 200
        assert confirmed.json()["status"] == "CONFIRMED"
        receipt = client.get(f"/api/v1/bookings/{booking['id']}/receipt.pdf")
        assert receipt.status_code == 200
        assert receipt.headers["content-type"] == "application/pdf"
        assert receipt.content.startswith(b"%PDF")
        cancelled = client.post(f"/api/v1/bookings/{booking['id']}/cancel", headers={"X-CSRF-Token": csrf})
        assert cancelled.status_code == 200
        assert cancelled.json()["status"] == "REFUND_PENDING"


def test_advance_upi_qr_payment_is_persisted_and_idempotent() -> None:
    with TestClient(app) as client:
        admin_token = login(client, "admin@mailinator.com", "AdminTest@123")
        settings_response = client.patch("/api/v1/admin/settings", json={"upi_id": "ridex-test@upi", "standard_advance_type": "PERCENTAGE", "standard_advance_value": 25, "airport_advance_type": "PERCENTAGE", "airport_advance_value": 25, "outstation_advance_type": "FIXED", "outstation_advance_value": 1500})
        assert settings_response.status_code == 200
        customer_token = login(client, "ridex.customer@mailinator.com", "Customer@123")
        quote = client.post("/api/v1/quotes", json={"service_type": "AIRPORT", "pickup": "Marathahalli", "destination": "BLR Airport", "scheduled_at": "2026-12-01T10:00:00+05:30", "passengers": 2, "luggage": 2}).json()["results"][0]
        payload = {"quote_id": quote["quote_id"], "vehicle_id": quote["vehicle"]["id"], "passenger_name": "Harish Kumar", "passenger_phone": "+919876543210", "special_instructions": ""}
        first = client.post("/api/v1/bookings", json=payload)
        second = client.post("/api/v1/bookings", json=payload)
        assert first.status_code == 201
        assert second.json()["id"] == first.json()["id"]
        payment = client.post(f"/api/v1/bookings/{first.json()['id']}/payment-order")
        assert payment.status_code == 200
        assert payment.json()["amount"] == round(quote["total"] * 0.25)
        assert payment.json()["payment_type"] == "ADVANCE_PERCENTAGE"
        assert payment.json()["upi_id"] == "ridex-test@upi"
        qr = client.get(f"/api/v1{payment.json()['qr_url']}")
        assert qr.status_code == 200
        assert qr.headers["content-type"] == "image/png"
        assert qr.content.startswith(b"\x89PNG")
        confirmed = client.post(f"/api/v1/payments/{payment.json()['id']}/demo-confirm")
        assert confirmed.status_code == 200
        assert confirmed.json()["payment_status"] == "ADVANCE_PAID"
        assert confirmed.json()["paid_amount"] == payment.json()["amount"]
        assert confirmed.json()["balance_due"] == quote["total"] - payment.json()["amount"]
        assert client.get(f"/api/v1{payment.json()['qr_url']}").status_code == 410

        legacy = next(item for item in store.memory["payments"] if item["_id"] == payment.json()["id"])
        legacy.pop("upi_uri")
        legacy["status"] = "CREATED"
        reopened = client.post(f"/api/v1/bookings/{first.json()['id']}/payment-order")
        assert reopened.status_code == 200
        assert reopened.json()["upi_uri"].startswith("upi://pay?")

        outstation_amount, payment_type, _ = __import__("asyncio").run(payment_policy({"service_type": "OUTSTATION", "total": 5000}))
        assert outstation_amount == 1500
        assert payment_type == "ADVANCE_FIXED"
        standard_amount, standard_type, _ = __import__("asyncio").run(payment_policy({"service_type": "NORMAL", "total": 100}))
        assert standard_amount == 25
        assert standard_type == "ADVANCE_PERCENTAGE"
        preview = client.get("/api/v1/payment-policy/preview", params={"service_type": "NORMAL", "total": 100})
        assert preview.status_code == 200
        assert preview.json() == {"amount": 25, "remaining": 75, "booking_total": 100, "payment_type": "ADVANCE_PERCENTAGE"}


def test_super_admin_fee_uses_total_bill_not_advance() -> None:
    with TestClient(app) as client:
        login(client, "admin@mailinator.com", "AdminTest@123")
        assert client.patch("/api/v1/super-admin/settings", json={"application_service_fee_percent": 2}).status_code == 403

        login(client, "owner@mailinator.com", "OwnerTest@123")
        configured = client.patch("/api/v1/super-admin/settings", json={"application_service_fee_percent": 2})
        assert configured.status_code == 200
        assert configured.json()["application_service_fee_percent"] == 2

        booking = next(item for item in store.memory["bookings"] if item["_id"] == "booking-demo")
        booking.update({"total": 10_000, "paid_amount": 0, "payment_status": "PENDING", "status": "PENDING_PAYMENT"})
        payment = store.memory["payments"]
        payment.clear()

        login(client, "ridex.customer@mailinator.com", "Customer@123")
        order = client.post("/api/v1/bookings/booking-demo/payment-order").json()
        stored = next(item for item in store.memory["payments"] if item["_id"] == order["id"])
        stored["amount"] = 3_000
        confirmed = client.post(f"/api/v1/payments/{order['id']}/demo-confirm")
        assert confirmed.status_code == 200

        history = client.get("/api/v1/customer/payments")
        assert history.status_code == 200
        assert any(item["id"] == order["id"] and item["upi_transaction_id"].startswith("DEMO_TXN_") for item in history.json())

        fee = next(item for item in store.memory["service_fee_records"] if item["payment_id"] == order["id"])
        assert fee["total_booking_amount"] == 10_000
        assert fee["amount_collected"] == 3_000
        assert fee["configured_percentage"] == 2
        assert fee["calculated_service_fee"] == 200


def test_super_admin_can_manage_normal_admin_accounts() -> None:
    with TestClient(app) as client:
        login(client, "admin@mailinator.com", "AdminTest@123")
        assert client.get("/api/v1/super-admin/admins").status_code == 403

        login(client, "owner@mailinator.com", "OwnerTest@123")
        initial = client.get("/api/v1/super-admin/admins")
        assert initial.status_code == 200
        assert any(admin["id"] == "admin-demo" for admin in initial.json())

        created = client.post("/api/v1/super-admin/admins", json={"name": "Operations Admin", "email": "operations.admin@mailinator.com", "phone": "+919811110000", "password": "Operations@123"})
        assert created.status_code == 201
        admin_id = created.json()["id"]
        assert created.json()["role"] == "ADMIN"
        assert "password_hash" not in created.json()

        duplicate = client.post("/api/v1/super-admin/admins", json={"name": "Duplicate Admin", "email": "operations.admin@mailinator.com", "phone": "+919811110001", "password": "Operations@123"})
        assert duplicate.status_code == 409

        updated = client.patch(f"/api/v1/super-admin/admins/{admin_id}", json={"name": "Senior Operations Admin", "phone": "+919811110002", "password": "NewOperations@123", "status": "ACTIVE"})
        assert updated.status_code == 200
        assert updated.json()["name"] == "Senior Operations Admin"

        report = client.get("/api/v1/super-admin/reports")
        assert report.status_code == 200
        assert report.json()["admin_count"] == 2
        assert "owner_earnings" in report.json()

        deleted = client.delete(f"/api/v1/super-admin/admins/{admin_id}")
        assert deleted.status_code == 200
        assert all(admin["id"] != admin_id for admin in client.get("/api/v1/super-admin/admins").json())


def test_role_boundaries_and_driver_transition() -> None:
    with TestClient(app) as client:
        login(client, "ridex.customer@mailinator.com", "Customer@123")
        assert client.get("/api/v1/admin/dashboard").status_code == 403
    with TestClient(app) as client:
        csrf = login(client, "ridex.driver@mailinator.com", "Driver@123")
        trips = client.get("/api/v1/driver/trips").json()
        booking_id = trips[0]["id"]
        steps = [("accept", "DRIVER_ACCEPTED"), ("on-the-way", "DRIVER_ON_THE_WAY")]
        for command, expected in steps:
            response = client.post(f"/api/v1/driver/trips/{booking_id}/{command}", headers={"X-CSRF-Token": csrf}, json={"action_id": f"{command}-demo-trip"})
            assert response.status_code == 200
            assert response.json()["status"] == expected
        assert client.post(f"/api/v1/driver/trips/{booking_id}/start", json={"action_id": "bypass-start"}).status_code == 404


def test_pending_booking_and_qr_are_repriced_after_coupon() -> None:
    with TestClient(app) as client:
        admin_token = login(client, "admin@mailinator.com", "AdminTest@123")
        client.patch("/api/v1/admin/settings", json={"standard_advance_type": "PERCENTAGE", "standard_advance_value": 25, "airport_advance_type": "PERCENTAGE", "airport_advance_value": 25})
        coupon = client.post("/api/v1/admin/coupons", json={"code": "CHECKOUT20", "discount_type": "PERCENTAGE", "value": 20, "minimum_booking": 500, "maximum_discount": 1000, "valid_from": (datetime.now(UTC) - timedelta(days=1)).isoformat(), "valid_to": (datetime.now(UTC) + timedelta(days=30)).isoformat(), "usage_limit": 100, "scope": "PUBLIC", "status": "ACTIVE"})
        assert coupon.status_code == 201
        login(client, "ridex.customer@mailinator.com", "Customer@123")
        request = {"service_type": "AIRPORT", "pickup": "Whitefield", "destination": "BLR Airport", "scheduled_at": "2027-03-01T10:00:00+05:30", "passengers": 2, "luggage": 1}
        base_quotes = client.post("/api/v1/quotes", json=request).json()["results"]
        base_quote = base_quotes[0]
        payload = {"quote_id": base_quote["quote_id"], "vehicle_id": base_quote["vehicle"]["id"], "passenger_name": "Harish Kumar", "passenger_phone": "+919876543210", "special_instructions": ""}
        booking = client.post("/api/v1/bookings", json=payload).json()
        original_payment = client.post(f"/api/v1/bookings/{booking['id']}/payment-order").json()
        assert original_payment["amount"] == round(base_quote["total"] * 0.25)

        discounted_quotes = client.post("/api/v1/quotes", json={**request, "coupon_code": "CHECKOUT20"}).json()["results"]
        discounted_quote = next(item for item in discounted_quotes if item["vehicle"]["id"] == base_quote["vehicle"]["id"])
        repriced_booking = client.post("/api/v1/bookings", json={**payload, "quote_id": discounted_quote["quote_id"]})
        assert repriced_booking.status_code == 201
        assert repriced_booking.json()["id"] == booking["id"]
        assert repriced_booking.json()["total"] == discounted_quote["total"]
        refreshed_payment = client.post(f"/api/v1/bookings/{booking['id']}/payment-order")
        assert refreshed_payment.status_code == 200
        assert refreshed_payment.json()["id"] == original_payment["id"]
        assert refreshed_payment.json()["booking_total"] == discounted_quote["total"]
        assert refreshed_payment.json()["amount"] == round(discounted_quote["total"] * 0.25)
        assert refreshed_payment.json()["provider_order_id"] != original_payment["provider_order_id"]
        confirmed = client.post(f"/api/v1/payments/{refreshed_payment.json()['id']}/demo-confirm")
        assert confirmed.status_code == 200
        client.headers["Authorization"] = f"Bearer {admin_token}"
        admin_payment = next(item for item in client.get("/api/v1/admin/payments").json() if item["id"] == refreshed_payment.json()["id"])
        assert admin_payment["booking_total"] == discounted_quote["total"]
        assert admin_payment["paid_amount"] == refreshed_payment.json()["amount"]
        assert admin_payment["driver_collected_amount"] == 0
        assert admin_payment["balance_due"] == discounted_quote["total"] - refreshed_payment.json()["amount"]


def test_vehicle_default_driver_auto_assignment_and_schedule_aware_reassignment() -> None:
    with TestClient(app) as client:
        admin_token = login(client, "admin@mailinator.com", "AdminTest@123")
        default_assignment = client.post("/api/v1/admin/vehicles/city/assign-driver", json={"driver_id": "driver-demo"})
        assert default_assignment.status_code == 200
        default_profile = next(item for item in store.memory["drivers"] if item["user_id"] == "driver-demo")
        assert default_profile["online_status"] == "OFFLINE"
        assert default_profile["schedule_availability"] == "UNAVAILABLE"
        login(client, "ridex.driver@mailinator.com", "Driver@123")
        assert client.patch("/api/v1/driver/availability", json={"online_status": "ONLINE", "latitude": "12.971599", "longitude": "77.594566"}).status_code == 200
        client.headers["Authorization"] = f"Bearer {admin_token}"

        second_driver = client.post("/api/v1/admin/drivers", json={"name": "Available Driver", "email": "available.driver@mailinator.com", "phone": "+919844445555", "password": "Available@123", "license_number": "KA02-2026-5555", "license_expiry": "2030-12-31"})
        assert second_driver.status_code == 201
        second_driver_id = second_driver.json()["id"]
        second_profile = next(item for item in store.memory["drivers"] if item["user_id"] == second_driver_id)
        second_profile["documents_status"] = "SUBMITTED"
        approved = client.patch(f"/api/v1/admin/drivers/{second_driver_id}", json={"verification_status": "VERIFIED"})
        assert approved.status_code == 200
        login(client, "available.driver@mailinator.com", "Available@123")
        assert client.patch("/api/v1/driver/availability", json={"online_status": "ONLINE", "latitude": "12.960000", "longitude": "77.600000"}).status_code == 200

        customer_token = login(client, "ridex.customer@mailinator.com", "Customer@123")
        quote = client.post("/api/v1/quotes", json={"service_type": "AIRPORT", "pickup": "Whitefield", "destination": "BLR Airport", "scheduled_at": "2027-01-10T10:00:00+05:30", "passengers": 2, "luggage": 1}).json()["results"]
        city_quote = next(item for item in quote if item["vehicle"]["id"] == "city")
        booking = client.post("/api/v1/bookings", json={"quote_id": city_quote["quote_id"], "vehicle_id": "city", "passenger_name": "Harish Kumar", "passenger_phone": "+919876543210", "special_instructions": ""}).json()
        payment = client.post(f"/api/v1/bookings/{booking['id']}/payment-order").json()
        confirmed = client.post(f"/api/v1/payments/{payment['id']}/demo-confirm")
        assert confirmed.status_code == 200
        assert confirmed.json()["status"] == "DRIVER_ASSIGNED"
        assert confirmed.json()["driver_id"] == "driver-demo"
        assert confirmed.json()["assignment_status"] == "AUTO_ASSIGNED"
        assert any(item["booking_id"] == booking["id"] and item["driver_id"] == "driver-demo" for item in store.memory["driver_reservations"])

        overlapping = client.post("/api/v1/quotes", json={"service_type": "AIRPORT", "pickup": "Whitefield", "destination": "BLR Airport", "scheduled_at": "2027-01-10T10:00:00+05:30", "passengers": 2, "luggage": 1}).json()["results"]
        assert all(item["vehicle"]["id"] != "city" for item in overlapping)
        client.headers["Authorization"] = f"Bearer {admin_token}"
        friend_vehicle = client.post("/api/v1/admin/vehicles", json={"name": "Friend Sedan", "registration_number": "KA06FS2026", "category": "SEDAN_NON_CNG", "seats": 4, "luggage": 2, "transmission": "Manual", "fuel": "Petrol", "has_ac": True, "base_rate": 1200, "status": "ACTIVE"})
        assert friend_vehicle.status_code == 201
        client.headers["Authorization"] = f"Bearer {customer_token}"
        expanded_capacity = client.post("/api/v1/quotes", json={"service_type": "AIRPORT", "pickup": "Whitefield", "destination": "BLR Airport", "scheduled_at": "2027-01-10T10:00:00+05:30", "passengers": 2, "luggage": 1}).json()["results"]
        assert any(item["vehicle"]["id"] == friend_vehicle.json()["id"] for item in expanded_capacity)

        client.headers["Authorization"] = f"Bearer {admin_token}"
        available = client.get(f"/api/v1/admin/bookings/{booking['id']}/available-drivers")
        assert available.status_code == 200
        assert next(item for item in available.json() if item["id"] == second_driver_id)["available"] is True
        reassigned = client.post(f"/api/v1/admin/bookings/{booking['id']}/assign-driver", json={"driver_id": second_driver_id})
        assert reassigned.status_code == 200
        assert reassigned.json()["driver_id"] == second_driver_id
        assert reassigned.json()["assignment_status"] == "ADMIN_ASSIGNED"
        assert not any(item["booking_id"] == booking["id"] and item["driver_id"] == "driver-demo" for item in store.memory["driver_reservations"])

        login(client, "ridex.driver@mailinator.com", "Driver@123")
        assert all(item["id"] != booking["id"] for item in client.get("/api/v1/driver/trips").json())
        login(client, "available.driver@mailinator.com", "Available@123")
        assert any(item["id"] == booking["id"] for item in client.get("/api/v1/driver/trips").json())

        seed_booking = next(item for item in store.memory["bookings"] if item["_id"] == "booking-demo")
        client.headers["Authorization"] = f"Bearer {customer_token}"
        conflict_quotes = client.post("/api/v1/quotes", json={"service_type": "AIRPORT", "pickup": "Whitefield", "destination": "BLR Airport", "scheduled_at": seed_booking["scheduled_at"], "passengers": 2, "luggage": 1}).json()["results"]
        conflict_quote = next(item for item in conflict_quotes if item["vehicle"]["id"] == "city")
        conflict_booking = client.post("/api/v1/bookings", json={"quote_id": conflict_quote["quote_id"], "vehicle_id": "city", "passenger_name": "Harish Kumar", "passenger_phone": "+919876543210", "special_instructions": ""}).json()
        conflict_payment = client.post(f"/api/v1/bookings/{conflict_booking['id']}/payment-order").json()
        conflict_confirmed = client.post(f"/api/v1/payments/{conflict_payment['id']}/demo-confirm")
        assert conflict_confirmed.status_code == 200
        assert conflict_confirmed.json()["status"] == "CONFIRMED"
        assert conflict_confirmed.json()["driver_id"] is None
        assert conflict_confirmed.json()["assignment_status"] == "AWAITING_ADMIN"
        assert "Overlaps" in conflict_confirmed.json()["assignment_reason"]

        client.headers["Authorization"] = f"Bearer {admin_token}"
        conflict_available = client.get(f"/api/v1/admin/bookings/{conflict_booking['id']}/available-drivers").json()
        default_option = next(item for item in conflict_available if item["id"] == "driver-demo")
        alternate_option = next(item for item in conflict_available if item["id"] == second_driver_id)
        assert default_option["available"] is False
        assert "Overlaps" in default_option["unavailable_reason"]
        assert alternate_option["available"] is True
        blocked = client.post(f"/api/v1/admin/bookings/{conflict_booking['id']}/assign-driver", json={"driver_id": "driver-demo"})
        assert blocked.status_code == 409
        assigned_alternate = client.post(f"/api/v1/admin/bookings/{conflict_booking['id']}/assign-driver", json={"driver_id": second_driver_id})
        assert assigned_alternate.status_code == 200
        assert assigned_alternate.json()["driver_id"] == second_driver_id


def test_inactive_driver_old_token_is_rejected() -> None:
    with TestClient(app) as client:
        driver_token = login(client, "ridex.driver@mailinator.com", "Driver@123")
        admin_token = login(client, "admin@mailinator.com", "AdminTest@123")
        deactivated = client.patch("/api/v1/admin/drivers/driver-demo", json={"status": "INACTIVE"})
        assert deactivated.status_code == 200
        client.headers["Authorization"] = f"Bearer {driver_token}"
        assert client.get("/api/v1/driver/dashboard").status_code == 403
        assert client.get("/api/v1/driver/trips").status_code == 403
        assert client.post("/api/v1/trip-operations/booking-demo/location", json={"latitude": 12.97, "longitude": 77.59}).status_code == 403


def test_advance_balance_collection_and_shared_live_location() -> None:
    with TestClient(app) as client:
        booking = next(item for item in store.memory["bookings"] if item["_id"] == "booking-demo")
        booking.update({"status": "TRIP_STARTED", "payment_status": "ADVANCE_PAID", "quoted_total": 100, "total": 100, "paid_amount": 25, "balance_due": 75, "line_items": [{"code": "BASE", "label": "Ride fare", "amount": 100}], "drop_latitude": 12.9716, "drop_longitude": 77.5946})
        driver_token = login(client, "ridex.driver@mailinator.com", "Driver@123")
        location = client.post("/api/v1/trip-operations/booking-demo/location", json={"latitude": 12.9716, "longitude": 77.5946, "accuracy": 8})
        assert location.status_code == 200
        assert "live_locations" not in store.memory

        view = client.get("/api/v1/trip-operations/booking-demo").json()
        assert view["payment_summary"]["paid_amount"] == 25
        assert view["payment_summary"]["driver_collected_amount"] == 0
        assert view["payment_summary"]["amount_to_collect"] == 75
        blocked = client.post("/api/v1/trip-operations/booking-demo/request-end", json={"latitude": 12.9716, "longitude": 77.5946})
        assert blocked.status_code == 409
        assert "₹75" in blocked.json()["detail"]
        assert client.post("/api/v1/trip-operations/booking-demo/record-balance", json={"method": "CARD"}).status_code == 422
        collected = client.post("/api/v1/trip-operations/booking-demo/record-balance", json={"method": "UPI"})
        assert collected.status_code == 200
        assert collected.json()["amount_received"] == 75
        assert booking["driver_collected_amount"] == 75
        assert booking["balance_payment_method"] == "UPI"

        admin_token = login(client, "admin@mailinator.com", "AdminTest@123")
        admin_booking = next(item for item in client.get("/api/v1/admin/bookings").json() if item["id"] == "booking-demo")
        assert admin_booking["driver_location"]["latitude"] == 12.9716
        assert admin_booking["driver_collected_amount"] == 75
        client.headers["Authorization"] = f"Bearer {driver_token}"
        completed = client.post("/api/v1/trip-operations/booking-demo/request-end", json={"latitude": 12.9716, "longitude": 77.5946})
        assert completed.status_code == 200
        assert completed.json()["status"] == "TRIP_COMPLETED"


def test_forgot_password_stores_only_hashed_otp() -> None:
    with TestClient(app) as client:
        response = client.post("/api/v1/auth/forgot-password", json={"email": "ridex.customer@mailinator.com"})
        assert response.status_code == 200
        record = store.memory["password_reset_otps"][-1]
        assert "otp" not in record
        assert record["otp_hash"]
        assert record["otp_salt"]
        delivery = store.memory["email_outbox"][-1]
        assert delivery["event_type"] == "PASSWORD_RESET"
        assert delivery["status"] == "SUPPRESSED_DEMO"
        assert delivery["original_recipient"] == "ridex.customer@mailinator.com"

        login(client, "admin@mailinator.com", "AdminTest@123")
        deliveries = client.get("/api/v1/admin/email-deliveries")
        assert deliveries.status_code == 200
        logged = next(item for item in deliveries.json() if item["id"] == delivery["_id"])
        assert "body" not in logged
        assert logged["recipient_domain"] == "mailinator.com"


def test_development_mailinator_delivery_redirects_to_configured_inbox() -> None:
    with TestClient(app):
        service = EmailDeliveryService(store, Settings(app_env="development", demo_mode=False, seed_demo_data=False, mongodb_uri="mongodb://unused", secret_key="test-secret", smtp_host="smtp.gmail.com", smtp_username="sender@gmail.com", smtp_password="configured", smtp_from_email="sender@gmail.com", email_delivery_enabled=False))
        delivery = __import__("asyncio").run(service.enqueue("person@mailinator.com", "Subject", "Body", "TEST"))
        assert delivery["redirected"] is True
        assert delivery["recipient"] == "sender@gmail.com"
        assert delivery["original_recipient"] == "person@mailinator.com"
        assert delivery["status"] == "NOT_CONFIGURED"


def test_admin_logout_requires_client_to_discard_bearer() -> None:
    with TestClient(app) as client:
        csrf = login(client, "admin@mailinator.com", "AdminTest@123")
        assert client.get("/api/v1/admin/dashboard").status_code == 200
        logout = client.post("/api/v1/auth/logout", headers={"X-CSRF-Token": csrf})
        assert logout.status_code == 200
        client.headers.pop("Authorization")
        assert client.get("/api/v1/admin/dashboard").status_code == 401


def test_admin_database_console_redacts_and_guards_records() -> None:
    with TestClient(app) as client:
        login(client, "admin@mailinator.com", "AdminTest@123")
        collections = client.get("/api/v1/admin/database/collections")
        assert collections.status_code == 200
        assert any(item["name"] == "users" and item["cleanup_enabled"] is False for item in collections.json())

        users = client.get("/api/v1/admin/database/users").json()
        admin_record = next(item for item in users if item["record"]["email"] == "admin@mailinator.com")
        assert "password_hash" not in admin_record["record"]
        assert "password_salt" not in admin_record["record"]
        assert admin_record["deletable"] is False
        assert client.delete(f"/api/v1/admin/database/users/{admin_record['record']['id']}").status_code == 403

        record = store.memory["notifications"].append({"_id": "cleanup-notification", "user_id": "customer-demo", "event_type": "TEST", "title": "Cleanup", "message": "Disposable", "read": True, "created_at": datetime.now(UTC)})
        notifications = client.get("/api/v1/admin/database/notifications").json()
        cleanup = next(item for item in notifications if item["record"]["id"] == "cleanup-notification")
        assert cleanup["deletable"] is True
        assert client.delete("/api/v1/admin/database/notifications/cleanup-notification").status_code == 200
        assert not any(item["_id"] == "cleanup-notification" for item in store.memory["notifications"])
        store.memory["email_outbox"].append({"_id": "secret-email", "status": "FAILED", "body": "OTP 123456", "subject": "Secret", "original_recipient": "customer@example.com", "created_at": datetime.now(UTC)})
        emails = client.get("/api/v1/admin/database/email_outbox").json()
        secret = next(item for item in emails if item["record"]["id"] == "secret-email")
        assert secret["record"]["body"] == "[REDACTED]"


def test_admin_payments_are_enriched_and_protected() -> None:
    with TestClient(app) as client:
        customer_csrf = login(client, "ridex.customer@mailinator.com", "Customer@123")
        assert customer_csrf
        assert client.get("/api/v1/admin/payments").status_code == 403
    with TestClient(app) as client:
        login(client, "admin@mailinator.com", "AdminTest@123")
        response = client.get("/api/v1/admin/payments")
        assert response.status_code == 200
        for payment in response.json():
            assert "booking_public_id" in payment
            assert "customer_name" in payment


def test_complete_admin_api_is_database_backed() -> None:
    with TestClient(app) as client:
        admin_token = login(client, "admin@mailinator.com", "AdminTest@123")
        headers = {"X-CSRF-Token": admin_token}

        dashboard = client.get("/api/v1/admin/dashboard").json()
        assert len(dashboard["booking_trends"]) == 7
        assert len(dashboard["revenue_trends"]) == 7

        customers = [user for user in client.get("/api/v1/admin/users").json() if user["role"] == "CUSTOMER"]
        customer = client.patch(f"/api/v1/admin/users/{customers[0]['id']}", headers=headers, json={"status": "INACTIVE"})
        assert customer.status_code == 200
        assert customer.json()["status"] == "INACTIVE"

        driver = client.post("/api/v1/admin/drivers", headers=headers, json={"name": "Test Driver", "email": "ridex.driver2@mailinator.com", "phone": "+919811111111", "password": "DriverTwo@123", "license_number": "KA-TEST-002", "license_expiry": "2028-12-31"})
        assert driver.status_code == 201
        driver_id = driver.json()["id"]
        pending_approval = client.patch(f"/api/v1/admin/drivers/{driver_id}", headers=headers, json={"verification_status": "VERIFIED"})
        assert pending_approval.status_code == 409
        login(client, "ridex.driver2@mailinator.com", "DriverTwo@123")
        for document_type, filename, content_type, content in (("LICENSE", "licence.pdf", "application/pdf", b"%PDF-1.4 licence"), ("VEHICLE_PHOTO", "car.png", "image/png", b"\x89PNG\r\n\x1a\ncar"), ("ADDRESS_PROOF", "address.pdf", "application/pdf", b"%PDF-1.4 address")):
            assert client.post(f"/api/v1/driver/documents/{document_type}", files={"file": (filename, content, content_type)}).status_code == 201
        client.headers["Authorization"] = f"Bearer {admin_token}"
        verified = client.patch(f"/api/v1/admin/drivers/{driver_id}", headers=headers, json={"verification_status": "VERIFIED", "availability": "AVAILABLE"})
        assert verified.json()["profile"]["verification_status"] == "VERIFIED"

        vehicle = client.post("/api/v1/admin/vehicles", headers=headers, json={"name": "Test Sedan", "registration_number": "KA10TT1234", "category": "SEDAN_NON_CNG", "seats": 4, "luggage": 2, "transmission": "Automatic", "fuel": "Petrol", "has_ac": True, "base_rate": 1200, "image": "https://example.com/car.jpg", "status": "ACTIVE"})
        assert vehicle.status_code == 201
        vehicle_id = vehicle.json()["id"]
        maintenance = client.patch(f"/api/v1/admin/vehicles/{vehicle_id}", headers=headers, json={"status": "MAINTENANCE"})
        assert maintenance.json()["status"] == "MAINTENANCE"
        assignment = client.patch(f"/api/v1/admin/drivers/{driver_id}", headers=headers, json={"assigned_vehicle_id": vehicle_id})
        assert assignment.status_code == 200
        assert assignment.json()["profile"]["assigned_vehicle_id"] == vehicle_id
        vehicle_assignment = client.post(f"/api/v1/admin/vehicles/{vehicle_id}/assign-driver", headers=headers, json={"driver_id": driver_id})
        assert vehicle_assignment.status_code == 200
        assert vehicle_assignment.json()["assigned_driver"]["id"] == driver_id
        assert client.patch(f"/api/v1/admin/drivers/{driver_id}", headers=headers, json={"assigned_vehicle_id": "missing-vehicle"}).status_code == 404

        bookings = client.get("/api/v1/admin/bookings").json()
        assert bookings[0]["customer"]["role"] == "CUSTOMER"
        assert bookings[0]["vehicle"]["name"]
        today = datetime.now(UTC).date()
        calendar = client.get(f"/api/v1/admin/bookings/calendar?start={today.isoformat()}&end={(today + timedelta(days=31)).isoformat()}")
        assert calendar.status_code == 200
        calendar_booking = next(item for item in calendar.json()["bookings"] if item["id"] == "booking-demo")
        assert calendar_booking["vehicle"]["name"]
        assert calendar_booking["driver"]["name"]
        assert calendar_booking["pickup"]
        assert calendar_booking["destination"]
        assert client.get(f"/api/v1/admin/bookings/calendar?start={today.isoformat()}&end={(today + timedelta(days=90)).isoformat()}").status_code == 422

        rule = client.post("/api/v1/admin/pricing-rules", headers=headers, json={"service_type": "NORMAL", "vehicle_category": "SEDAN_NON_CNG", "base_fare": 500, "per_km": 18, "extra_hour": 200, "driver_allowance": 0, "tax_percent": 5, "status": "DRAFT"})
        assert rule.status_code == 201
        rule_body = rule.json()
        rule_body["status"] = "ACTIVE"
        active_rule = client.patch(f"/api/v1/admin/pricing-rules/{rule_body['id']}", headers=headers, json=rule_body)
        assert active_rule.json()["status"] == "ACTIVE"

        coupon = client.post("/api/v1/admin/coupons", headers=headers, json={"code": "TEST10", "discount_type": "PERCENTAGE", "value": 10, "minimum_booking": 1000, "maximum_discount": 500, "valid_from": "2026-09-26T00:00:00Z", "valid_to": "2026-10-26T00:00:00Z", "usage_limit": 100, "status": "ACTIVE"})
        assert coupon.status_code == 201

        store.memory["reviews"].append({"_id": "review-admin-test", "booking_id": "booking-demo", "customer_id": "customer-demo", "rating": 5, "comment": "Great ride", "status": "PUBLISHED", "created_at": "2026-09-26T00:00:00Z"})
        assert any(item["id"] == "review-admin-test" for item in client.get("/api/v1/reviews").json())
        review = client.patch("/api/v1/admin/reviews/review-admin-test", headers=headers, json={"status": "HIDDEN", "reason": "Moderated in test"})
        assert review.json()["status"] == "HIDDEN"
        assert all(item["id"] != "review-admin-test" for item in client.get("/api/v1/reviews").json())

        settings_response = client.patch("/api/v1/admin/settings", headers=headers, json={"support_phone": "+91 9000000000", "cancellation_hours": 4})
        assert settings_response.json()["cancellation_hours"] == 4
        assert client.get("/api/v1/admin/reports/summary").status_code == 200
        assert client.get("/api/v1/admin/notifications").status_code == 200
        assert len(client.get("/api/v1/admin/audit-logs").json()) >= 6


def test_admin_pricing_change_controls_customer_quote() -> None:
    with TestClient(app) as client:
        admin_csrf = login(client, "admin@mailinator.com", "AdminTest@123")
        rules = client.get("/api/v1/admin/pricing-rules").json()
        rule = next(item for item in rules if item["service_type"] == "AIRPORT" and item["vehicle_category"] == "INNOVA")
        changed = {**rule, "base_fare": 7000, "driver_allowance": 0, "tax_percent": 5, "status": "ACTIVE"}
        response = client.patch(f"/api/v1/admin/pricing-rules/{rule['id']}", headers={"X-CSRF-Token": admin_csrf}, json=changed)
        assert response.status_code == 200

        login(client, "ridex.customer@mailinator.com", "Customer@123")
        quote_response = client.post("/api/v1/quotes", json={"service_type": "AIRPORT", "pickup": "Marathahalli", "destination": "BLR Airport", "scheduled_at": "2026-10-28T10:00:00+05:30", "passengers": 2, "luggage": 2})
        assert quote_response.status_code == 200
        innova_quote = next(item for item in quote_response.json()["results"] if item["vehicle"]["id"] == "innova")
        assert innova_quote["total"] == 7350


def test_jwt_claims_and_customer_account_apis() -> None:
    with TestClient(app) as client:
        token = login(client, "ridex.customer@mailinator.com", "Customer@123")
        claims = jwt.decode(token, get_settings().secret_key, algorithms=["HS256"])
        assert claims["sub"] == "customer-demo"
        assert claims["role"] == "CUSTOMER"
        assert claims["name"] == "Harish Kumar"
        assert claims["email"].endswith("@mailinator.com")
        assert claims["phone"]
        assert "password" not in claims

        dashboard = client.get("/api/v1/customer/dashboard")
        assert dashboard.status_code == 200
        assert dashboard.json()["customer"]["id"] == claims["sub"]
        assert client.get("/api/v1/driver/dashboard").status_code == 403
        assert client.get("/api/v1/admin/dashboard").status_code == 403

        location = client.post("/api/v1/customer/saved-locations", json={"label": "Home", "address": "12.971599, 77.594566", "latitude": 12.971599, "longitude": 77.594566})
        assert location.status_code == 201
        locations = client.get("/api/v1/customer/saved-locations").json()
        assert len(locations) == 1
        assert locations[0]["customer_id"] == claims["sub"]
        assert client.delete(f"/api/v1/customer/saved-locations/{location.json()['id']}").status_code == 200

        profile = client.patch("/api/v1/customer/profile", json={"name": "Updated Customer", "phone": "+919899999999"})
        assert profile.status_code == 200
        refreshed = jwt.decode(profile.json()["access_token"], get_settings().secret_key, algorithms=["HS256"])
        assert refreshed["name"] == "Updated Customer"
        assert refreshed["phone"] == "+919899999999"


def test_driver_online_status_requires_and_stores_location() -> None:
    with TestClient(app) as client:
        login(client, "ridex.driver@mailinator.com", "Driver@123")
        missing_location = client.patch("/api/v1/driver/availability", json={"online_status": "ONLINE"})
        assert missing_location.status_code == 422
        online = client.patch("/api/v1/driver/availability", json={"online_status": "ONLINE", "latitude": "12.971599", "longitude": "77.594566"})
        assert online.status_code == 200
        assert online.json()["online_status"] == "ONLINE"
        assert online.json()["schedule_availability"] == "AVAILABLE"
        assert online.json()["latitude"] == 12.971599
        assert online.json()["longitude"] == 77.594566
        assert online.json()["last_seen"]
        offline = client.patch("/api/v1/driver/availability", json={"online_status": "OFFLINE"})
        assert offline.status_code == 200
        assert offline.json()["online_status"] == "OFFLINE"
        assert offline.json()["schedule_availability"] == "UNAVAILABLE"


def test_media_blob_and_trip_otp_extra_completion_workflow() -> None:
    with TestClient(app) as client:
        admin_token = login(client, "admin@mailinator.com", "AdminTest@123")
        upload = client.post(
            "/api/v1/admin/media/VEHICLE/innova",
            files={"file": ("innova.png", b"\x89PNG\r\n\x1a\nRIDEX", "image/png")},
        )
        assert upload.status_code == 201
        media = client.get(upload.json()["url"])
        assert media.status_code == 200
        assert media.content.startswith(b"\x89PNG")
        vehicle = next(item for item in client.get("/api/v1/admin/vehicles").json() if item["id"] == "innova")
        assert upload.json()["id"] in vehicle.get("image_ids", [])
        assert "future_booking_count" in vehicle
        assert "next_booking_at" in vehicle

        driver_token = login(client, "ridex.driver@mailinator.com", "Driver@123")
        booking_id = "booking-demo"
        client.post(f"/api/v1/driver/trips/{booking_id}/accept", json={"action_id": "accept-layered-trip"})
        client.post(f"/api/v1/driver/trips/{booking_id}/on-the-way", json={"action_id": "travel-layered-trip"})
        booking_document = next(item for item in store.memory["bookings"] if item["_id"] == booking_id)
        booking_document.update({"pickup_latitude": 12.9716, "pickup_longitude": 77.5946})
        location = client.post(f"/api/v1/trip-operations/{booking_id}/location", json={"latitude": 12.9731, "longitude": 77.5946, "accuracy": 10})
        assert location.status_code == 200
        assert location.json()["arrived"] is True
        assert booking_document["status"] == "DRIVER_ARRIVED"
        assert "trip_locations" not in store.memory
        driver_profile = next(item for item in store.memory["drivers"] if item["user_id"] == "driver-demo")
        assert "location_accuracy" not in driver_profile
        assert any(item["event_type"] == "DRIVER_ARRIVED" and item["user_id"] == "customer-demo" for item in store.memory["notifications"])

        booking_document.update({"airport_direction": "PICKUP", "airport_pickup_at": (datetime.now(UTC) - timedelta(hours=2)).isoformat(), "airport_grace_minutes": 30, "airport_waiting_rate": 150})

        customer_token = login(client, "ridex.customer@mailinator.com", "Customer@123")
        trip_view = client.get(f"/api/v1/trip-operations/{booking_id}")
        assert trip_view.status_code == 200
        assert trip_view.json()["driver"]["phone"]
        first_otp_record = next(item for item in store.memory["trip_otps"] if item["booking_id"] == booking_id and item["purpose"] == "START")
        first_otp_record["expires_at"] = datetime.now(UTC).replace(tzinfo=None) - timedelta(seconds=1)
        otp_response = client.get(f"/api/v1/trip-operations/{booking_id}/otp/START")
        assert otp_response.status_code == 200
        assert len([item for item in store.memory["trip_otps"] if item["booking_id"] == booking_id and item["purpose"] == "START"]) == 2
        latest_otp = sorted([item for item in store.memory["trip_otps"] if item["booking_id"] == booking_id and item["purpose"] == "START"], key=lambda item: str(item.get("created_at", "")), reverse=True)[0]
        latest_otp["attempts"] = 5
        regenerated = client.get(f"/api/v1/trip-operations/{booking_id}/otp/START")
        assert regenerated.status_code == 200
        assert len([item for item in store.memory["trip_otps"] if item["booking_id"] == booking_id and item["purpose"] == "START"]) == 3
        otp = regenerated.json()["code"]
        client.headers["Authorization"] = f"Bearer {driver_token}"
        wrong = client.post(f"/api/v1/trip-operations/{booking_id}/start", json={"code": "111111" if otp == "000000" else "000000"})
        assert wrong.status_code == 400
        assert wrong.json()["detail"] == "Incorrect Trip Start OTP. Enter the latest code shown on the customer's live trip page."
        started = client.post(f"/api/v1/trip-operations/{booking_id}/start", json={"code": otp})
        assert started.status_code == 200
        assert started.json()["status"] == "TRIP_STARTED"
        assert started.json()["waiting_charge"] == 300
        evidence = client.post(f"/api/v1/trip-operations/{booking_id}/evidence", files={"file": ("toll.png", b"\x89PNG\r\n\x1a\nreceipt", "image/png")})
        assert evidence.status_code == 201
        toll = client.post(f"/api/v1/trip-operations/{booking_id}/extras", json={"type": "TOLL", "amount": 250, "note": "Highway toll", "media_id": evidence.json()["id"]})
        assert toll.status_code == 201
        driver_view = client.get(f"/api/v1/trip-operations/{booking_id}").json()
        assert driver_view["payment_summary"] == {"quoted_total": 3499, "paid_amount": 3499, "driver_collected_amount": 0, "additional_charges": 550, "final_total": 4049, "amount_to_collect": 550}
        booking_document.update({"drop_latitude": 13.0, "drop_longitude": 77.6})
        blocked_end = client.post(f"/api/v1/trip-operations/{booking_id}/request-end", json={"latitude": 12.9716, "longitude": 77.5946})
        assert blocked_end.status_code == 409
        assert "₹550" in blocked_end.json()["detail"]
        balance = client.post(f"/api/v1/trip-operations/{booking_id}/record-balance", json={"method": "CASH"})
        assert balance.status_code == 200
        assert balance.json()["amount_received"] == 550
        assert balance.json()["method"] == "CASH"
        end_request = client.post(f"/api/v1/trip-operations/{booking_id}/request-end", json={"latitude": 12.9716, "longitude": 77.5946})
        assert end_request.json()["purpose"] == "DRIVER_END"
        expired_end_otp = next(item for item in store.memory["trip_otps"] if item["booking_id"] == booking_id and item["purpose"] == "DRIVER_END" and not item["consumed"])
        expired_end_otp["expires_at"] = datetime.now(UTC) - timedelta(seconds=1)
        client.headers["Authorization"] = f"Bearer {customer_token}"
        end_otp = client.get(f"/api/v1/trip-operations/{booking_id}/otp/DRIVER_END").json()["code"]
        assert expired_end_otp["status"] == "EXPIRED"
        assert next(item for item in store.memory["trip_otps"] if item["booking_id"] == booking_id and item["purpose"] == "DRIVER_END" and not item["consumed"])["status"] == "ACTIVE"
        customer_cannot_complete = client.post(f"/api/v1/trip-operations/{booking_id}/request-end", json={})
        assert customer_cannot_complete.status_code == 403
        client.headers["Authorization"] = f"Bearer {driver_token}"
        completed = client.post(f"/api/v1/trip-operations/{booking_id}/verify-end/DRIVER_END", json={"code": end_otp})
        assert completed.status_code == 200
        assert completed.json()["status"] == "TRIP_COMPLETED"
        assert completed.json()["extra_total"] == 250
        assert next(item for item in reversed(store.memory["trip_otps"]) if item["booking_id"] == booking_id and item["purpose"] == "DRIVER_END")["status"] == "VERIFIED"

        booking_document.update({"status": "TRIP_STARTED"})
        client.headers["Authorization"] = f"Bearer {driver_token}"
        nearby_complete = client.post(f"/api/v1/trip-operations/{booking_id}/request-end", json={"latitude": 13.0005, "longitude": 77.6})
        assert nearby_complete.status_code == 200
        assert nearby_complete.json()["status"] == "TRIP_COMPLETED"
        dashboard = client.get("/api/v1/driver/dashboard")
        assert dashboard.status_code == 200
        assert dashboard.json()["completed"] == 1
        assert dashboard.json()["earnings"] == nearby_complete.json()["total"]
