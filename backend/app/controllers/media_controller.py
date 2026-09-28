from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Response, UploadFile

from ..core.enums import MediaEntityType
from ..dependencies import get_store, require_active_driver, require_active_roles
from ..repositories.media_repository import MediaRepository
from ..security import require_roles
from ..services.media_service import MediaService

router = APIRouter(tags=["media"])


@router.post("/admin/media/{entity_type}/{entity_id}", status_code=201)
async def upload_admin_media(entity_type: MediaEntityType, entity_id: str, file: UploadFile, admin=Depends(require_roles("ADMIN")), store=Depends(get_store)):
    media = await MediaService(MediaRepository(store)).upload(entity_type, entity_id, file, admin["sub"])
    if entity_type == MediaEntityType.VEHICLE:
        vehicle = await store.find_one("vehicles", {"_id": entity_id})
        if not vehicle:
            raise HTTPException(status_code=404, detail="Vehicle not found")
        image_ids = [*vehicle.get("image_ids", []), media["id"]]
        await store.update("vehicles", entity_id, {"image_ids": image_ids, "image": media["url"]})
    elif entity_type == MediaEntityType.DRIVER:
        user = await store.find_one("users", {"_id": entity_id, "role": "DRIVER"})
        if not user:
            raise HTTPException(status_code=404, detail="Driver not found")
        await store.update("users", entity_id, {"profile_image_id": media["id"]})
    return media


@router.post("/me/profile-image", status_code=201)
async def upload_profile_image(file: UploadFile, claims=Depends(require_active_roles("CUSTOMER", "DRIVER")), store=Depends(get_store)):
    entity_type = MediaEntityType.CUSTOMER if claims["role"] == "CUSTOMER" else MediaEntityType.DRIVER
    media = await MediaService(MediaRepository(store)).upload(entity_type, claims["sub"], file, claims["sub"])
    await store.update("users", claims["sub"], {"profile_image_id": media["id"]})
    return media


@router.post("/driver/documents/{document_type}", status_code=201)
async def upload_driver_document(document_type: Literal["LICENSE", "VEHICLE_PHOTO", "ADDRESS_PROOF"], file: UploadFile, claims=Depends(require_active_driver), store=Depends(get_store)):
    profile = await store.find_one("drivers", {"user_id": claims["sub"]})
    if not profile:
        raise HTTPException(status_code=404, detail="Driver profile not found")
    media = await MediaService(MediaRepository(store)).upload_document(document_type, claims["sub"], file)
    documents = dict(profile.get("documents", {}))
    if document_type == "VEHICLE_PHOTO":
        documents[document_type] = [*documents.get(document_type, []), media["id"]]
    else:
        documents[document_type] = media["id"]
    complete = all(documents.get(required) for required in ("LICENSE", "VEHICLE_PHOTO", "ADDRESS_PROOF"))
    await store.update("drivers", profile["_id"], {"documents": documents, "documents_status": "SUBMITTED" if complete else "INCOMPLETE", "verification_status": "PENDING"})
    return {**media, "documents_status": "SUBMITTED" if complete else "INCOMPLETE"}

@router.post("/trip-operations/{booking_id}/evidence", status_code=201)
async def upload_trip_evidence(booking_id: str, file: UploadFile, claims=Depends(require_active_driver), store=Depends(get_store)):
    booking = await store.find_one("bookings", {"_id": booking_id, "driver_id": claims["sub"]})
    if not booking:
        raise HTTPException(status_code=404, detail="Assigned trip not found")
    if booking["status"] not in {"DRIVER_ARRIVED", "TRIP_STARTED"}:
        raise HTTPException(status_code=409, detail="Evidence can only be uploaded during an active trip")
    return await MediaService(MediaRepository(store)).upload(MediaEntityType.TRIP_EXTRA, booking_id, file, claims["sub"])


@router.get("/media/{media_id}")
async def media_blob(media_id: str, store=Depends(get_store)):
    document = await MediaRepository(store).get(media_id)
    if not document:
        raise HTTPException(status_code=404, detail="Media not found")
    return Response(content=bytes(document["data"]), media_type=document["content_type"], headers={"Cache-Control": "public, max-age=86400"})