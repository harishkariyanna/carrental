from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from ..core.enums import ExtraChargeType, OtpPurpose, Role
from ..dependencies import get_store, require_verified_driver
from ..repositories.trip_repository import TripRepository
from ..security import require_roles
from ..services.trip_service import TripService
from ..config import get_settings

router = APIRouter(prefix="/trip-operations", tags=["trip-operations"])


class LocationUpdate(BaseModel):
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    accuracy: float | None = Field(default=None, ge=0)


class OtpVerification(BaseModel):
    code: str = Field(pattern=r"^\d{6}$")


class ExtraChargeInput(BaseModel):
    type: ExtraChargeType
    amount: int = Field(gt=0, le=100_000)
    note: str = Field(default="", max_length=300)
    media_id: str | None = None


class EndTripInput(BaseModel):
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)


def service(store):
    return TripService(TripRepository(store), get_settings())


@router.post("/{booking_id}/location")
async def update_location(booking_id: str, payload: LocationUpdate, claims=Depends(require_verified_driver), store=Depends(get_store)):
    return await service(store).update_location(booking_id, claims["sub"], payload.latitude, payload.longitude, payload.accuracy)


@router.post("/{booking_id}/arrived")
async def arrived(booking_id: str, claims=Depends(require_verified_driver), store=Depends(get_store)):
    return await service(store).arrived(booking_id, claims["sub"])


@router.post("/{booking_id}/start-waiting")
async def start_waiting(booking_id: str, claims=Depends(require_verified_driver), store=Depends(get_store)):
    return await service(store).start_waiting(booking_id, claims["sub"])


@router.get("/{booking_id}/otp/{purpose}")
async def show_otp(booking_id: str, purpose: OtpPurpose, claims=Depends(require_roles("CUSTOMER", "DRIVER")), store=Depends(get_store)):
    return await service(store).otp_for_role(booking_id, purpose, Role(claims["role"]), claims["sub"])


@router.post("/{booking_id}/start")
async def start_trip(booking_id: str, payload: OtpVerification, claims=Depends(require_verified_driver), store=Depends(get_store)):
    return await service(store).verify_start(booking_id, claims["sub"], payload.code)


@router.post("/{booking_id}/extras", status_code=201)
async def add_extra(booking_id: str, payload: ExtraChargeInput, claims=Depends(require_verified_driver), store=Depends(get_store)):
    return await service(store).add_extra(booking_id, claims["sub"], payload.type, payload.amount, payload.note, payload.media_id)


@router.post("/{booking_id}/request-end")
async def request_end(booking_id: str, payload: EndTripInput, claims=Depends(require_verified_driver), store=Depends(get_store)):
    return await service(store).request_end(booking_id, Role.DRIVER, claims["sub"], payload.latitude, payload.longitude)


@router.post("/{booking_id}/verify-end/DRIVER_END")
async def verify_end(booking_id: str, payload: OtpVerification, claims=Depends(require_verified_driver), store=Depends(get_store)):
    return await service(store).verify_end(booking_id, Role.DRIVER, claims["sub"], OtpPurpose.DRIVER_END, payload.code)


@router.get("/{booking_id}")
async def trip_view(booking_id: str, claims=Depends(require_roles("CUSTOMER", "DRIVER", "ADMIN")), store=Depends(get_store)):
    return await service(store).trip_view(booking_id, Role(claims["role"]), claims["sub"])