from typing import Any

from bson.binary import Binary

from ..database import Store, public


class MediaRepository:
    def __init__(self, store: Store):
        self.store = store

    async def create(self, entity_type: str, entity_id: str, filename: str, content_type: str, data: bytes, uploaded_by: str) -> dict[str, Any]:
        return await self.store.insert("media_blobs", {"entity_type": entity_type, "entity_id": entity_id, "filename": filename, "content_type": content_type, "size": len(data), "data": Binary(data), "uploaded_by": uploaded_by})

    async def get(self, media_id: str) -> dict[str, Any] | None:
        return await self.store.find_one("media_blobs", {"_id": media_id})

    async def list_for(self, entity_type: str, entity_id: str) -> list[dict[str, Any]]:
        documents = await self.store.find_many("media_blobs", {"entity_type": entity_type, "entity_id": entity_id}, limit=100)
        return [{**(public(document) or {}), "data": None} for document in documents]