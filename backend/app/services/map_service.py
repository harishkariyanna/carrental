from typing import Any

import httpx
from fastapi import HTTPException


class MapService:
    headers = {"User-Agent": "RideX/1.0 (support@ridex.in)"}

    async def geocode(self, query: str) -> list[dict[str, Any]]:
        if len(query.strip()) < 3:
            return []
        async with httpx.AsyncClient(timeout=10, headers=self.headers) as client:
            response = await client.get("https://nominatim.openstreetmap.org/search", params={"q": query, "format": "jsonv2", "limit": 5, "countrycodes": "in"})
            if response.is_error:
                raise HTTPException(status_code=503, detail="Location search is temporarily unavailable")
            return [{"label": item["display_name"], "latitude": float(item["lat"]), "longitude": float(item["lon"])} for item in response.json()]

    async def route(self, pickup_lat: float, pickup_lng: float, drop_lat: float, drop_lng: float) -> dict[str, Any]:
        url = f"https://router.project-osrm.org/route/v1/driving/{pickup_lng},{pickup_lat};{drop_lng},{drop_lat}"
        async with httpx.AsyncClient(timeout=12) as client:
            response = await client.get(url, params={"overview": "full", "geometries": "geojson"})
            if response.is_error or not response.json().get("routes"):
                raise HTTPException(status_code=503, detail="Route preview is temporarily unavailable")
            route = response.json()["routes"][0]
            return {"distance_m": route["distance"], "duration_s": route["duration"], "coordinates": [[point[1], point[0]] for point in route["geometry"]["coordinates"]]}