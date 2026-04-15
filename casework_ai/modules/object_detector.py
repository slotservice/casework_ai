"""
Object Detection / Geometry Extraction Module
Detects casework items (cabinets, sinks, fixtures, shelving) from elevation images.

Strategy:
1. Split the elevation strip into sub-views (separate elevation segments)
2. Within each sub-view, calibrate scale from cabinet height
3. Find vertical boundary lines to identify individual cabinets
4. Classify each cabinet by analyzing interior features (doors, drawers, etc.)
"""

import logging
import math
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from enum import Enum

import numpy as np

logger = logging.getLogger(__name__)

try:
    import cv2
    HAS_CV2 = True
except ImportError:
    HAS_CV2 = False


class CaseworkType(Enum):
    BASE_CABINET = "base_cabinet"
    WALL_CABINET = "wall_cabinet"
    SINK = "sink"
    SINK_CABINET = "sink_cabinet"
    DRAWER_UNIT = "drawer_unit"
    OPEN_SHELF = "open_shelf"
    COUNTERTOP = "countertop"
    PEGBOARD = "pegboard"
    FUME_HOOD = "fume_hood"
    FIXTURE = "fixture"
    FILLER = "filler"
    END_PANEL = "end_panel"
    UNKNOWN = "unknown"


@dataclass
class DetectedObject:
    obj_id: int
    casework_type: CaseworkType
    bbox: Tuple[int, int, int, int]  # (x, y, w, h) in pixels
    center: Tuple[int, int]
    confidence: float
    estimated_width_inches: Optional[float] = None
    estimated_height_inches: Optional[float] = None
    features: Dict = field(default_factory=dict)
    notes: str = ""
    subview_index: int = 0


@dataclass
class SubView:
    """A separate elevation segment within the full strip."""
    index: int
    x_start: int
    x_end: int
    width_px: int
    content_top: int
    content_bottom: int
    content_height_px: int
    cabinets: List[DetectedObject] = field(default_factory=list)


@dataclass
class DetectionResult:
    objects: List[DetectedObject] = field(default_factory=list)
    scale_factor: float = 1.0  # pixels per inch
    countertop_line_y: Optional[int] = None
    floor_line_y: Optional[int] = None
    total_width_inches: float = 0
    subviews: List[SubView] = field(default_factory=list)
    debug_image: Optional[np.ndarray] = None
    drawing_scale: str = ""

    @property
    def cabinet_count(self) -> int:
        return len([o for o in self.objects if "cabinet" in o.casework_type.value or o.casework_type == CaseworkType.DRAWER_UNIT])

    @property
    def high_confidence_count(self) -> int:
        return len([o for o in self.objects if o.confidence >= 0.7])


