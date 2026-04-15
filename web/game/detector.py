# -*- coding: utf-8 -*-
"""
web/game/detector.py
--------------------
OpenCV-based circle detector for the Parking Challenge game mode.

For each video frame it:
  1. Converts to HSV
  2. Builds a binary mask for each configured color using the calibrated HSV ranges
  3. Runs Hough Circle detection on each masked grayscale image
  4. Returns detected circles with normalized coordinates (0..1 relative to frame size)

The detector is stateless: pass a frame (numpy ndarray BGR), get back a list of dicts.
"""

from __future__ import annotations

from typing import Any

import numpy as np


# ---------------------------------------------------------------------------
# Detection helpers
# ---------------------------------------------------------------------------

def _detect_by_hough(
    frame: np.ndarray,
    mask: np.ndarray,
    w: int,
    h: int,
    min_r: int,
    max_r: int,
) -> list[tuple[int, int, int]]:
    """Hough-gradient circle detection on the masked grayscale image.

    Works well for bright-coloured circles (red, green, blue) whose edges are
    clearly visible after masking.  Returns list of (cx_px, cy_px, r_px).
    """
    import cv2 as _cv2
    masked_gray = _cv2.bitwise_and(
        _cv2.cvtColor(frame, _cv2.COLOR_BGR2GRAY), mask
    )
    blurred = _cv2.GaussianBlur(masked_gray, (9, 9), 2)
    min_dist = int(w * 0.10)

    circles = _cv2.HoughCircles(
        blurred,
        _cv2.HOUGH_GRADIENT,
        dp=1.2,
        minDist=min_dist,
        param1=80,
        param2=30,
        minRadius=min_r,
        maxRadius=max_r,
    )
    if circles is None:
        return []
    return [
        (int(round(cx)), int(round(cy)), int(round(r)))
        for cx, cy, r in circles[0]
    ]


