import base64
import logging

import cv2
import numpy as np
from fastapi import APIRouter, File, HTTPException, Request, UploadFile, status

from .config import get_settings
from .decoders import AVAILABLE_DECODERS
from .limiter import limiter
from .models import Base64ImageRequest, HealthResponse, ScanResponse
from .scanner import scan_image

logger = logging.getLogger(__name__)
router = APIRouter()
settings = get_settings()


def _bytes_to_image(data: bytes) -> np.ndarray:
    arr = np.frombuffer(data, np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Could not decode image — unsupported or corrupt file",
        )
    return img


def _check_size(data: bytes) -> None:
    if len(data) > settings.max_file_size:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"Payload exceeds {settings.max_file_size_mb} MB limit",
        )


def _execute_scan(image: np.ndarray, request: Request) -> ScanResponse:
    result = scan_image(image, request.app.state.executor, settings.timeout_seconds)
    if result.success:
        return result
    raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=result.error)


@router.post("/scan", response_model=ScanResponse, summary="Scan from file upload")
@limiter.limit("10/minute")
@limiter.limit("30/day")
async def scan_file(request: Request, file: UploadFile = File(...)):
    """Upload an image (multipart/form-data) and decode its PDF417 barcode."""
    if not file.filename:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No filename provided")

    ext = file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else ""
    if ext not in settings.allowed_extensions:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=f"Unsupported file type '.{ext}'. Allowed: {sorted(settings.allowed_extensions)}",
        )

    data = await file.read()
    _check_size(data)
    return _execute_scan(_bytes_to_image(data), request)


@router.post("/scan/base64", response_model=ScanResponse, summary="Scan from base64 image")
@limiter.limit("10/minute")
@limiter.limit("30/day")
async def scan_base64(request: Request, body: Base64ImageRequest):
    """Submit a base64-encoded image and decode its PDF417 barcode."""
    data = base64.b64decode(body.image)  # already validated + stripped by the model
    _check_size(data)
    return _execute_scan(_bytes_to_image(data), request)


@router.get("/health", response_model=HealthResponse, summary="Health check")
async def health():
    return HealthResponse(
        status="healthy",
        service=settings.app_name,
        version=settings.app_version,
        available_decoders=AVAILABLE_DECODERS,
    )


@router.get("/", include_in_schema=False)
async def root():
    return {
        "service": settings.app_name,
        "version": settings.app_version,
        "description": "High-performance PDF417 barcode scanner for Bangladesh NID cards",
        "endpoints": {
            "POST /scan": "Upload image file (multipart/form-data)",
            "POST /scan/base64": "Base64-encoded image",
            "GET /health": "Health check",
            "GET /docs": "Swagger UI",
            "GET /redoc": "ReDoc UI",
        },
        "available_decoders": AVAILABLE_DECODERS,
        "supported_formats": ["Machine Readable Zone (MRZ)", "Digital NID (XML)"],
        "limits": {
            "max_file_size_mb": settings.max_file_size_mb,
            "timeout_seconds": settings.timeout_seconds,
            "min_image_px": settings.min_image_dimension,
        },
    }
