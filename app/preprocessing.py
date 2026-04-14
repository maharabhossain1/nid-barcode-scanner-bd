import logging

import cv2
import numpy as np

logger = logging.getLogger(__name__)

ImageVariant = tuple[str, np.ndarray]


def _to_gray(image: np.ndarray) -> np.ndarray:
    return cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if image.ndim == 3 else image.copy()


def smart_preprocess(image: np.ndarray) -> list[ImageVariant]:
    """
    Generate up to 5 preprocessed variants optimised for PDF417 decoding.
    Ordered most-likely-to-succeed first to minimise parallel overhead.
    """
    gray = _to_gray(image)
    is_dark = np.mean(gray) < 127

    def maybe_invert(img: np.ndarray) -> np.ndarray:
        return cv2.bitwise_not(img) if is_dark else img

    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    h, w = gray.shape
    variants: list[ImageVariant] = []

    variants.append(("clahe", maybe_invert(clahe.apply(gray))))

    _, otsu = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)
    variants.append(("otsu", maybe_invert(otsu)))

    adaptive = cv2.adaptiveThreshold(
        gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 11, 2
    )
    variants.append(("adaptive", maybe_invert(adaptive)))

    if w < 1200 or h < 800:
        scale = 2.0 if w < 800 else 1.5
        scaled = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
        variants.append(("scaled_clahe", maybe_invert(clahe.apply(scaled))))

    normalised = cv2.normalize(gray, None, 0, 255, cv2.NORM_MINMAX)
    high_contrast = cv2.convertScaleAbs(normalised, alpha=1.5, beta=0)
    variants.append(("high_contrast", maybe_invert(high_contrast)))

    return variants


def detect_barcode_region(image: np.ndarray) -> np.ndarray:
    """
    Locate the PDF417 barcode region within an image.
    Tries three strategies in order: contour detection → horizontal projection → top/bottom crop.
    """
    gray = _to_gray(image)
    h, w = gray.shape

    # 1. Contour-based detection
    edges = cv2.Canny(gray, 50, 150, apertureSize=3)
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (30, 5))
    closed = cv2.dilate(cv2.morphologyEx(edges, cv2.MORPH_CLOSE, kernel), kernel, iterations=2)

    candidates: list[tuple[int, int, int, int, int]] = []
    for cnt in cv2.findContours(closed, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)[0]:
        bx, by, bw, bh = cv2.boundingRect(cnt)
        if bw / max(bh, 1) > 2.5 and bw * bh > h * w * 0.03:
            candidates.append((bw * bh, bx, by, bw, bh))

    if candidates:
        _, bx, by, bw, bh = max(candidates)
        pad = 15
        return image[
            max(0, by - pad): min(h, by + bh + pad),
            max(0, bx - pad): min(w, bx + bw + pad),
        ]

    # 2. Horizontal-projection density
    _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)
    if np.mean(binary) > 127:
        binary = cv2.bitwise_not(binary)

    proj = np.sum(binary, axis=1).astype(np.float32)
    ks = max(5, h // 100) | 1
    smoothed = cv2.GaussianBlur(proj.reshape(-1, 1), (1, ks), 0).flatten()
    dense = np.where(smoothed > np.percentile(smoothed, 80))[0]

    if dense.size:
        splits = np.where(np.diff(dense) > max(3, h // 100))[0] + 1
        best = max(np.split(dense, splits), key=len)
        if len(best) > h * 0.05:
            return image[max(0, best[0] - 15): min(h, best[-1] + 15), :]

    # 3. Top/bottom crop fallback
    def _edge_density(region: np.ndarray) -> float:
        e = cv2.Canny(_to_gray(region), 50, 150)
        return float(np.sum(e)) / max(e.size, 1)

    top = image[: int(h * 0.35), :]
    bottom = image[int(h * 0.65):, :]
    if _edge_density(bottom) > _edge_density(top):
        logger.debug("Barcode region fallback: bottom")
        return bottom
    logger.debug("Barcode region fallback: top")
    return top