def _detect_by_contour(
    mask: np.ndarray,
    w: int,
    h: int,
    min_r: int,
    max_r: int,
) -> list[tuple[int, int, int]]:
    """Contour-based circle detection.

    Used for **black** circles: Hough relies on Canny edge detection on the
    masked-grey image, but black pixels are near-zero after the bitwise-AND
    with the grey frame, so edges vanish.  Contour fitting works directly on
    the binary mask, where black regions appear as solid white blobs.

    Returns list of (cx_px, cy_px, r_px).
    """
    import cv2 as _cv2
    results = []
    contours, _ = _cv2.findContours(
        mask, _cv2.RETR_EXTERNAL, _cv2.CHAIN_APPROX_SIMPLE
    )
    for cnt in contours:
        area = _cv2.contourArea(cnt)
        if area < np.pi * min_r ** 2:
            continue
        (cx, cy), r = _cv2.minEnclosingCircle(cnt)
        r = int(round(r))
        if r < min_r or r > max_r:
            continue
        # Circularity check: area / (pi * r^2) should be close to 1 for a
        # filled circle.  Reject elongated or hollow shapes.
        circularity = area / max(np.pi * r * r, 1.0)
        if circularity < 0.45:
            continue
        results.append((int(round(cx)), int(round(cy)), r))
    return results


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def detect_circles(frame: np.ndarray, cfg: dict[str, Any]) -> list[dict]:
    """Detect colored circles in a BGR frame.

    Parameters
    ----------
    frame : np.ndarray
        BGR image from OpenCV (e.g. cap.read()).
    cfg : dict
        Full game config dict (as returned by web.game.config.load()).

    Returns
    -------
    list of dicts, each with:
        color       : str  ("red" | "green" | "blue" | "black")
        cx          : float  center X normalized to [0, 1]
        cy          : float  center Y normalized to [0, 1]
        radius_ratio: float  radius as fraction of frame width
        radius_px   : int    radius in pixels (useful for debug overlay)
        cx_px       : int
        cy_px       : int
    """
    try:
        import cv2
    except ImportError:
        return []

    h, w = frame.shape[:2]
    if h == 0 or w == 0:
        return []

    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    color_cfg: dict = cfg.get("colors", {})
    results: list[dict] = []

    for color_name, color_def in color_cfg.items():
        if not color_def.get("enabled", True):
            continue
        ranges = color_def.get("ranges", [])
        if not ranges:
            continue

        # Build combined mask for all ranges of this color
        mask = np.zeros((h, w), dtype=np.uint8)
        for rng in ranges:
            if len(rng) != 6:
                continue
            lo = np.array([rng[0], rng[2], rng[4]], dtype=np.uint8)
            hi = np.array([rng[1], rng[3], rng[5]], dtype=np.uint8)
            mask |= cv2.inRange(hsv, lo, hi)

        # Morphological cleanup
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN,  kernel, iterations=2)
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=2)

        min_r = max(5, int(w * 0.03))
        max_r = int(w * 0.50)

        # Black circles are dark — Hough (Canny-based) fails because edges
        # between near-black pixels are too faint.  Use contour fitting instead.
        if color_name == "black":
            found = _detect_by_contour(mask, w, h, min_r, max_r)
        else:
            found = _detect_by_hough(frame, mask, w, h, min_r, max_r)

        for cx_px, cy_px, r_px in found:
            # Verify the detected circle area is actually within the mask
            circle_mask = np.zeros((h, w), dtype=np.uint8)
            cv2.circle(circle_mask, (cx_px, cy_px), r_px, 255, -1)
            overlap = cv2.bitwise_and(mask, circle_mask)
            fill_ratio = np.count_nonzero(overlap) / max(
                np.count_nonzero(circle_mask), 1
            )
            if fill_ratio < 0.35:
                continue

            results.append({
                "color":        color_name,
                "cx":           float(cx_px) / w,
                "cy":           float(cy_px) / h,
                "radius_ratio": float(r_px)  / w,
                "cx_px":        int(cx_px),
                "cy_px":        int(cy_px),
                "radius_px":    int(r_px),
            })

    return results


def best_match(
    detections: list[dict],
    target_color: str,
    overlay_radius: float,
    center_tolerance: float,
    radius_tolerance: float,
) -> tuple[dict | None, float]:
    """Return the best matching circle for the current target and its hold progress.

    Parameters
    ----------
    detections       : output of detect_circles()
    target_color     : required color name
    overlay_radius   : required radius as fraction of frame width
    center_tolerance : allowed center offset from 0.5,0.5 (fraction of width)
    radius_tolerance : allowed radius mismatch (fraction of overlay_radius)

    Returns
    -------
    (circle_dict | None, match_quality: float 0..1)
    match_quality = 1.0 means all conditions satisfied exactly.
    None if no circle of the target color is close enough to qualify.
    """
    candidates = [d for d in detections if d["color"] == target_color]
    if not candidates:
        return None, 0.0

    r_lo = overlay_radius * (1.0 - radius_tolerance)
    r_hi = overlay_radius * (1.0 + radius_tolerance)

    best = None
    best_score = -1.0

    for c in candidates:
        # Center proximity (distance from 0.5, 0.5)
        dx = abs(c["cx"] - 0.5)
        dy = abs(c["cy"] - 0.5)
        if dx > center_tolerance or dy > center_tolerance:
            continue

        # Radius match
        if not (r_lo <= c["radius_ratio"] <= r_hi):
            continue

        # Score: higher = better centered and better radius match
        center_score  = 1.0 - (max(dx, dy) / center_tolerance)
        radius_center = (r_lo + r_hi) / 2.0
        radius_score  = 1.0 - abs(c["radius_ratio"] - radius_center) / (
            overlay_radius * radius_tolerance
        )
        score = (center_score + radius_score) / 2.0

        if score > best_score:
            best_score = score
            best = c

    return best, max(0.0, min(1.0, best_score)) if best else 0.0
