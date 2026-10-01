from html import unescape
import json
import re
from typing import Any
from urllib.parse import urljoin

import httpx
from fastapi import HTTPException


class GoogleReviewRefreshService:
    maps_url = "https://www.google.com/maps/search/Konanur+Tours+and+Travels?hl=en"
    profile_url = "https://share.google/008bQrAOrtyDw5XR2"
    business_name = "Konanur Tours and Travels"
    place_id = "ChIJiVvOuNwbrjsRDAOYVBwSl6M"

    @staticmethod
    def parse_place_data(data: str) -> dict[str, Any]:
        pattern = re.compile(
            r'(?P<url>https://search\.google\.com/local/reviews\?placeid\\u003dChIJiVvOuNwbrjsRDAOYVBwSl6M[^\"]*)",'
            r'"(?P<label_count>\d+) reviews?"[^\]]*\],null,null,null,'
            r'(?P<rating>[0-9.]+),(?P<review_count>\d+)\]'
        )
        match = pattern.search(data)
        if not match or GoogleReviewRefreshService.business_name not in data:
            raise HTTPException(status_code=502, detail="Google Maps did not return the expected review summary")
        rating = float(match.group("rating"))
        review_count = int(match.group("review_count"))
        if review_count != int(match.group("label_count")) or not 0 <= rating <= 5:
            raise HTTPException(status_code=502, detail="Google Maps returned an invalid review summary")
        address_match = re.search(r'"(No\. 87, Konanur Tours and Travels,[^\"]+)"', data)
        review_url = json.loads(f'"{match.group("url")}"')
        address = json.loads(f'"{address_match.group(1)}"') if address_match else "Budigere, Bangalore, Karnataka"
        return {
            "business_name": GoogleReviewRefreshService.business_name,
            "place_id": GoogleReviewRefreshService.place_id,
            "profile_url": GoogleReviewRefreshService.profile_url,
            "review_url": review_url,
            "rating": rating,
            "review_count": review_count,
            "address": address,
        }

    async def fetch(self) -> dict[str, Any]:
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/140 Safari/537.36"}
        async with httpx.AsyncClient(timeout=20, headers=headers, follow_redirects=True) as client:
            last_error: HTTPException | None = None
            for _ in range(3):
                page = await client.get(self.maps_url)
                if page.is_error:
                    last_error = HTTPException(status_code=503, detail="Google Maps is temporarily unavailable")
                    continue
                data_path = re.search(r'(search\?tbm=map&amp;[^\"\'<]+)', page.text)
                if not data_path:
                    last_error = HTTPException(status_code=502, detail="Google Maps review data could not be located")
                    continue
                data_url = urljoin("https://www.google.com/", unescape(data_path.group(1)))
                response = await client.get(data_url, headers={**headers, "Referer": "https://www.google.com/maps/"})
                if response.is_error:
                    last_error = HTTPException(status_code=503, detail="Google Maps review data is temporarily unavailable")
                    continue
                try:
                    return self.parse_place_data(response.text)
                except HTTPException as exc:
                    last_error = exc
            raise last_error or HTTPException(status_code=503, detail="Google Maps is temporarily unavailable")