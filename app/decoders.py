import logging

import cv2
import numpy as np
from PIL import Image

logger = logging.getLogger(__name__)

try:
    from pyzbar import pyzbar as _pyzbar
    _PYZBAR_AVAILABLE = True
except ImportError:
    _PYZBAR_AVAILABLE = False

try:
    from pylibdmtx import pylibdmtx as _pylibdmtx
    _PYLIBDMTX_AVAILABLE = True
except ImportError:
    _PYLIBDMTX_AVAILABLE = False

from pdf417decoder import PDF417Decoder


def _pyzbar_decode(image: np.ndarray) -> str | None:
    try:
        hits = _pyzbar.decode(image, symbols=[_pyzbar.ZBarSymbol.PDF417])
        if hits:
            return hits[0].data.decode("utf-8", errors="ignore")
    except Exception as exc:
        logger.debug("pyzbar: %s", exc)
    return None


def _pylibdmtx_decode(image: np.ndarray) -> str | None:
    try:
        hits = _pylibdmtx.decode(image, timeout=2000)
        if hits:
            return hits[0].data.decode("utf-8", errors="ignore")
    except Exception as exc:
        logger.debug("pylibdmtx: %s", exc)
    return None


def _pdf417decoder_decode(image: np.ndarray) -> str | None:
    try:
        pil = (
            Image.fromarray(image, mode="L")
            if image.ndim == 2
            else Image.fromarray(cv2.cvtColor(image, cv2.COLOR_BGR2RGB))
        )
        dec = PDF417Decoder(pil)
        if dec.decode() > 0:
            return dec.barcode_data_index_to_string(0)
    except Exception as exc:
        logger.debug("pdf417decoder: %s", exc)
    return None


# Built at import time — only includes decoders whose libraries are present
_DECODERS: list[tuple[str, object]] = (
    ([("pyzbar", _pyzbar_decode)] if _PYZBAR_AVAILABLE else [])
    + ([("pylibdmtx", _pylibdmtx_decode)] if _PYLIBDMTX_AVAILABLE else [])
    + [("pdf417decoder", _pdf417decoder_decode)]
)

AVAILABLE_DECODERS: list[str] = [name for name, _ in _DECODERS]


def try_decode(strategy: str, image: np.ndarray) -> tuple[str, str] | None:
    """Try each decoder in priority order. Returns (method_label, raw_data) or None."""
    for name, fn in _DECODERS:
        result = fn(image)
        if result:
            return (f"{name}+{strategy}", result)
    return None
