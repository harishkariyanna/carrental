from fastapi import APIRouter, Query

from ..services.map_service import MapService

router = APIRouter(prefix="/maps", tags=["maps"])


@router.get("/geocode")
async def geocode(q: str = Query(min_length=3, max_length=200)):
    return await MapService().geocode(q)


@router.get("/reverse")
async def reverse(latitude: float, longitude: float):
    return await MapService().reverse(latitude, longitude)


@router.get("/route")
async def route(pickup_lat: float, pickup_lng: float, drop_lat: float, drop_lng: float):
    return await MapService().route(pickup_lat, pickup_lng, drop_lat, drop_lng)