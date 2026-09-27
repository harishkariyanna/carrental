from datetime import datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, EmailStr, Field, field_validator, model_validator


class Role(StrEnum):
    CUSTOMER = "CUSTOMER"
    ADMIN = "ADMIN"
    DRIVER = "DRIVER"


class ServiceType(StrEnum):
    NORMAL = "NORMAL"
    AIRPORT = "AIRPORT"
    HOURLY = "HOURLY"
    OUTSTATION = "OUTSTATION"


class RegisterRequest(BaseModel):
    name: str = Field(min_length=2, max_length=80)
    email: EmailStr
    phone: str = Field(min_length=10, max_length=16)
    password: str = Field(min_length=8, max_length=128)
    role: Literal["CUSTOMER", "DRIVER"] = "CUSTOMER"
    license_number: str | None = Field(default=None, min_length=4, max_length=40)
    license_expiry: str | None = None

    @model_validator(mode="after")
    def require_driver_fields(self):
        if self.role == "DRIVER" and (not self.license_number or not self.license_expiry):
            raise ValueError("Driver licence number and expiry are required")
        return self


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class QuoteRequest(BaseModel):
    service_type: ServiceType
    pickup: str = Field(min_length=2, max_length=240)
    destination: str | None = Field(default=None, max_length=240)
    scheduled_at: datetime
    passengers: int = Field(ge=1, le=12)
    luggage: int = Field(ge=0, le=12)
    package_hours: int | None = Field(default=None, ge=1, le=24)
    round_trip: bool = False
    ac_required: bool = True
    coupon_code: str | None = Field(default=None, min_length=3, max_length=30)
    return_at: datetime | None = None
    flight_number: str | None = Field(default=None, max_length=20)
    airport_direction: Literal["PICKUP", "DROP"] | None = None
    airport_pickup_at: datetime | None = None
    pickup_latitude: float | None = Field(default=None, ge=-90, le=90)
    pickup_longitude: float | None = Field(default=None, ge=-180, le=180)
    drop_latitude: float | None = Field(default=None, ge=-90, le=90)
    drop_longitude: float | None = Field(default=None, ge=-180, le=180)

    @field_validator("destination")
    @classmethod
    def blank_destination(cls, value: str | None) -> str | None:
        return value.strip() if value and value.strip() else None

    @field_validator("coupon_code")
    @classmethod
    def normalize_coupon_code(cls, value: str | None) -> str | None:
        return value.strip().upper() if value and value.strip() else None

    @model_validator(mode="after")
    def validate_trip_timing(self):
        if self.service_type in {ServiceType.NORMAL, ServiceType.OUTSTATION}:
            coordinates = (self.pickup_latitude, self.pickup_longitude, self.drop_latitude, self.drop_longitude)
            if any(value is None for value in coordinates):
                raise ValueError("Select geocoded pickup and destination locations for distance pricing")
        if self.service_type == ServiceType.OUTSTATION and self.round_trip:
            if not self.return_at:
                raise ValueError("Return date and time are required for an outstation round trip")
            if self.return_at <= self.scheduled_at:
                raise ValueError("Return date and time must be after departure")
        return self


class BookingCreate(BaseModel):
    quote_id: str
    vehicle_id: str
    passenger_name: str = Field(min_length=2, max_length=80)
    passenger_phone: str = Field(min_length=10, max_length=16)
    special_instructions: str = Field(default="", max_length=500)