class ObjectDetector:
    """Detects casework items using band-based vertical boundary analysis."""

    def __init__(self, config=None):
        self.config = config
        self._next_id = 1

        # Architectural drawing scales (drawing_inch : real_inch)
        # Common lab casework elevation scales
        self.common_scales = {
            "1/4\"=1'-0\"": 48,
            "3/16\"=1'-0\"": 64,
            "3/8\"=1'-0\"": 32,
            "1/2\"=1'-0\"": 24,
            "1/8\"=1'-0\"": 96,
        }

        # Standard Mott cabinet heights
        self.standing_height = 34.75  # inches
        self.total_visible_height = 38.0  # including countertop + toe kick

    def detect(self, image: np.ndarray, scale_hint: float = 0.0,
               dpi: int = 300) -> DetectionResult:
        if not HAS_CV2:
            return DetectionResult()

        self._next_id = 1
        result = DetectionResult()

        h, w = image.shape[:2]
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if len(image.shape) == 3 else image.copy()
        _, binary = cv2.threshold(gray, 200, 255, cv2.THRESH_BINARY_INV)

        # Step 1: Split into sub-views (separate elevation segments)
        subviews = self._find_subviews(binary, h, w)
        result.subviews = subviews
        logger.info(f"Found {len(subviews)} sub-views in elevation strip")

        # Step 2: Calibrate scale from cabinet height
        result.scale_factor = self._calibrate_scale(subviews, dpi)
        ppi = result.scale_factor
        logger.info(f"Calibrated scale: {ppi:.2f} px/inch, drawing scale: {result.drawing_scale}")

        # Step 3: Detect cabinets in each sub-view
        for sv in subviews:
            cabinets = self._detect_cabinets_in_subview(binary, gray, sv, ppi)
            sv.cabinets = cabinets
            result.objects.extend(cabinets)

        # Sort left to right across entire strip
        result.objects.sort(key=lambda o: o.bbox[0])

        # Calculate total width
        if result.objects:
            widths = [o.estimated_width_inches for o in result.objects if o.estimated_width_inches]
            result.total_width_inches = sum(widths)

        # Generate debug image
        result.debug_image = self._create_debug_image(image, result)

        logger.info(f"Detection complete: {len(result.objects)} objects ({result.high_confidence_count} high confidence)")
        return result

    def _find_subviews(self, binary: np.ndarray, h: int, w: int) -> List[SubView]:
        """Split the elevation strip into separate sub-views using vertical whitespace gaps."""
        v_proj = np.sum(binary > 0, axis=0)
        gap_threshold = h * 0.05

        # Find vertical gaps
        gaps = []
        in_gap = False
        gap_start = 0
        for i in range(w):
            is_white = v_proj[i] < gap_threshold
            if is_white and not in_gap:
                gap_start = i
                in_gap = True
            elif not is_white and in_gap:
                if i - gap_start > 8:
                    gaps.append((gap_start, i))
                in_gap = False

        # Create bands between gaps
        bands = []
        prev = 0
        for gs, ge in gaps:
            if gs > prev + 30:
                bands.append((prev, gs))
            prev = ge
        if prev < w - 30:
            bands.append((prev, w))

        # Build SubView objects with content bounds
        subviews = []
        for idx, (x_start, x_end) in enumerate(bands):
            band_strip = binary[:, x_start:x_end]
            h_proj = np.sum(band_strip > 0, axis=1)

            content_rows = np.where(h_proj > (x_end - x_start) * 0.05)[0]
            if len(content_rows) < 10:
                continue

            content_top = int(content_rows[0])
            content_bottom = int(content_rows[-1])
            content_height = content_bottom - content_top

            if content_height < 30:
                continue

            sv = SubView(
                index=idx,
                x_start=x_start,
                x_end=x_end,
                width_px=x_end - x_start,
                content_top=content_top,
                content_bottom=content_bottom,
                content_height_px=content_height,
            )
            subviews.append(sv)

        return subviews

    def _calibrate_scale(self, subviews: List[SubView], dpi: int) -> float:
        """Calibrate the pixel-to-inch scale from known cabinet dimensions."""
        if not subviews:
            return dpi / 48.0  # default 1/4"=1'-0"

        # Use the tallest consistent content height as the cabinet height
        heights = [sv.content_height_px for sv in subviews if sv.width_px > 100]
        if not heights:
            heights = [sv.content_height_px for sv in subviews]

        # The most common height is likely the standard cabinet elevation height
        median_height = sorted(heights)[len(heights) // 2]

        # This height represents the visible elevation (~38" for standing height with countertop)
        ppi = median_height / self.total_visible_height
        logger.info(f"Scale calibration: {median_height}px height = {self.total_visible_height}\" -> {ppi:.2f} px/inch")

        return ppi

    def _detect_cabinets_in_subview(self, binary: np.ndarray, gray: np.ndarray,
                                     sv: SubView, ppi: float) -> List[DetectedObject]:
        """Detect individual cabinets within a sub-view using vertical boundary analysis."""
        cabinets = []

        # Extract the cabinet region
        region = binary[sv.content_top:sv.content_bottom, sv.x_start:sv.x_end]
        gray_region = gray[sv.content_top:sv.content_bottom, sv.x_start:sv.x_end]
        rh, rw = region.shape

        if rw < 20 or rh < 20:
            return cabinets

        # Find vertical boundary lines between cabinets
        # True boundaries span nearly the full height of the cabinet region
        v_proj = np.sum(region > 0, axis=0)

        # Use 70% threshold for boundary lines
        boundary_threshold = rh * 0.70
        strong_cols = v_proj > boundary_threshold

        # Cluster adjacent strong columns into divider positions
        dividers = []
        in_div = False
        div_start = 0
        for i in range(rw):
            if strong_cols[i] and not in_div:
                div_start = i
                in_div = True
            elif not strong_cols[i] and in_div:
                center = (div_start + i) // 2
                line_width = i - div_start
                if line_width < 8:  # thin lines only
                    dividers.append(center)
                in_div = False

        # Minimum cabinet width in pixels (at least 8 inches)
        min_cab_px = max(15, ppi * 8)

        # Merge dividers that are too close together
        merged_dividers = []
        for d in dividers:
            if not merged_dividers or (d - merged_dividers[-1]) > min_cab_px * 0.5:
                merged_dividers.append(d)

        # Create segments between dividers
        all_edges = [0] + merged_dividers + [rw]
        segments = []
        for i in range(len(all_edges) - 1):
            xs = all_edges[i]
            xe = all_edges[i + 1]
            sw = xe - xs
            if sw >= min_cab_px * 0.7:
                segments.append((xs, xe, sw))

        # If no good segments found, treat entire subview as one cabinet
        if not segments and rw > min_cab_px:
            segments = [(0, rw, rw)]

        # Classify each segment
        for xs, xe, sw in segments:
            width_inches = sw / ppi if ppi > 0 else 0
            height_inches = rh / ppi if ppi > 0 else 0

            # Snap to standard Mott width
            standard_widths = [12, 15, 18, 21, 24, 30, 36, 42, 48]
            snapped_width = min(standard_widths, key=lambda s: abs(s - width_inches))

            # Accept snap if within 40% of standard width
            if abs(snapped_width - width_inches) > snapped_width * 0.4:
                snapped_width = round(width_inches)

            # Classify by interior features
            seg = region[:, xs:xe]
            gray_seg = gray_region[:, xs:xe]
            casework_type, confidence, features = self._classify_segment(seg, gray_seg, sw, rh)

            # Determine snap confidence boost
            snap_diff = abs(snapped_width - width_inches)
            if snap_diff < 2:
                confidence += 0.1
            elif snap_diff < 4:
                confidence += 0.05

            obj = DetectedObject(
                obj_id=self._next_id,
                casework_type=casework_type,
                bbox=(sv.x_start + xs, sv.content_top, sw, rh),
                center=(sv.x_start + xs + sw // 2, sv.content_top + rh // 2),
                confidence=min(confidence, 1.0),
                estimated_width_inches=float(snapped_width),
                estimated_height_inches=round(height_inches, 1),
                features=features,
                subview_index=sv.index,
                notes=f"Sub-view {sv.index + 1}, raw width {width_inches:.1f}\" -> snapped {snapped_width}\"",
            )
            self._next_id += 1
            cabinets.append(obj)

        return cabinets

    def _classify_segment(self, binary_seg: np.ndarray, gray_seg: np.ndarray,
                           seg_w: int, seg_h: int) -> Tuple[CaseworkType, float, Dict]:
        """Classify a cabinet segment by analyzing its interior patterns."""
        features = {
            "horizontal_line_groups": 0,
            "has_center_vertical": False,
            "has_circle": False,
            "fill_density": 0.0,
            "upper_density": 0.0,
            "lower_density": 0.0,
            "drawer_count": 0,
        }

        if seg_w < 5 or seg_h < 5:
            return CaseworkType.UNKNOWN, 0.3, features

        # Fill density
        total_pixels = seg_w * seg_h
        dark_pixels = np.count_nonzero(binary_seg)
        features["fill_density"] = dark_pixels / total_pixels if total_pixels > 0 else 0

        # Upper vs lower density (above/below midpoint)
        mid_y = seg_h // 2
        upper = binary_seg[:mid_y, :]
        lower = binary_seg[mid_y:, :]
        features["upper_density"] = np.count_nonzero(upper) / (upper.size + 1)
        features["lower_density"] = np.count_nonzero(lower) / (lower.size + 1)

        # Count horizontal line groups
        h_proj = np.sum(binary_seg > 0, axis=1)
        h_threshold = seg_w * 0.4
        prev_line = False
        line_groups = 0
        for val in h_proj:
            is_line = val > h_threshold
            if is_line and not prev_line:
                line_groups += 1
            prev_line = is_line
        features["horizontal_line_groups"] = line_groups

        # Estimate drawer count from horizontal lines in the lower 2/3
        lower_region = binary_seg[seg_h // 4:, :]
        lh_proj = np.sum(lower_region > 0, axis=1)
        prev_line = False
        drawer_lines = 0
        for val in lh_proj:
            if val > seg_w * 0.5 and not prev_line:
                drawer_lines += 1
            prev_line = val > seg_w * 0.5
        features["drawer_count"] = max(0, drawer_lines - 2)  # subtract top/bottom lines

        # Check for vertical center line (double doors)
        center_x = seg_w // 2
        center_band = binary_seg[:, max(0, center_x - 2):min(seg_w, center_x + 3)]
        if center_band.size > 0:
            center_fill = np.count_nonzero(center_band) / center_band.size
            features["has_center_vertical"] = center_fill > 0.3

        # Circle detection for sinks
        try:
            circles = cv2.HoughCircles(gray_seg, cv2.HOUGH_GRADIENT, dp=1.5,
                                       minDist=seg_w // 2, param1=80, param2=50,
                                       minRadius=max(3, seg_w // 10),
                                       maxRadius=seg_w // 3)
            if circles is not None and len(circles[0]) > 0:
                features["has_circle"] = True
        except Exception:
            pass

        # Classification logic
        casework_type = CaseworkType.BASE_CABINET
        confidence = 0.5

        drawer_count = features["drawer_count"]

        if features["has_circle"]:
            casework_type = CaseworkType.SINK_CABINET
            confidence = 0.65

        elif drawer_count >= 4:
            casework_type = CaseworkType.DRAWER_UNIT
            confidence = 0.7
            features["notes"] = f"~{drawer_count} drawers detected"

        elif drawer_count >= 2:
            # Door + drawer combo
            casework_type = CaseworkType.BASE_CABINET
            confidence = 0.6
            features["notes"] = "Door/drawer combo"

        elif features["fill_density"] < 0.08:
            casework_type = CaseworkType.OPEN_SHELF
            confidence = 0.5

        elif features["has_center_vertical"]:
            casework_type = CaseworkType.BASE_CABINET
            confidence = 0.6
            features["notes"] = "Double door (center line detected)"

        else:
            casework_type = CaseworkType.BASE_CABINET
            confidence = 0.5

        # Narrow items might be fillers or end panels
        if seg_w < seg_h * 0.15:
            casework_type = CaseworkType.FILLER
            confidence = 0.5

        return casework_type, confidence, features

    def _create_debug_image(self, original: np.ndarray, result: DetectionResult) -> np.ndarray:
        debug = original.copy() if len(original.shape) == 3 else cv2.cvtColor(original, cv2.COLOR_GRAY2BGR)

        type_colors = {
            CaseworkType.BASE_CABINET: (0, 255, 0),
            CaseworkType.WALL_CABINET: (255, 0, 0),
            CaseworkType.SINK: (0, 0, 255),
            CaseworkType.SINK_CABINET: (0, 128, 255),
            CaseworkType.DRAWER_UNIT: (255, 255, 0),
            CaseworkType.OPEN_SHELF: (128, 128, 0),
            CaseworkType.COUNTERTOP: (0, 255, 255),
            CaseworkType.FILLER: (128, 0, 128),
            CaseworkType.END_PANEL: (200, 100, 0),
            CaseworkType.UNKNOWN: (128, 128, 128),
        }

        # Draw subview boundaries
        for sv in result.subviews:
            cv2.rectangle(debug, (sv.x_start, sv.content_top),
                          (sv.x_end, sv.content_bottom), (100, 100, 100), 1)

        for obj in result.objects:
            color = type_colors.get(obj.casework_type, (128, 128, 128))
            x, y, w, h = obj.bbox
            thickness = 2 if obj.confidence >= 0.6 else 1

            cv2.rectangle(debug, (x, y), (x + w, y + h), color, thickness)

            label_parts = [obj.casework_type.value.split("_")[0]]
            if obj.estimated_width_inches:
                label_parts.append(f'{obj.estimated_width_inches:.0f}"')
            label_parts.append(f'{obj.confidence:.0%}')
            label = " ".join(label_parts)

            font_scale = 0.35
            cv2.putText(debug, label, (x + 2, y + 12), cv2.FONT_HERSHEY_SIMPLEX,
                        font_scale, color, 1)

        return debug
