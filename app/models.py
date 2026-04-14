import base64
from typing import Optional

from pydantic import BaseModel, field_validator


class Base64ImageRequest(BaseModel):
    image: str

    @field_validator("image")
    @classmethod
    def validate_and_strip(cls, v: str) -> str:
        payload = v.split("base64,")[1] if "base64," in v else v
        try:
            base64.b64decode(payload, validate=True)
        except Exception:
            raise ValueError("Invalid base64 image data")
        return payload


class NIDData(BaseModel):
    name: Optional[str] = None
    nid_number: Optional[str] = None
    old_nid: Optional[str] = None
    date_of_birth: Optional[str] = None
    blood_group: Optional[str] = None
    issue_date: Optional[str] = None
    pin: Optional[str] = None
    type: Optional[str] = None
    version: Optional[str] = None
    fingerprint: Optional[str] = None


class ScanResponse(BaseModel):
    success: bool
    message: Optional[str] = None
    data: Optional[str] = None
    parsed_data: Optional[NIDData] = None
    barcode_type: Optional[str] = None
    format: Optional[str] = None
    processing_time: Optional[float] = None
    method: Optional[str] = None
    error: Optional[str] = None
    suggestions: Optional[list[str]] = None


class HealthResponse(BaseModel):
    status: str
    service: str
    version: str
    available_decoders: list[str]