class VehicleInput(BaseModel):
    name: str = Field(min_length=2, max_length=100)
    registration_number: str = Field(min_length=8, max_length=12, pattern=r"^[A-Za-z]{2}\d{2}[A-Za-z]{1,3}\d{4}$")
    category: str
    seats: int = Field(ge=1, le=20)
    luggage: int = Field(ge=0, le=20)
    transmission: str
    fuel: str
    has_ac: bool = True
    base_rate: int = Field(ge=0)
    local_base_fare: int = Field(default=500, ge=0)
    local_included_km: int = Field(default=5, ge=0, le=100)
    local_per_km: int = Field(default=18, ge=0)
    local_waiting_grace_minutes: int = Field(default=15, ge=0, le=60)
    local_waiting_rate_per_minute: int = Field(default=5, ge=0)
    outstation_one_way_base_fare: int = Field(default=1800, ge=0)
    outstation_one_way_per_km: int = Field(default=18, ge=0)
    outstation_one_way_included_km_per_day: int = Field(default=150, ge=1, le=1000)
    outstation_one_way_extra_km_rate: int = Field(default=18, ge=0)
    outstation_one_way_driver_bata_per_day: int = Field(default=500, ge=0)
    outstation_one_way_base_fare_non_ac: int = Field(default=1600, ge=0)
    outstation_one_way_extra_km_rate_non_ac: int = Field(default=16, ge=0)
    outstation_round_trip_day_rate: int = Field(default=3000, ge=0)
    outstation_included_km_per_day: int = Field(default=250, ge=1, le=1000)
    outstation_extra_km_rate: int = Field(default=18, ge=0)
    driver_bata_per_day: int = Field(default=500, ge=0)
    outstation_round_trip_day_rate_non_ac: int = Field(default=2700, ge=0)
    outstation_extra_km_rate_non_ac: int = Field(default=16, ge=0)
    image: str = ""
    status: str = "AVAILABLE"

    @field_validator("registration_number")
    @classmethod
    def normalize_registration_number(cls, value: str) -> str:
        return value.replace(" ", "").replace("-", "").upper()


class VehicleUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=100)
    registration_number: str | None = Field(default=None, min_length=8, max_length=12, pattern=r"^[A-Za-z]{2}\d{2}[A-Za-z]{1,3}\d{4}$")
    category: str | None = None
    seats: int | None = Field(default=None, ge=1, le=20)
    luggage: int | None = Field(default=None, ge=0, le=20)
    transmission: str | None = None
    fuel: str | None = None
    has_ac: bool | None = None
    base_rate: int | None = Field(default=None, ge=0)
    local_base_fare: int | None = Field(default=None, ge=0)
    local_included_km: int | None = Field(default=None, ge=0, le=100)
    local_per_km: int | None = Field(default=None, ge=0)
    local_waiting_grace_minutes: int | None = Field(default=None, ge=0, le=60)
    local_waiting_rate_per_minute: int | None = Field(default=None, ge=0)
    outstation_one_way_base_fare: int | None = Field(default=None, ge=0)
    outstation_one_way_per_km: int | None = Field(default=None, ge=0)
    outstation_one_way_included_km_per_day: int | None = Field(default=None, ge=1, le=1000)
    outstation_one_way_extra_km_rate: int | None = Field(default=None, ge=0)
    outstation_one_way_driver_bata_per_day: int | None = Field(default=None, ge=0)
    outstation_one_way_base_fare_non_ac: int | None = Field(default=None, ge=0)
    outstation_one_way_extra_km_rate_non_ac: int | None = Field(default=None, ge=0)
    outstation_round_trip_day_rate: int | None = Field(default=None, ge=0)
    outstation_included_km_per_day: int | None = Field(default=None, ge=1, le=1000)
    outstation_extra_km_rate: int | None = Field(default=None, ge=0)
    driver_bata_per_day: int | None = Field(default=None, ge=0)
    outstation_round_trip_day_rate_non_ac: int | None = Field(default=None, ge=0)
    outstation_extra_km_rate_non_ac: int | None = Field(default=None, ge=0)
    image: str | None = None
    status: Literal["AVAILABLE", "BOOKED", "ON_TRIP", "MAINTENANCE", "INACTIVE"] | None = None

    @field_validator("registration_number")
    @classmethod
    def normalize_optional_registration_number(cls, value: str | None) -> str | None:
        return value.replace(" ", "").replace("-", "").upper() if value else value


class UserUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=80)
    phone: str | None = Field(default=None, min_length=10, max_length=16)
    status: Literal["ACTIVE", "INACTIVE"] | None = None


class CustomerProfileUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=80)
    phone: str | None = Field(default=None, min_length=10, max_length=16)


class SavedLocationInput(BaseModel):
    label: str = Field(min_length=2, max_length=40)
    address: str = Field(min_length=3, max_length=300)
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)


