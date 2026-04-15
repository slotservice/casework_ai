"""
CAD Writer Module
Generates clean, editable DXF output files using ezdxf.
Places matched blocks, dimensions, countertop outlines, annotations, and flags.
Draws professional shop-drawing-style cabinet elevations.
"""

import os
import logging
import math
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass

import ezdxf
from ezdxf.enums import TextEntityAlignment

from .block_matcher import MatchResult
from .object_detector import DetectedObject, CaseworkType, DetectionResult

# Map casework types that should get door details drawn
_DOOR_TYPES = {CaseworkType.BASE_CABINET, CaseworkType.SINK_CABINET, CaseworkType.WALL_CABINET}
# Map casework types that should get drawer details drawn
_DRAWER_TYPES = {CaseworkType.DRAWER_UNIT}

logger = logging.getLogger(__name__)


@dataclass
class PlacementInfo:
    """Information about where to place a block in the drawing."""
    x: float
    y: float
    width: float
    height: float
    product_number: str
    layer: str
    color: int
    confidence: float
    label: str = ""
    casework_type: CaseworkType = CaseworkType.BASE_CABINET
    drawer_count: int = 0
    has_center_vertical: bool = False
    has_circle: bool = False
    obj_id: int = 0


class CADWriter:
    """Generates DXF output files with matched casework blocks."""

    # Standard dimensions (inches)
    TOE_KICK_H = 4.0
    TOE_KICK_RECESS = 3.0  # toe kick setback from face
    COUNTERTOP_THICKNESS = 1.5
    COUNTERTOP_OVERHANG = 1.0
    HANDLE_RADIUS = 0.3
    HANDLE_OFFSET = 2.5  # from door edge
    DOOR_GAP = 0.0625  # 1/16" gap between doors
    DRAWER_GAP = 0.0625

    def __init__(self, config=None):
        self.config = config

        # Layer definitions
        self.layers = {
            "cabinets": "CASEWORK-CABINETS",
            "countertops": "CASEWORK-COUNTERTOPS",
            "sinks": "CASEWORK-SINKS",
            "fixtures": "CASEWORK-FIXTURES",
            "dimensions": "CASEWORK-DIMENSIONS",
            "annotations": "CASEWORK-ANNOTATIONS",
            "flags": "CASEWORK-FLAGS",
            "section_marks": "CASEWORK-SECTIONS",
            "product_numbers": "CASEWORK-PRODUCT-NUMBERS",
            "outlines": "CASEWORK-OUTLINES",
            "hidden": "CASEWORK-HIDDEN",
        }

        # Colors (AutoCAD color index)
        self.colors = {
            "cabinets": 7,       # white
            "countertops": 3,    # green
            "sinks": 5,          # blue
            "fixtures": 6,       # magenta
            "dimensions": 2,     # yellow
            "annotations": 1,    # red
            "flags": 1,          # red
            "section_marks": 4,  # cyan
            "product_numbers": 2, # yellow
            "outlines": 7,       # white
            "hidden": 8,         # dark gray
        }

        if config:
            cfg_layers = config.get("cad.layers", {})
            if cfg_layers:
                self.layers.update(cfg_layers)
            cfg_colors = config.get("cad.colors", {})
            if cfg_colors:
                self.colors.update(cfg_colors)

    def generate_dxf(self, match_results: List[MatchResult],
                     detection_result: DetectionResult,
                     output_path: str,
                     title: str = "Casework Elevation") -> str:
        logger.info(f"Generating DXF output: {output_path}")

        doc = ezdxf.new("R2010")
        msp = doc.modelspace()

        self._setup_layers(doc)

        scale = detection_result.scale_factor if detection_result.scale_factor > 0 else 1.0
        placements = self._calculate_placements(match_results, scale)

        # Draw in proper order: back to front
        self._draw_countertop(msp, placements, detection_result)
        for placement in placements:
            self._draw_cabinet(msp, placement)
        self._add_dimensions(msp, placements)
        self._add_product_numbers(msp, placements)
        self._add_flags(msp, match_results, scale)
        self._add_title_block(msp, title, match_results, placements)

        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
        doc.saveas(output_path)
        logger.info(f"DXF saved to {output_path}")
        return output_path

    def _setup_layers(self, doc: ezdxf.document.Drawing):
        for key, layer_name in self.layers.items():
            color = self.colors.get(key, 7)
            doc.layers.add(layer_name, color=color)
        # Set hidden layer to dashed linetype
        doc.linetypes.add("HIDDEN", pattern=[0.25, 0.125, -0.0625])
        doc.layers.get(self.layers["hidden"]).dxf.linetype = "HIDDEN"

    def _calculate_placements(self, match_results: List[MatchResult],
                               scale: float) -> List[PlacementInfo]:
        """Calculate placements using actual detected positions to preserve spatial layout.

        Uses the original pixel positions (converted to inches via scale factor) so that
        gaps between cabinet runs in the original drawing are preserved in the DXF output.
        Within each contiguous run, cabinets are placed tightly end-to-end using their
        snapped widths to produce clean alignment.
        """
        placements = []

        # First pass: collect all objects with their real pixel positions
        items = []
        for result in match_results:
            obj = result.detected_object
            if obj.casework_type == CaseworkType.COUNTERTOP:
                continue
            items.append((obj, result))

        if not items:
            return placements

        # Sort by pixel x position
        items.sort(key=lambda ir: ir[0].bbox[0])

        # Identify contiguous runs by detecting large gaps
        # A gap larger than ~15 inches (in pixel space) indicates separate cabinet runs
        gap_threshold_px = scale * 12  # ~12 inches of gap = separate run
        runs = []
        current_run = [items[0]]
        for i in range(1, len(items)):
            prev_obj = items[i - 1][0]
            curr_obj = items[i][0]
            prev_right = prev_obj.bbox[0] + prev_obj.bbox[2]
            curr_left = curr_obj.bbox[0]
            gap = curr_left - prev_right
            if gap > gap_threshold_px:
                runs.append(current_run)
                current_run = [items[i]]
            else:
                current_run.append(items[i])
        runs.append(current_run)

        # Second pass: place each run, with real gaps between runs
        # Convert the first object's pixel position to the DXF starting x
        first_px = items[0][0].bbox[0]

        for run in runs:
            # Starting x for this run: use pixel position relative to first object
            run_start_px = run[0][0].bbox[0]
            run_start_inches = (run_start_px - first_px) / scale if scale > 0 else 0
            current_x = run_start_inches

            for obj, result in run:
                width = obj.estimated_width_inches or (obj.bbox[2] / scale if scale > 0 else 24)
                height = obj.estimated_height_inches or (obj.bbox[3] / scale if scale > 0 else 34.75)

                layer_key = self._type_to_layer_key(obj.casework_type)
                product_num = result.product_number or "UNMATCHED"

                label = f"{obj.casework_type.value}"
                if result.best_match:
                    label = result.best_match.description or result.best_match.product_number

                drawer_count = obj.features.get("drawer_count", 0) if obj.features else 0
                has_center_vert = obj.features.get("has_center_vertical", False) if obj.features else False
                has_circle = obj.features.get("has_circle", False) if obj.features else False

                placement = PlacementInfo(
                    x=current_x,
                    y=0.0,
                    width=width,
                    height=height,
                    product_number=product_num,
                    layer=self.layers.get(layer_key, "CASEWORK-CABINETS"),
                    color=self.colors.get(layer_key, 7),
                    confidence=result.confidence,
                    label=label,
                    casework_type=obj.casework_type,
                    drawer_count=drawer_count,
                    has_center_vertical=has_center_vert,
                    has_circle=has_circle,
                    obj_id=obj.obj_id,
                )
                placements.append(placement)
                current_x += width

        return placements

    def _type_to_layer_key(self, casework_type: CaseworkType) -> str:
        mapping = {
            CaseworkType.BASE_CABINET: "cabinets",
            CaseworkType.WALL_CABINET: "cabinets",
            CaseworkType.SINK: "sinks",
            CaseworkType.SINK_CABINET: "sinks",
            CaseworkType.DRAWER_UNIT: "cabinets",
            CaseworkType.OPEN_SHELF: "cabinets",
            CaseworkType.COUNTERTOP: "countertops",
            CaseworkType.FILLER: "cabinets",
            CaseworkType.END_PANEL: "cabinets",
            CaseworkType.PEGBOARD: "fixtures",
            CaseworkType.FUME_HOOD: "fixtures",
            CaseworkType.FIXTURE: "fixtures",
        }
        return mapping.get(casework_type, "cabinets")

    # ------------------------------------------------------------------ #
    #  Cabinet drawing - professional shop drawing style
    # ------------------------------------------------------------------ #

    def _draw_cabinet(self, msp, p: PlacementInfo):
        """Draw a single cabinet in shop-drawing style."""
        if p.casework_type == CaseworkType.FILLER:
            self._draw_filler(msp, p)
        elif p.casework_type == CaseworkType.DRAWER_UNIT:
            self._draw_drawer_unit(msp, p)
        elif p.casework_type == CaseworkType.SINK_CABINET:
            self._draw_sink_cabinet(msp, p)
        elif p.casework_type == CaseworkType.OPEN_SHELF:
            self._draw_open_shelf(msp, p)
        else:
            self._draw_door_cabinet(msp, p)

    def _cab_attribs(self, p: PlacementInfo) -> dict:
        return {"layer": p.layer, "color": p.color}

    def _hidden_attribs(self) -> dict:
        return {"layer": self.layers["hidden"], "color": self.colors["hidden"]}

    def _draw_outer_box(self, msp, p: PlacementInfo):
        """Draw the standard cabinet outer rectangle and toe kick."""
        x, y, w, h = p.x, p.y, p.width, p.height
        att = self._cab_attribs(p)

        # Main outline
        msp.add_lwpolyline(
            [(x, y), (x + w, y), (x + w, y + h), (x, y + h), (x, y)],
            dxfattribs=att, close=True)

        # Toe kick line
        tk = self.TOE_KICK_H
        msp.add_line((x, y + tk), (x + w, y + tk), dxfattribs=att)

        # Toe kick recess lines (hidden/dashed) showing the recessed base
        rec = self.TOE_KICK_RECESS
        hatt = self._hidden_attribs()
        msp.add_line((x + rec, y), (x + rec, y + tk), dxfattribs=hatt)
        msp.add_line((x + w - rec, y), (x + w - rec, y + tk), dxfattribs=hatt)
        msp.add_line((x + rec, y), (x + w - rec, y), dxfattribs=hatt)

    def _draw_door_cabinet(self, msp, p: PlacementInfo):
        """Draw a base cabinet with doors (single or double)."""
        self._draw_outer_box(msp, p)
        x, y, w, h = p.x, p.y, p.width, p.height
        att = self._cab_attribs(p)
        tk = self.TOE_KICK_H
        door_area_h = h - tk
        gap = self.DOOR_GAP

        is_double = w > 21 or p.has_center_vertical

        if is_double:
            # Double door - two panels with center stile
            mid = x + w / 2
            msp.add_line((mid, y + tk), (mid, y + h), dxfattribs=att)

            # Left door panel (inset lines showing door edge)
            self._draw_door_panel(msp, x + gap, y + tk + gap, w / 2 - gap * 2, door_area_h - gap * 2, att, "left")
            # Right door panel
            self._draw_door_panel(msp, mid + gap, y + tk + gap, w / 2 - gap * 2, door_area_h - gap * 2, att, "right")
        else:
            # Single door
            self._draw_door_panel(msp, x + gap, y + tk + gap, w - gap * 2, door_area_h - gap * 2, att, "right")

    def _draw_door_panel(self, msp, x, y, w, h, att, hand):
        """Draw a single door panel with raised panel detail and handle."""
        # Raised panel inset (typical shop drawing detail)
        inset = min(1.5, w * 0.12, h * 0.06)
        if w > 4 and h > 8:
            msp.add_lwpolyline(
                [(x + inset, y + inset), (x + w - inset, y + inset),
                 (x + w - inset, y + h - inset), (x + inset, y + h - inset),
                 (x + inset, y + inset)],
                dxfattribs=att, close=True)

        # Door handle
        if hand == "left":
            hx = x + w - self.HANDLE_OFFSET
        else:
            hx = x + self.HANDLE_OFFSET
        hy = y + h * 0.55
        msp.add_circle((hx, hy), self.HANDLE_RADIUS, dxfattribs=att)

    def _draw_drawer_unit(self, msp, p: PlacementInfo):
        """Draw a drawer unit with multiple drawers."""
        self._draw_outer_box(msp, p)
        x, y, w, h = p.x, p.y, p.width, p.height
        att = self._cab_attribs(p)
        tk = self.TOE_KICK_H

        num_drawers = max(p.drawer_count, 4)
        drawer_area_h = h - tk
        drawer_h = drawer_area_h / num_drawers

        for i in range(1, num_drawers):
            dy = y + tk + i * drawer_h
            msp.add_line((x, dy), (x + w, dy), dxfattribs=att)

        # Drawer handles (centered horizontal pulls)
        for i in range(num_drawers):
            dy_center = y + tk + i * drawer_h + drawer_h / 2
            pull_half_w = min(w * 0.15, 2.0)  # pull width proportional to cabinet
            cx = x + w / 2
            msp.add_line(
                (cx - pull_half_w, dy_center),
                (cx + pull_half_w, dy_center),
                dxfattribs=att)
            # Small end caps on the pull
            cap = 0.2
            msp.add_line((cx - pull_half_w, dy_center - cap), (cx - pull_half_w, dy_center + cap), dxfattribs=att)
            msp.add_line((cx + pull_half_w, dy_center - cap), (cx + pull_half_w, dy_center + cap), dxfattribs=att)

    def _draw_sink_cabinet(self, msp, p: PlacementInfo):
        """Draw a sink cabinet - double doors with sink basin shown as hidden/dashed."""
        # Draw as double-door cabinet first
        self._draw_outer_box(msp, p)
        x, y, w, h = p.x, p.y, p.width, p.height
        att = self._cab_attribs(p)
        tk = self.TOE_KICK_H
        door_area_h = h - tk

        # Always double door for sink cabinets
        mid = x + w / 2
        msp.add_line((mid, y + tk), (mid, y + h), dxfattribs=att)
        self._draw_door_panel(msp, x, y + tk, w / 2, door_area_h, att, "left")
        self._draw_door_panel(msp, mid, y + tk, w / 2, door_area_h, att, "right")

        # Sink basin outline (dashed/hidden) - ellipse in upper portion
        hatt = self._hidden_attribs()
        basin_w = w * 0.55
        basin_h = door_area_h * 0.35
        basin_cx = x + w / 2
        basin_cy = y + h - door_area_h * 0.45

        # Draw basin as a rectangle with rounded indication (ezdxf ellipse)
        try:
            msp.add_ellipse(
                center=(basin_cx, basin_cy),
                major_axis=(basin_w / 2, 0),
                ratio=basin_h / basin_w if basin_w > 0 else 0.5,
                dxfattribs=hatt)
        except Exception:
            # Fallback: draw as rectangle
            bx = basin_cx - basin_w / 2
            by = basin_cy - basin_h / 2
            msp.add_lwpolyline(
                [(bx, by), (bx + basin_w, by), (bx + basin_w, by + basin_h),
                 (bx, by + basin_h), (bx, by)],
                dxfattribs=hatt, close=True)

    def _draw_open_shelf(self, msp, p: PlacementInfo):
        """Draw open shelving unit."""
        self._draw_outer_box(msp, p)
        x, y, w, h = p.x, p.y, p.width, p.height
        att = self._cab_attribs(p)
        tk = self.TOE_KICK_H

        # Draw 2-3 shelf lines (evenly spaced)
        shelf_area = h - tk
        num_shelves = 2 if w < 24 else 3
        for i in range(1, num_shelves + 1):
            sy = y + tk + (shelf_area * i / (num_shelves + 1))
            msp.add_line((x, sy), (x + w, sy), dxfattribs=att)

    def _draw_filler(self, msp, p: PlacementInfo):
        """Draw a filler strip - simple rectangle with diagonal hatch."""
        x, y, w, h = p.x, p.y, p.width, p.height
        att = self._cab_attribs(p)

        # Outline
        msp.add_lwpolyline(
            [(x, y), (x + w, y), (x + w, y + h), (x, y + h), (x, y)],
            dxfattribs=att, close=True)

        # Diagonal lines to indicate filler
        num_diags = max(2, int(h / 6))
        for i in range(num_diags):
            dy = y + (h * (i + 1) / (num_diags + 1))
            # Diagonal from bottom-left to top-right within the strip
            x1 = x
            y1 = dy
            x2 = x + w
            y2 = min(dy + w, y + h)
            msp.add_line((x1, y1), (x2, y2), dxfattribs=att)

    # ------------------------------------------------------------------ #
    #  Countertop
    # ------------------------------------------------------------------ #

    def _find_runs(self, placements: List[PlacementInfo]) -> List[List[PlacementInfo]]:
        """Group placements into contiguous cabinet runs (separated by gaps)."""
        if not placements:
            return []
        sorted_p = sorted(placements, key=lambda p: p.x)
        runs = [[sorted_p[0]]]
        for i in range(1, len(sorted_p)):
            prev = sorted_p[i - 1]
            curr = sorted_p[i]
            gap = curr.x - (prev.x + prev.width)
            if gap > 8:  # more than 8" gap = separate run
                runs.append([curr])
            else:
                runs[-1].append(curr)
        return runs

    def _draw_countertop(self, msp, placements: List[PlacementInfo],
                          detection_result: DetectionResult):
        if not placements:
            return

        layer = self.layers["countertops"]
        color = self.colors["countertops"]
        att = {"layer": layer, "color": color}

        # Draw separate countertop for each cabinet run
        runs = self._find_runs(placements)
        for run in runs:
            min_x = min(p.x for p in run) - self.COUNTERTOP_OVERHANG
            max_x = max(p.x + p.width for p in run) + self.COUNTERTOP_OVERHANG
            max_h = max(p.height for p in run)

            ct_bottom = max_h
            ct_top = max_h + self.COUNTERTOP_THICKNESS

            msp.add_lwpolyline(
                [(min_x, ct_bottom), (max_x, ct_bottom),
                 (max_x, ct_top), (min_x, ct_top), (min_x, ct_bottom)],
                dxfattribs=att, close=True)

            # Nosing detail
            msp.add_line(
                (min_x, ct_bottom - 0.25), (max_x, ct_bottom - 0.25),
                dxfattribs=att)

    # ------------------------------------------------------------------ #
    #  Dimensions
    # ------------------------------------------------------------------ #

    def _add_dimensions(self, msp, placements: List[PlacementInfo]):
        layer = self.layers["dimensions"]
        color = self.colors["dimensions"]
        att = {"layer": layer, "color": color}
        ext_att = {"layer": layer, "color": 8}  # extension lines in dark gray

        runs = self._find_runs(placements)

        for run in runs:
            # Individual cabinet widths
            dim_y = -4.0
            for p in run:
                mid_x = p.x + p.width / 2
                text = f'{p.width:.0f}"'

                msp.add_text(text, dxfattribs={**att, "height": 1.5}).set_placement(
                    (mid_x, dim_y), align=TextEntityAlignment.MIDDLE_CENTER)

                # Dimension line
                msp.add_line((p.x + 0.5, dim_y + 1.2), (p.x + p.width - 0.5, dim_y + 1.2), dxfattribs=att)
                # Tick marks
                for tx in (p.x, p.x + p.width):
                    msp.add_line((tx, dim_y + 0.5), (tx, dim_y + 1.8), dxfattribs=att)
                # Extension lines
                msp.add_line((p.x, p.y - 0.5), (p.x, dim_y + 2.0), dxfattribs=ext_att)
                msp.add_line((p.x + p.width, p.y - 0.5), (p.x + p.width, dim_y + 2.0), dxfattribs=ext_att)

            # Run overall dimension
            run_start = run[0].x
            run_end = run[-1].x + run[-1].width
            run_width = run_end - run_start
            if len(run) > 1:
                overall_y = dim_y - 5.0
                text = f'{run_width:.0f}"'
                msp.add_text(text, dxfattribs={**att, "height": 1.8}).set_placement(
                    ((run_start + run_end) / 2, overall_y), align=TextEntityAlignment.MIDDLE_CENTER)
                msp.add_line((run_start + 0.5, overall_y + 1.5), (run_end - 0.5, overall_y + 1.5), dxfattribs=att)
                for tx in (run_start, run_end):
                    msp.add_line((tx, overall_y + 0.8), (tx, overall_y + 2.2), dxfattribs=att)

        # Height dimension on the rightmost run
        if runs:
            last_run = runs[-1]
            last_p = last_run[-1]
            hx = last_p.x + last_p.width + 3.0
            h = last_p.height
            msp.add_line((hx, 0), (hx, h), dxfattribs=att)
            msp.add_line((hx - 0.5, 0), (hx + 0.5, 0), dxfattribs=att)
            msp.add_line((hx - 0.5, h), (hx + 0.5, h), dxfattribs=att)
            msp.add_text(f'{h:.1f}"', dxfattribs={**att, "height": 1.2, "rotation": 90}).set_placement(
                (hx + 1.5, h / 2), align=TextEntityAlignment.MIDDLE_CENTER)

    # ------------------------------------------------------------------ #
    #  Product numbers & annotations
    # ------------------------------------------------------------------ #

    def _add_product_numbers(self, msp, placements: List[PlacementInfo]):
        layer = self.layers["product_numbers"]
        color = self.colors["product_numbers"]

        for p in placements:
            if not p.product_number or p.product_number == "UNMATCHED":
                continue

            mid_x = p.x + p.width / 2
            # Place product number in the upper third of the cabinet (above any sink basin / between drawers)
            label_y = p.y + p.height * 0.78

            # Scale text to fit in cabinet
            text_h = min(1.2, p.width * 0.08)
            msp.add_text(
                p.product_number,
                dxfattribs={"layer": layer, "color": color, "height": text_h},
            ).set_placement((mid_x, label_y), align=TextEntityAlignment.MIDDLE_CENTER)

    def _add_flags(self, msp, match_results: List[MatchResult], scale: float):
        layer = self.layers["flags"]
        color = self.colors["flags"]
        att = {"layer": layer, "color": color}

        flag_y_offset = 0.0
        for result in match_results:
            if not result.is_flagged:
                continue

            obj = result.detected_object
            x = obj.bbox[0] / scale if scale > 0 else obj.bbox[0]
            w = obj.estimated_width_inches or 24
            flag_y = (obj.estimated_height_inches or 34.75) + 6
            flag_y += flag_y_offset

            flag_text = f"? {result.flag_reason}"
            msp.add_text(flag_text, dxfattribs={**att, "height": 1.0}).set_placement(
                (x, flag_y), align=TextEntityAlignment.LEFT)

            # Triangle warning marker
            cx = x + w / 2
            cy = flag_y - 1.5
            tri_r = 1.2
            pts = [
                (cx, cy + tri_r),
                (cx - tri_r * 0.866, cy - tri_r * 0.5),
                (cx + tri_r * 0.866, cy - tri_r * 0.5),
                (cx, cy + tri_r),
            ]
            msp.add_lwpolyline(pts, dxfattribs=att, close=True)
            msp.add_text("!", dxfattribs={**att, "height": 1.2}).set_placement(
                (cx, cy), align=TextEntityAlignment.MIDDLE_CENTER)

            flag_y_offset += 3.5

    def _add_title_block(self, msp, title: str, match_results: List[MatchResult],
                         placements: List[PlacementInfo]):
        layer = self.layers["annotations"]
        ann_color = self.colors["annotations"]

        total_matched = len([r for r in match_results if r.best_match])
        total_flagged = len([r for r in match_results if r.is_flagged])
        total = len(match_results)

        # Calculate average confidence
        confidences = [r.confidence for r in match_results if r.confidence > 0]
        avg_conf = sum(confidences) / len(confidences) if confidences else 0

        # Total width
        total_width = sum(p.width for p in placements) if placements else 0

        # Title block below dimensions
        title_y = -18.0
        total_end = placements[-1].x + placements[-1].width if placements else 100

        # Box around title block
        tb_x = 0
        tb_w = max(total_end, 80)
        tb_h = 12
        msp.add_lwpolyline(
            [(tb_x, title_y), (tb_x + tb_w, title_y),
             (tb_x + tb_w, title_y - tb_h), (tb_x, title_y - tb_h),
             (tb_x, title_y)],
            dxfattribs={"layer": layer, "color": 8}, close=True)

        # Title
        msp.add_text(title, dxfattribs={"layer": layer, "color": 7, "height": 2.5}).set_placement(
            (tb_x + 2, title_y - 3), align=TextEntityAlignment.LEFT)

        # Stats line
        stats = (f"Items: {total}  |  Matched: {total_matched}  |  Flagged: {total_flagged}  |  "
                 f"Avg Confidence: {avg_conf:.0%}  |  Total Width: {total_width:.0f}\"")
        msp.add_text(stats, dxfattribs={"layer": layer, "color": ann_color, "height": 1.3}).set_placement(
            (tb_x + 2, title_y - 6.5), align=TextEntityAlignment.LEFT)

        # Generator credit
        msp.add_text(
            "Generated by Casework AI Pipeline - Mott Manufacturing",
            dxfattribs={"layer": layer, "color": 8, "height": 1.0}).set_placement(
            (tb_x + 2, title_y - 9.5), align=TextEntityAlignment.LEFT)
