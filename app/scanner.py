import logging
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError, as_completed

import cv2
import numpy as np

from .decoders import try_decode
from .models import ScanResponse
from .parsers import parse_barcode_data
from .preprocessing import detect_barcode_region, smart_preprocess

logger = logging.getLogger(__name__)

# Blur: below this score the image is truly blank/solid — reject immediately.
# Above this but below _BLUR_SOFT_WARN → attempt decode but inject blur hint on failure.
_BLUR_HARD_REJECT = 5.0
_BLUR_SOFT_WARN = 80.0

_DECODE_SUGGESTIONS = [
    "Ensure the barcode is clearly visible and not damaged",
    "Try better lighting without glare or shadows",
    "Use a higher resolution image",
    "Make sure the entire barcode is within the frame",
    "Confirm the barcode is a valid PDF417 format",
]

_ROTATION_CODES = [
    ("rot90", cv2.ROTATE_90_CLOCKWISE),
    ("rot180", cv2.ROTATE_180),
    ("rot270", cv2.ROTATE_90_COUNTERCLOCKWISE),
]


def _blur_score(image: np.ndarray) -> float:
    """Laplacian variance — higher = sharper. < 5 = blank/solid. < 80 = probably blurry."""
    gray = image if image.ndim == 2 else cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    return float(cv2.Laplacian(gray, cv2.CV_64F).var())


def _is_clipped(image: np.ndarray) -> bool:
    """True if strong edge activity at image borders — barcode likely cut off."""
    gray = image if image.ndim == 2 else cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    edges = cv2.Canny(gray, 50, 150)
    h, w = edges.shape
    margin = max(5, min(h, w) // 15)
    border_pixels = np.concatenate([
        edges[:margin, :].ravel(),
        edges[-margin:, :].ravel(),
        edges[:, :margin].ravel(),
        edges[:, -margin:].ravel(),
    ])
    return float(np.mean(border_pixels)) > 8.0


def _run_decode(
    variants: list[tuple[str, np.ndarray]],
    executor: ThreadPoolExecutor,
    timeout: float,
) -> tuple[str, str] | None:
    """Submit variants to thread pool. Returns (method_label, raw_data) or None."""
    futures = {executor.submit(try_decode, name, img): name for name, img in variants}
    try:
        for future in as_completed(futures, timeout=timeout):
            result = future.result()
            if result is not None:
                for f in futures:
                    f.cancel()
                return result
    except FuturesTimeoutError:
        pass
    finally:
        for f in futures:
            f.cancel()
    return None


def scan_image(image: np.ndarray, executor: ThreadPoolExecutor, timeout: int) -> ScanResponse:
    """Full pipeline: validate → blur check → detect region → decode → rotations → parse."""
    t0 = time.perf_counter()

    if image.size == 0:
        return ScanResponse(
            success=False,
            error="Empty image",
            suggestions=["Provide a valid image file"],
        )

    h, w = image.shape[:2]
    if h < 200 or w < 200:
        return ScanResponse(
            success=False,
            error=f"Image too small ({w}×{h}px)",
            suggestions=["Minimum image size is 200×200 px"],
        )

    score = _blur_score(image)
    if score < _BLUR_HARD_REJECT:
        logger.warning("Image rejected — appears blank (blur_score=%.1f)", score)
        return ScanResponse(
            success=False,
            error="Image appears blank or completely uniform — no visual content to scan",
            suggestions=[
                "Upload a real photo of the NID card",
                "Ensure the image is not a solid colour or empty file",
            ],
        )

    logger.info("Scanning %d×%d image (blur_score=%.1f)", w, h, score)

    # ── Initial orientation ────────────────────────────────────────────────────
    region = detect_barcode_region(image)
    variants = smart_preprocess(region)
    logger.debug("Submitting %d preprocessing strategies (initial orientation)", len(variants))

    # Give 65% of total timeout to the initial pass
    initial_timeout = timeout * 0.65
    result = _run_decode(variants, executor, initial_timeout)

    if result is None:
        # ── Rotation attempts ──────────────────────────────────────────────────
        elapsed = time.perf_counter() - t0
        remaining = timeout - elapsed

        if remaining > 2.0:
            logger.info("Initial decode failed — trying rotations (%.1fs remaining)", remaining)
            per_rotation = remaining / len(_ROTATION_CODES)

            for rot_label, rot_code in _ROTATION_CODES:
                rotated = cv2.rotate(image, rot_code)
                rot_region = detect_barcode_region(rotated)
                rot_variants = [
                    (f"{rot_label}_{name}", img)
                    for name, img in smart_preprocess(rot_region)
                ]
                result = _run_decode(rot_variants, executor, per_rotation)
                if result is not None:
                    logger.info("Decoded after %s", rot_label)
                    break

    if result is not None:
        method, raw = result
        elapsed = round(time.perf_counter() - t0, 3)
        parsed, barcode_type = parse_barcode_data(raw)
        logger.info("Decoded via %s in %.3fs (type=%s)", method, elapsed, barcode_type)
        return ScanResponse(
            success=True,
            data=raw,
            parsed_data=parsed,
            barcode_type=barcode_type,
            format="PDF417",
            processing_time=elapsed,
            method=method,
        )

    # ── All attempts failed — build contextual error ───────────────────────────
    elapsed_total = time.perf_counter() - t0
    if elapsed_total >= timeout * 0.95:
        return ScanResponse(
            success=False,
            error=f"Processing timed out after {timeout}s",
            processing_time=round(elapsed_total, 3),
            suggestions=[
                "Image may be too complex or very high resolution",
                "Try a smaller/cropped image focused on the barcode",
                "Ensure good lighting and no motion blur",
            ],
        )

    suggestions: list[str] = []

    if score < _BLUR_SOFT_WARN:
        suggestions.append(
            f"Image appears blurry (sharpness score {score:.0f}/80) — "
            "use a focused, well-lit photo"
        )

    if _is_clipped(image):
        suggestions.append(
            "Barcode may be partially cut off — ensure the entire barcode is within the frame"
        )

    suggestions.extend(_DECODE_SUGGESTIONS)

    return ScanResponse(
        success=False,
        error="Could not decode barcode",
        processing_time=round(elapsed_total, 3),
        suggestions=suggestions[:6],
    )
