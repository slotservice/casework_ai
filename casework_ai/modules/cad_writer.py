"""
CAD Writer Module
Generates professional shop-drawing-style DXF output files using ezdxf.
Matches Mott Manufacturing elevation drawing standards with:
- Wall/backsplash representation with hatching
- Leader lines with cabinet description annotations
- Proper elevation marker and title block
- Material-specific cabinet patterns
- Section cut markers
- Full dimensioning with extension lines
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

logger = logging.getLogger(__name__)


# ------------------------------------------------------------------ #
#  Type descriptions for leader annotations (Mott shop drawing format)
# ------------------------------------------------------------------ #
_TYPE_DESCRIPTIONS = {
    CaseworkType.BASE_CABINET: "LOWER CASEWORK W/ DOORS\nATTACHED TOE KICKS - LG-1",
    CaseworkType.DRAWER_UNIT: "LOWER CASEWORK W/ DRAWERS\nATTACHED TOE KICKS - LG-1",
    CaseworkType.SINK_CABINET: "LOWER CASEWORK, SINK BASE\nOPEN BOTTOM - LG-1",
    CaseworkType.OPEN_SHELF: "LOWER CASEWORK\nOPEN SHELVES - LG-1",
    CaseworkType.FILLER: "FILLER STRIP",
    CaseworkType.WALL_CABINET: "UPPER CASEWORK\nADJUSTABLE SHELVES - LG-1",
    CaseworkType.PEGBOARD: "EPOXY PEG BOARD\nWITH DRIP TRAY",
    CaseworkType.FUME_HOOD: "FUME HOOD\nSEE MECHANICAL",
    CaseworkType.END_PANEL: "END PANEL",
}


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
    """Generates DXF output files matching Mott shop drawing standards."""

    # Standard dimensions (inches)
    TOE_KICK_H = 4.0
    TOE_KICK_RECESS = 3.0
    COUNTERTOP_THICKNESS = 1.5
    COUNTERTOP_OVERHANG = 1.0
    HANDLE_RADIUS = 0.3
    HANDLE_OFFSET = 2.5
    DOOR_GAP = 0.0625
    DRAWER_GAP = 0.0625
    BACKSPLASH_H = 18.0  # wall area above countertop
    HATCH_SPACING = 2.0  # diagonal hatch line spacing for wall

    def __init__(self, config=None):
        self.config = config

        self.layers = {
            "cabinets": "CASEWORK-CABINETS",
            "countertops": "CASEWORK-COUNTERTOPS",
            "sinks": "CASEWORK-SINKS",
            "fixtures": "CASEWORK-FIXTURES",
            "dimensions": "CASEWORK-DIMENSIONS",
            "annotations": "CASEWORK-ANNOTATIONS",
            "leaders": "CASEWORK-LEADERS",
            "flags": "CASEWORK-FLAGS",
            "section_marks": "CASEWORK-SECTIONS",
            "product_numbers": "CASEWORK-PRODUCT-NUMBERS",
            "outlines": "CASEWORK-OUTLINES",
            "hidden": "CASEWORK-HIDDEN",
            "wall": "CASEWORK-WALL",
            "titleblock": "CASEWORK-TITLEBLOCK",
        }

        self.colors = {
            "cabinets": 7,       # white
            "countertops": 3,    # green
            "sinks": 5,          # blue
            "fixtures": 6,       # magenta
            "dimensions": 2,     # yellow
            "annotations": 7,    # white
            "leaders": 7,        # white
            "flags": 1,          # red
            "section_marks": 4,  # cyan
            "product_numbers": 2, # yellow
            "outlines": 7,       # white
            "hidden": 8,         # dark gray
            "wall": 8,           # dark gray
            "titleblock": 7,     # white
        }

        if config:
            cfg_layers = config.get("cad.layers", {})
            if cfg_layers:
                self.layers.update(cfg_layers)
            cfg_colors = config.get("cad.colors", {})
            if cfg_colors:
                self.colors.update(cfg_colors)

    # ================================================================== #
    #  Main entry point
    # ================================================================== #

    def generate_dxf(self, match_results: List[MatchResult],
                     detection_result: DetectionResult,
                     output_path: str,
                     title: str = "Casework Elevation",
                     elevation_label: str = "E4",
                     room_name: str = "") -> str:
        logger.info(f"Generating DXF output: {output_path}")

        doc = ezdxf.new("R2010")
        msp = doc.modelspace()

        self._setup_layers(doc)

        scale = detection_result.scale_factor if detection_result.scale_factor > 0 else 1.0
        placements = self._calculate_placements(match_results, scale)

        if not placements:
            doc.saveas(output_path)
            return output_path

        # Draw in order: wall background -> countertop -> cabinets -> annotations
        self._draw_wall_backsplash(msp, placements)
        self._draw_countertop(msp, placements, detection_result)
        for placement in placements:
            self._draw_cabinet(msp, placement)
        self._add_dimensions(msp, placements)
        self._add_product_numbers(msp, placements)
        self._add_leader_annotations(msp, placements)
        self._add_section_marks(msp, placements)
        self._add_flags(msp, match_results, scale)
        self._add_elevation_marker(msp, placements, elevation_label, room_name, title)

        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
        doc.saveas(output_path)
        logger.info(f"DXF saved to {output_path}")
        return output_path

    def _setup_layers(self, doc: ezdxf.document.Drawing):
        for key, layer_name in self.layers.items():
            color = self.colors.get(key, 7)
            doc.layers.add(layer_name, color=color)
        doc.linetypes.add("HIDDEN", pattern=[0.25, 0.125, -0.0625])
        doc.linetypes.add("CENTER", pattern=[0.5, 0.25, -0.125, 0.0, -0.125])
        doc.layers.get(self.layers["hidden"]).dxf.linetype = "HIDDEN"

    # ================================================================== #
    #  Placement calculation (preserves spatial layout)
    # ================================================================== #

    def _calculate_placements(self, match_results: List[MatchResult],
                               scale: float) -> List[PlacementInfo]:
        placements = []
        items = []
        for result in match_results:
            obj = result.detected_object
            if obj.casework_type == CaseworkType.COUNTERTOP:
                continue
            items.append((obj, result))

        if not items:
            return placements

        items.sort(key=lambda ir: ir[0].bbox[0])

        gap_threshold_px = scale * 12
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

        first_px = items[0][0].bbox[0]

        for run in runs:
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
                    x=current_x, y=0.0, width=width, height=height,
                    product_number=product_num, layer=self.layers.get(layer_key, "CASEWORK-CABINETS"),
                    color=self.colors.get(layer_key, 7), confidence=result.confidence,
                    label=label, casework_type=obj.casework_type,
                    drawer_count=drawer_count, has_center_vertical=has_center_vert,
                    has_circle=has_circle, obj_id=obj.obj_id,
                )
                placements.append(placement)
                current_x += width

        return placements

    def _type_to_layer_key(self, casework_type: CaseworkType) -> str:
        mapping = {
            CaseworkType.BASE_CABINET: "cabinets", CaseworkType.WALL_CABINET: "cabinets",
            CaseworkType.SINK: "sinks", CaseworkType.SINK_CABINET: "sinks",
            CaseworkType.DRAWER_UNIT: "cabinets", CaseworkType.OPEN_SHELF: "cabinets",
            CaseworkType.COUNTERTOP: "countertops", CaseworkType.FILLER: "cabinets",
            CaseworkType.END_PANEL: "cabinets", CaseworkType.PEGBOARD: "fixtures",
            CaseworkType.FUME_HOOD: "fixtures", CaseworkType.FIXTURE: "fixtures",
        }
        return mapping.get(casework_type, "cabinets")

    def _find_runs(self, placements: List[PlacementInfo]) -> List[List[PlacementInfo]]:
        if not placements:
            return []
        sorted_p = sorted(placements, key=lambda p: p.x)
        runs = [[sorted_p[0]]]
        for i in range(1, len(sorted_p)):
            prev = sorted_p[i - 1]
            curr = sorted_p[i]
            gap = curr.x - (prev.x + prev.width)
            if gap > 8:
                runs.append([curr])
            else:
                runs[-1].append(curr)
        return runs

    # ================================================================== #
    #  Wall / Backsplash
    # ================================================================== #

    def _draw_wall_backsplash(self, msp, placements: List[PlacementInfo]):
        """Draw wall area above countertop with brick/masonry hatch pattern."""
        runs = self._find_runs(placements)
        wall_layer = self.layers["wall"]
        wall_color = self.colors["wall"]
        att = {"layer": wall_layer, "color": wall_color}

        for run in runs:
            min_x = min(p.x for p in run) - 2
            max_x = max(p.x + p.width for p in run) + 2
            max_h = max(p.height for p in run)

            wall_bottom = max_h + self.COUNTERTOP_THICKNESS
            wall_top = wall_bottom + self.BACKSPLASH_H

            # Wall outline
            msp.add_lwpolyline(
                [(min_x, wall_bottom), (max_x, wall_bottom),
                 (max_x, wall_top), (min_x, wall_top), (min_x, wall_bottom)],
                dxfattribs=att, close=True)

            # Brick/masonry hatch pattern
            # Standard modular brick: 2-2/3" face height, 8" wide, 3/8" mortar joints
            brick_h = 2.67    # brick face height in inches
            brick_w = 8.0     # standard brick width
            mortar = 0.38     # mortar joint thickness
            course_h = brick_h + mortar  # total course height

            wall_h = wall_top - wall_bottom
            n_courses = int(wall_h / course_h) + 2

            for i in range(n_courses):
                jy = wall_bottom + i * course_h

                # Horizontal mortar joint line
                if wall_bottom < jy < wall_top:
                    msp.add_line((min_x, jy), (max_x, jy), dxfattribs=att)

                # Vertical joints — staggered by half-brick on alternating courses
                x_offset = (brick_w / 2) if (i % 2 == 1) else 0
                vx = min_x + x_offset
                jy_bottom = max(wall_bottom, jy)
                jy_top = min(jy + course_h, wall_top)
                while vx < max_x:
                    if min_x < vx < max_x:
                        msp.add_line((vx, jy_bottom), (vx, jy_top), dxfattribs=att)
                    vx += brick_w

    # ================================================================== #
    #  Cabinet drawing
    # ================================================================== #

    def _draw_cabinet(self, msp, p: PlacementInfo):
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
        x, y, w, h = p.x, p.y, p.width, p.height
        att = self._cab_attribs(p)
        msp.add_lwpolyline(
            [(x, y), (x + w, y), (x + w, y + h), (x, y + h), (x, y)],
            dxfattribs=att, close=True)
        tk = self.TOE_KICK_H
        msp.add_line((x, y + tk), (x + w, y + tk), dxfattribs=att)
        rec = self.TOE_KICK_RECESS
        hatt = self._hidden_attribs()
        msp.add_line((x + rec, y), (x + rec, y + tk), dxfattribs=hatt)
        msp.add_line((x + w - rec, y), (x + w - rec, y + tk), dxfattribs=hatt)
        msp.add_line((x + rec, y), (x + w - rec, y), dxfattribs=hatt)

    def _draw_door_cabinet(self, msp, p: PlacementInfo):
        self._draw_outer_box(msp, p)
        x, y, w, h = p.x, p.y, p.width, p.height
        att = self._cab_attribs(p)
        tk = self.TOE_KICK_H
        door_area_h = h - tk
        gap = self.DOOR_GAP
        is_double = w > 21 or p.has_center_vertical

        if is_double:
            mid = x + w / 2
            msp.add_line((mid, y + tk), (mid, y + h), dxfattribs=att)
            self._draw_door_panel(msp, x + gap, y + tk + gap, w / 2 - gap * 2, door_area_h - gap * 2, att, "left")
            self._draw_door_panel(msp, mid + gap, y + tk + gap, w / 2 - gap * 2, door_area_h - gap * 2, att, "right")
        else:
            self._draw_door_panel(msp, x + gap, y + tk + gap, w - gap * 2, door_area_h - gap * 2, att, "right")

    def _draw_door_panel(self, msp, x, y, w, h, att, hand):
        inset = min(1.5, w * 0.12, h * 0.06)
        if w > 4 and h > 8:
            msp.add_lwpolyline(
                [(x + inset, y + inset), (x + w - inset, y + inset),
                 (x + w - inset, y + h - inset), (x + inset, y + h - inset),
                 (x + inset, y + inset)],
                dxfattribs=att, close=True)
        if hand == "left":
            hx = x + w - self.HANDLE_OFFSET
        else:
            hx = x + self.HANDLE_OFFSET
        hy = y + h * 0.55
        msp.add_circle((hx, hy), self.HANDLE_RADIUS, dxfattribs=att)

    def _draw_drawer_unit(self, msp, p: PlacementInfo):
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
        for i in range(num_drawers):
            dy_center = y + tk + i * drawer_h + drawer_h / 2
            pull_half_w = min(w * 0.15, 2.0)
            cx = x + w / 2
            msp.add_line((cx - pull_half_w, dy_center), (cx + pull_half_w, dy_center), dxfattribs=att)
            cap = 0.2
            msp.add_line((cx - pull_half_w, dy_center - cap), (cx - pull_half_w, dy_center + cap), dxfattribs=att)
            msp.add_line((cx + pull_half_w, dy_center - cap), (cx + pull_half_w, dy_center + cap), dxfattribs=att)

    def _draw_sink_cabinet(self, msp, p: PlacementInfo):
        self._draw_outer_box(msp, p)
        x, y, w, h = p.x, p.y, p.width, p.height
        att = self._cab_attribs(p)
        tk = self.TOE_KICK_H
        door_area_h = h - tk
        mid = x + w / 2
        msp.add_line((mid, y + tk), (mid, y + h), dxfattribs=att)
        self._draw_door_panel(msp, x, y + tk, w / 2, door_area_h, att, "left")
        self._draw_door_panel(msp, mid, y + tk, w / 2, door_area_h, att, "right")
        hatt = self._hidden_attribs()
        basin_w = w * 0.55
        basin_h = door_area_h * 0.35
        basin_cx = x + w / 2
        basin_cy = y + h - door_area_h * 0.45
        try:
            msp.add_ellipse(
                center=(basin_cx, basin_cy), major_axis=(basin_w / 2, 0),
                ratio=basin_h / basin_w if basin_w > 0 else 0.5, dxfattribs=hatt)
        except Exception:
            bx = basin_cx - basin_w / 2
            by = basin_cy - basin_h / 2
            msp.add_lwpolyline(
                [(bx, by), (bx + basin_w, by), (bx + basin_w, by + basin_h),
                 (bx, by + basin_h), (bx, by)], dxfattribs=hatt, close=True)

    def _draw_open_shelf(self, msp, p: PlacementInfo):
        self._draw_outer_box(msp, p)
        x, y, w, h = p.x, p.y, p.width, p.height
        att = self._cab_attribs(p)
        tk = self.TOE_KICK_H
        shelf_area = h - tk
        num_shelves = 2 if w < 24 else 3
        for i in range(1, num_shelves + 1):
            sy = y + tk + (shelf_area * i / (num_shelves + 1))
            msp.add_line((x, sy), (x + w, sy), dxfattribs=att)

    def _draw_filler(self, msp, p: PlacementInfo):
        x, y, w, h = p.x, p.y, p.width, p.height
        att = self._cab_attribs(p)
        msp.add_lwpolyline(
            [(x, y), (x + w, y), (x + w, y + h), (x, y + h), (x, y)],
            dxfattribs=att, close=True)
        num_diags = max(2, int(h / 6))
        for i in range(num_diags):
            dy = y + (h * (i + 1) / (num_diags + 1))
            x1, y1 = x, dy
            x2, y2 = x + w, min(dy + w, y + h)
            msp.add_line((x1, y1), (x2, y2), dxfattribs=att)

    # ================================================================== #
    #  Countertop
    # ================================================================== #

    def _draw_countertop(self, msp, placements: List[PlacementInfo],
                          detection_result: DetectionResult):
        if not placements:
            return
        layer = self.layers["countertops"]
        color = self.colors["countertops"]
        att = {"layer": layer, "color": color}

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
            msp.add_line((min_x, ct_bottom - 0.25), (max_x, ct_bottom - 0.25), dxfattribs=att)

    # ================================================================== #
    #  Leader annotations
    # ================================================================== #

    def _add_leader_annotations(self, msp, placements: List[PlacementInfo]):
        """Add horizontal leader lines with Mott shop drawing style annotations."""
        leader_layer = self.layers["leaders"]
        leader_color = self.colors["leaders"]
        att = {"layer": leader_layer, "color": leader_color}

        runs = self._find_runs(placements)

        for run in runs:
            max_h = max(p.height for p in run)
            wall_top = max_h + self.COUNTERTOP_THICKNESS + self.BACKSPLASH_H
            run_right = max(p.x + p.width for p in run)

            # Group consecutive cabinets of the same type for shared leaders
            groups = []
            current_group = [run[0]]
            for i in range(1, len(run)):
                if run[i].casework_type == current_group[0].casework_type:
                    current_group.append(run[i])
                else:
                    groups.append(current_group)
                    current_group = [run[i]]
            groups.append(current_group)

            # Leaders originate from cabinet mid-height, angled up to a shelf above wall
            # Text sits on the horizontal shelf extending to the right
            shelf_x_start = run_right + 6.0
            shelf_length = 28.0
            leader_y_base = wall_top + 4.0   # first shelf level above wall
            leader_spacing = 8.0             # vertical spacing between shelves

            shelf_idx = 0
            for group in groups:
                ctype = group[0].casework_type
                if ctype == CaseworkType.FILLER:
                    continue

                # Origin dot: center of the group at mid-cabinet height
                group_cx = (group[0].x + group[-1].x + group[-1].width) / 2
                group_cy = max_h * 0.55

                # Shelf level for this leader
                shelf_y = leader_y_base + shelf_idx * leader_spacing

                # Diagonal leg from dot to shelf corner
                msp.add_line((group_cx, group_cy), (shelf_x_start, shelf_y), dxfattribs=att)
                # Horizontal shelf line
                msp.add_line((shelf_x_start, shelf_y), (shelf_x_start + shelf_length, shelf_y), dxfattribs=att)

                # Dot at origin (small filled circle)
                msp.add_circle((group_cx, group_cy), 0.4, dxfattribs=att)

                # Text description above the shelf line
                desc = _TYPE_DESCRIPTIONS.get(ctype, ctype.value.upper().replace("_", " "))
                text_lines = desc.split("\n")
                for li, line in enumerate(text_lines):
                    ty = shelf_y + 0.5 + li * 2.0
                    msp.add_text(line, dxfattribs={**att, "height": 1.4}).set_placement(
                        (shelf_x_start + 0.5, ty), align=TextEntityAlignment.LEFT)

                shelf_idx += 1

    # ================================================================== #
    #  Section cut markers
    # ================================================================== #

    def _add_section_marks(self, msp, placements: List[PlacementInfo]):
        """Add section cut markers at the ends of cabinet runs."""
        sec_layer = self.layers["section_marks"]
        sec_color = self.colors["section_marks"]
        att = {"layer": sec_layer, "color": sec_color}

        runs = self._find_runs(placements)
        section_id = 1

        for run in runs:
            max_h = max(p.height for p in run)
            run_end = run[-1].x + run[-1].width

            # Section mark at right end of run
            mark_x = run_end + 1.5
            mark_y_bottom = -2
            mark_y_top = max_h + self.COUNTERTOP_THICKNESS + 2

            # Vertical cut line (center linetype)
            msp.add_line((mark_x, mark_y_bottom), (mark_x, mark_y_top),
                         dxfattribs={**att, "linetype": "CENTER"})

            # Circle with section label at bottom
            label = f"RS-{section_id}"
            circle_r = 2.5
            cy = mark_y_bottom - circle_r - 1
            msp.add_circle((mark_x, cy), circle_r, dxfattribs=att)
            msp.add_text(label, dxfattribs={**att, "height": 1.3}).set_placement(
                (mark_x, cy), align=TextEntityAlignment.MIDDLE_CENTER)

            section_id += 1

    # ================================================================== #
    #  Dimensions
    # ================================================================== #

    @staticmethod
    def _to_feetinches(inches: float) -> str:
        """Convert decimal inches to feet-inches string: 3'-6\""""
        total = round(inches)
        feet = total // 12
        rem = total % 12
        if feet == 0:
            return f'{rem}"'
        elif rem == 0:
            return f"{feet}'-0\""
        else:
            return f"{feet}'-{rem}\""

    def _add_dimensions(self, msp, placements: List[PlacementInfo]):
        layer = self.layers["dimensions"]
        color = self.colors["dimensions"]
        att = {"layer": layer, "color": color}
        ext_att = {"layer": layer, "color": 8}

        runs = self._find_runs(placements)
        if not runs:
            return

        global_max_h = max(p.height for run in runs for p in run)
        wall_top = global_max_h + self.COUNTERTOP_THICKNESS + self.BACKSPLASH_H

        # --- Width dimensions on TOP (above wall/backsplash) ---
        # Individual cabinet widths at first tier
        dim_y1 = wall_top + 4.0
        # Overall run widths at second tier
        dim_y2 = wall_top + 10.0

        for run in runs:
            # Individual widths
            for p in run:
                mid_x = p.x + p.width / 2
                text = self._to_feetinches(p.width)
                msp.add_text(text, dxfattribs={**att, "height": 1.5}).set_placement(
                    (mid_x, dim_y1 + 1.0), align=TextEntityAlignment.MIDDLE_CENTER)
                # Dimension line
                msp.add_line((p.x + 0.5, dim_y1), (p.x + p.width - 0.5, dim_y1), dxfattribs=att)
                # Tick marks at each edge
                for tx in (p.x, p.x + p.width):
                    msp.add_line((tx, dim_y1 - 0.8), (tx, dim_y1 + 0.8), dxfattribs=att)
                # Extension lines from wall top to dim line
                msp.add_line((p.x, wall_top), (p.x, dim_y1 - 1.0), dxfattribs=ext_att)
                msp.add_line((p.x + p.width, wall_top), (p.x + p.width, dim_y1 - 1.0), dxfattribs=ext_att)

            # Overall run width (second tier)
            run_start = run[0].x
            run_end = run[-1].x + run[-1].width
            run_width = run_end - run_start
            if len(run) > 1:
                mid = (run_start + run_end) / 2
                text = self._to_feetinches(run_width)
                msp.add_text(text, dxfattribs={**att, "height": 1.8}).set_placement(
                    (mid, dim_y2 + 1.5), align=TextEntityAlignment.MIDDLE_CENTER)
                msp.add_line((run_start + 0.5, dim_y2), (run_end - 0.5, dim_y2), dxfattribs=att)
                for tx in (run_start, run_end):
                    msp.add_line((tx, dim_y2 - 0.8), (tx, dim_y2 + 0.8), dxfattribs=att)
                # Extension lines from first tier up
                msp.add_line((run_start, dim_y1 + 1.0), (run_start, dim_y2 - 1.0), dxfattribs=ext_att)
                msp.add_line((run_end, dim_y1 + 1.0), (run_end, dim_y2 - 1.0), dxfattribs=ext_att)

        # --- Height dimensions on LEFT side ---
        min_x = min(p.x for run in runs for p in run)
        hx = min_x - 5.0

        max_h = global_max_h
        ct_top = max_h + self.COUNTERTOP_THICKNESS

        # Full cabinet height (floor to top of cabinet body)
        msp.add_line((hx, 0), (hx, max_h), dxfattribs=att)
        msp.add_line((hx - 0.8, 0), (hx + 0.8, 0), dxfattribs=att)
        msp.add_line((hx - 0.8, max_h), (hx + 0.8, max_h), dxfattribs=att)
        msp.add_text(self._to_feetinches(max_h), dxfattribs={**att, "height": 1.5, "rotation": 90}).set_placement(
            (hx - 2.0, max_h / 2), align=TextEntityAlignment.MIDDLE_CENTER)

        # Counter height (floor to countertop top)
        hx2 = hx - 5.0
        msp.add_line((hx2, 0), (hx2, ct_top), dxfattribs={**att, "color": 8})
        msp.add_line((hx2 - 0.8, 0), (hx2 + 0.8, 0), dxfattribs={**att, "color": 8})
        msp.add_line((hx2 - 0.8, ct_top), (hx2 + 0.8, ct_top), dxfattribs={**att, "color": 8})
        msp.add_text(self._to_feetinches(ct_top), dxfattribs={**att, "height": 1.2, "rotation": 90, "color": 8}).set_placement(
            (hx2 - 2.0, ct_top / 2), align=TextEntityAlignment.MIDDLE_CENTER)

        # Toe kick height sub-dimension
        tk = self.TOE_KICK_H
        hx3 = hx - 10.0
        msp.add_line((hx3, 0), (hx3, tk), dxfattribs={**att, "color": 8})
        msp.add_line((hx3 - 0.5, 0), (hx3 + 0.5, 0), dxfattribs={**att, "color": 8})
        msp.add_line((hx3 - 0.5, tk), (hx3 + 0.5, tk), dxfattribs={**att, "color": 8})
        msp.add_text(self._to_feetinches(tk), dxfattribs={**att, "height": 1.0, "rotation": 90, "color": 8}).set_placement(
            (hx3 - 1.5, tk / 2), align=TextEntityAlignment.MIDDLE_CENTER)

    # ================================================================== #
    #  Product numbers
    # ================================================================== #

    def _add_product_numbers(self, msp, placements: List[PlacementInfo]):
        layer = self.layers["product_numbers"]
        color = self.colors["product_numbers"]
        for p in placements:
            if not p.product_number or p.product_number == "UNMATCHED":
                continue
            mid_x = p.x + p.width / 2
            label_y = p.y + p.height * 0.78
            text_h = min(1.2, p.width * 0.08)
            msp.add_text(p.product_number, dxfattribs={"layer": layer, "color": color, "height": text_h}).set_placement(
                (mid_x, label_y), align=TextEntityAlignment.MIDDLE_CENTER)

    # ================================================================== #
    #  Flags
    # ================================================================== #

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
            flag_y = (obj.estimated_height_inches or 34.75) + self.COUNTERTOP_THICKNESS + self.BACKSPLASH_H + 4
            flag_y += flag_y_offset
            flag_text = f"? {result.flag_reason}"
            msp.add_text(flag_text, dxfattribs={**att, "height": 1.0}).set_placement(
                (x, flag_y), align=TextEntityAlignment.LEFT)
            cx = x + w / 2
            cy = flag_y - 1.5
            tri_r = 1.2
            msp.add_lwpolyline([
                (cx, cy + tri_r), (cx - tri_r * 0.866, cy - tri_r * 0.5),
                (cx + tri_r * 0.866, cy - tri_r * 0.5), (cx, cy + tri_r),
            ], dxfattribs=att, close=True)
            msp.add_text("!", dxfattribs={**att, "height": 1.2}).set_placement(
                (cx, cy), align=TextEntityAlignment.MIDDLE_CENTER)
            flag_y_offset += 3.5

    # ================================================================== #
    #  Elevation marker & title block (Mott format)
    # ================================================================== #

    def _add_elevation_marker(self, msp, placements: List[PlacementInfo],
                               elevation_label: str, room_name: str, title: str):
        """Add elevation circle marker and title block matching Mott format."""
        tb_layer = self.layers["titleblock"]
        tb_color = self.colors["titleblock"]
        att = {"layer": tb_layer, "color": tb_color}

        if not placements:
            return

        first_x = placements[0].x
        total_end = max(p.x + p.width for p in placements)

        # Position title block below dimensions
        tb_y = -16.0

        # --- Elevation circle marker (bottom left) ---
        circle_r = 4.0
        cx = first_x - 8
        cy = tb_y - 5

        # Outer circle
        msp.add_circle((cx, cy), circle_r, dxfattribs=att)
        # Elevation label inside circle
        msp.add_text(elevation_label, dxfattribs={**att, "height": 3.0}).set_placement(
            (cx, cy), align=TextEntityAlignment.MIDDLE_CENTER)

        # --- Title text to the right of circle ---
        title_x = cx + circle_r + 3
        # Room / elevation name
        display_name = room_name if room_name else title
        msp.add_text(display_name, dxfattribs={**att, "height": 2.2}).set_placement(
            (title_x, cy + 1.5), align=TextEntityAlignment.LEFT)

        # Scale and reference line
        msp.add_line((title_x, cy - 0.5), (title_x + 60, cy - 0.5), dxfattribs={**att, "color": 8})
        scale_text = '1/4" = 1\'-0"    REFERENCED ON  A2 / A407'
        msp.add_text(scale_text, dxfattribs={**att, "height": 1.2, "color": 8}).set_placement(
            (title_x, cy - 2.5), align=TextEntityAlignment.LEFT)

        # --- Stats line (subtle, below title) ---
        ann_att = {"layer": self.layers["annotations"], "color": 8}
        stats_y = cy - 6
        total_matched = len(placements)
        total_width = sum(p.width for p in placements)
        confidences = [p.confidence for p in placements if p.confidence > 0]
        avg_conf = sum(confidences) / len(confidences) if confidences else 0

        stats = f"AI Pipeline: {total_matched} items matched  |  Avg confidence: {avg_conf:.0%}  |  Total width: {total_width:.0f}\""
        msp.add_text(stats, dxfattribs={**ann_att, "height": 1.0}).set_placement(
            (title_x, stats_y), align=TextEntityAlignment.LEFT)

        msp.add_text("Generated by Casework AI Pipeline - Mott Manufacturing",
                     dxfattribs={**ann_att, "height": 0.8}).set_placement(
            (title_x, stats_y - 2), align=TextEntityAlignment.LEFT)
