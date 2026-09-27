from typing import Any

from fastapi import HTTPException, UploadFile

from ..core.enums import MediaEntityType
from ..repositories.media_repository import MediaRepository


class MediaService:
    allowed_types = {"image/jpeg", "image/png", "image/webp"}
    max_size = 5 * 1024 * 1024

    def __init__(self, repository: MediaRepository):
        self.repository = repository

    async def upload(self, entity_type: MediaEntityType, entity_id: str, file: UploadFile, uploaded_by: str) -> dict[str, Any]:
        if file.content_type not in self.allowed_types:
            raise HTTPException(status_code=422, detail="Only JPEG, PNG, and WebP images are allowed")
        data = await file.read(self.max_size + 1)
        if not data or len(data) > self.max_size:
            raise HTTPException(status_code=422, detail="Image must be between 1 byte and 5 MB")
        signatures = {"image/jpeg": (b"\xff\xd8\xff",), "image/png": (b"\x89PNG\r\n\x1a\n",), "image/webp": (b"RIFF",)}
        if not any(data.startswith(signature) for signature in signatures[file.content_type]):
            raise HTTPException(status_code=422, detail="Image signature does not match its content type")
        media = await self.repository.create(entity_type.value, entity_id, file.filename or "image", file.content_type, data, uploaded_by)
        return {"id": media["_id"], "entity_type": entity_type.value, "entity_id": entity_id, "filename": media["filename"], "content_type": media["content_type"], "size": media["size"], "url": f"/api/v1/media/{media['_id']}"}

    async def upload_document(self, document_type: str, driver_id: str, file: UploadFile) -> dict[str, Any]:
        allowed_types = {*self.allowed_types, "application/pdf"}
        if file.content_type not in allowed_types:
            raise HTTPException(status_code=422, detail="Only PDF, JPEG, PNG, and WebP documents are allowed")
        data = await file.read(self.max_size + 1)
        if not data or len(data) > self.max_size:
            raise HTTPException(status_code=422, detail="Document must be between 1 byte and 5 MB")
        signatures = {"application/pdf": (b"%PDF",), "image/jpeg": (b"\xff\xd8\xff",), "image/png": (b"\x89PNG\r\n\x1a\n",), "image/webp": (b"RIFF",)}
        if not any(data.startswith(signature) for signature in signatures[file.content_type]):
            raise HTTPException(status_code=422, detail="Document signature does not match its content type")
        media = await self.repository.create(f"DRIVER_{document_type}", driver_id, file.filename or "document", file.content_type, data, driver_id)
        return {"id": media["_id"], "document_type": document_type, "filename": media["filename"], "content_type": media["content_type"], "size": media["size"], "url": f"/api/v1/media/{media['_id']}"}