class DriverCreate(BaseModel):
    name: str = Field(min_length=2, max_length=80)
    email: EmailStr
    phone: str = Field(min_length=10, max_length=16)
    password: str = Field(min_length=8, max_length=128)
    license_number: str = Field(min_length=4, max_length=40)
    license_expiry: str


class DriverUpdate(BaseModel):
    status: Literal["ACTIVE", "INACTIVE"] | None = None
    availability: Literal["AVAILABLE", "OFFLINE"] | None = None
    verification_status: Literal["PENDING", "VERIFIED", "REJECTED"] | None = None
    license_number: str | None = Field(default=None, min_length=4, max_length=40)
    license_expiry: str | None = None
    assigned_vehicle_id: str | None = None


class PricingRuleInput(BaseModel):
    service_type: ServiceType
    vehicle_category: str = Field(min_length=2, max_length=60)
    base_fare: int = Field(ge=0)
    per_km: int = Field(ge=0)
    extra_hour: int = Field(ge=0)
    driver_allowance: int = Field(ge=0)
    tax_percent: float = Field(ge=0, le=100)
    included_hours: int = Field(default=4, ge=1, le=24)
    round_trip_multiplier: float = Field(default=2, ge=1, le=10)
    status: Literal["DRAFT", "ACTIVE", "INACTIVE"] = "DRAFT"


class CouponInput(BaseModel):
    code: str = Field(min_length=3, max_length=30)
    discount_type: Literal["PERCENTAGE", "FIXED"]
    value: int = Field(gt=0)
    minimum_booking: int = Field(ge=0)
    maximum_discount: int = Field(ge=0)
    valid_from: datetime
    valid_to: datetime
    usage_limit: int = Field(gt=0)
    scope: Literal["PERSONAL", "PUBLIC"] = "PUBLIC"
    customer_id: str | None = None
    status: Literal["ACTIVE", "INACTIVE"] = "ACTIVE"

    @model_validator(mode="after")
    def validate_scope(self):
        if self.discount_type == "PERCENTAGE" and self.value > 100:
            raise ValueError("Percentage discount cannot exceed 100")
        if self.valid_to <= self.valid_from:
            raise ValueError("Coupon expiry must be after its start time")
        if self.scope == "PERSONAL" and not self.customer_id:
            raise ValueError("Select a customer for a personal coupon")
        if self.scope == "PUBLIC":
            self.customer_id = None
        return self


class ReviewModeration(BaseModel):
    status: Literal["PUBLISHED", "HIDDEN", "FLAGGED"]
    reason: str = Field(default="", max_length=300)


class PlatformSettingsUpdate(BaseModel):
    platform_name: str | None = Field(default=None, min_length=2, max_length=80)
    support_email: EmailStr | None = None
    support_phone: str | None = Field(default=None, min_length=8, max_length=20)
    cancellation_hours: int | None = Field(default=None, ge=0, le=168)
    cancellation_fee_percent: float | None = Field(default=None, ge=0, le=100)
    google_review_url: str | None = Field(default=None, max_length=500)
    maintenance_mode: bool | None = None
    upi_id: str | None = Field(default=None, min_length=3, max_length=100)
    airport_advance_type: Literal["PERCENTAGE", "FIXED"] | None = None
    airport_advance_value: int | None = Field(default=None, ge=0)
    outstation_advance_type: Literal["PERCENTAGE", "FIXED"] | None = None
    outstation_advance_value: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def validate_advance_values(self):
        if self.airport_advance_type == "PERCENTAGE" and self.airport_advance_value is not None and self.airport_advance_value > 100:
            raise ValueError("Airport advance percentage cannot exceed 100")
        if self.outstation_advance_type == "PERCENTAGE" and self.outstation_advance_value is not None and self.outstation_advance_value > 100:
            raise ValueError("Outstation advance percentage cannot exceed 100")
        return self


class DriverAssignment(BaseModel):
    driver_id: str


class VehicleDriverAssignment(BaseModel):
    driver_id: str | None = None


class TripTransition(BaseModel):
    action_id: str = Field(min_length=8, max_length=80)


class ReviewCreate(BaseModel):
    rating: int = Field(ge=1, le=5)
    comment: str = Field(min_length=3, max_length=1000)


class ApiMessage(BaseModel):
    message: str
    data: dict[str, Any] | None = None
