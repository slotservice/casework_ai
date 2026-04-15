"""
CAD Writer Module
Generates clean, editable DXF output files using ezdxf.
Places matched blocks, dimensions, countertop outlines, annotations, and flags.
"""

import os
import logging
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


class CADWriter:
    """Generates DXF output files with matched casework blocks."""

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
        """
        Generate a complete DXF file from match results.

        Args:
            match_results: List of block matching results
            detection_result: Original detection result with scale info
            output_path: Path to save the DXF file
            title: Drawing title

        Returns:
            Path to the generated DXF file
        """
        logger.info(f"Generating DXF output: {output_path}")

        # Create new DXF document (R2010 format for wide compatibility)
        doc = ezdxf.new("R2010")
        msp = doc.modelspace()

        # Setup layers
        self._setup_layers(doc)

        # Calculate placement coordinates
        scale = detection_result.scale_factor if detection_result.scale_factor > 0 else 1.0
        placements = self._calculate_placements(match_results, scale)

        # Draw cabinet outlines and blocks
        for placement in placements:
            self._draw_cabinet_block(msp, placement)

        # Draw countertop outline
        self._draw_countertop(msp, placements, detection_result)

        # Add dimensions
        self._add_dimensions(msp, placements)

        # Add product numbers
        self._add_product_numbers(msp, placements)

        # Add flags for uncertain items
        self._add_flags(msp, match_results, scale)

        # Add title block
        self._add_title_block(msp, title, match_results)

        # Save
        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
        doc.saveas(output_path)
        logger.info(f"DXF saved to {output_path}")
        return output_path

    def _setup_layers(self, doc: ezdxf.document.Drawing):
        """Create all required layers in the DXF document."""
        for key, layer_name in self.layers.items():
            color = self.colors.get(key, 7)
            doc.layers.add(layer_name, color=color)

    def _calculate_placements(self, match_results: List[MatchResult],
                               scale: float) -> List[PlacementInfo]:
        """Calculate DXF placement coordinates for all matched items."""
        placements = []
        current_x = 0.0

        for result in match_results:
            obj = result.detected_object
            if obj.casework_type == CaseworkType.COUNTERTOP:
                continue  # Countertop handled separately

            # Calculate width and height in inches
            width = obj.estimated_width_inches or (obj.bbox[2] / scale if scale > 0 else 24)
            height = obj.estimated_height_inches or (obj.bbox[3] / scale if scale > 0 else 34.75)

            # Determine layer and color based on type
            layer_key = self._type_to_layer_key(obj.casework_type)

            product_num = result.product_number or "UNMATCHED"

            # Label for annotation
            label = f"{obj.casework_type.value}"
            if result.best_match:
                label = result.best_match.description or result.best_match.product_number

            # Extract features for drawing details
            drawer_count = obj.features.get("drawer_count", 0) if obj.features else 0
            has_center_vert = obj.features.get("has_center_vertical", False) if obj.features else False

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
            )
            placements.append(placement)
            current_x += width

        return placements

    def _type_to_layer_key(self, casework_type: CaseworkType) -> str:
        """Map a casework type to a layer key."""
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

    def _draw_cabinet_block(self, msp, placement: PlacementInfo):
        """Draw a cabinet block as a rectangle with internal details."""
        x, y = placement.x, placement.y
        w, h = placement.width, placement.height

        # Cabinet outline rectangle
        points = [
            (x, y), (x + w, y), (x + w, y + h), (x, y + h), (x, y)
        ]
        msp.add_lwpolyline(points, dxfattribs={
            "layer": placement.layer,
            "color": placement.color,
        })

        # Toe kick line (4" from bottom)
        toe_kick_height = 4.0
        msp.add_line(
            (x, y + toe_kick_height), (x + w, y + toe_kick_height),
            dxfattribs={"layer": placement.layer, "color": placement.color}
        )

        # Filler strips and end panels get no interior details
        if placement.casework_type in (CaseworkType.FILLER, CaseworkType.END_PANEL):
            return

        # Draw drawer lines if this is a drawer unit
        is_drawer = (placement.casework_type == CaseworkType.DRAWER_UNIT or
                     placement.drawer_count >= 3)
        if is_drawer:
            num_drawers = max(placement.drawer_count, 4)
            drawer_area = h - toe_kick_height
            drawer_h = drawer_area / num_drawers
            for i in range(1, num_drawers):
                dy = y + toe_kick_height + i * drawer_h
                msp.add_line(
                    (x, dy), (x + w, dy),
                    dxfattribs={"layer": placement.layer, "color": placement.color}
                )
                # Drawer handle
                msp.add_circle(
                    (x + w / 2, dy - drawer_h / 2), radius=0.5,
                    dxfattribs={"layer": placement.layer, "color": placement.color}
                )
        else:
            # Door cabinet - add door details
            if w > 24 or placement.has_center_vertical:
                # Double door - center line
                msp.add_line(
                    (x + w / 2, y + toe_kick_height), (x + w / 2, y + h),
                    dxfattribs={"layer": placement.layer, "color": placement.color}
                )
            # Door handle marks
            handle_y = y + h * 0.6
            if w > 24 or placement.has_center_vertical:
                msp.add_circle(
                    (x + w / 2 - 2, handle_y), radius=0.5,
                    dxfattribs={"layer": placement.layer, "color": placement.color}
                )
                msp.add_circle(
                    (x + w / 2 + 2, handle_y), radius=0.5,
                    dxfattribs={"layer": placement.layer, "color": placement.color}
                )
            else:
                msp.add_circle(
                    (x + w - 3, handle_y), radius=0.5,
                    dxfattribs={"layer": placement.layer, "color": placement.color}
                )

    def _draw_countertop(self, msp, placements: List[PlacementInfo],
                          detection_result: DetectionResult):
        """Draw countertop outline above the cabinets."""
        if not placements:
            return

        layer = self.layers["countertops"]
        color = self.colors["countertops"]

        # Countertop spans the full width, 1" overhang on each side
        min_x = min(p.x for p in placements) - 1
        max_x = max(p.x + p.width for p in placements) + 1
        max_h = max(p.height for p in placements)

        ct_bottom = max_h
        ct_top = max_h + 1.5  # 1.5" thick countertop

        points = [
            (min_x, ct_bottom), (max_x, ct_bottom),
            (max_x, ct_top), (min_x, ct_top), (min_x, ct_bottom)
        ]
        msp.add_lwpolyline(points, dxfattribs={"layer": layer, "color": color})

    def _add_dimensions(self, msp, placements: List[PlacementInfo]):
        """Add dimension annotations to the drawing."""
        layer = self.layers["dimensions"]
        color = self.colors["dimensions"]
        dim_y = -3.0  # Below the cabinets

        for p in placements:
            # Width dimension below each cabinet
            text = f'{p.width:.0f}"'
            mid_x = p.x + p.width / 2
            msp.add_text(
                text,
                dxfattribs={
                    "layer": layer,
                    "color": color,
                    "height": 1.5,
                },
            ).set_placement((mid_x, dim_y), align=TextEntityAlignment.MIDDLE_CENTER)

            # Dimension lines
            msp.add_line(
                (p.x, dim_y + 0.8), (p.x + p.width, dim_y + 0.8),
                dxfattribs={"layer": layer, "color": color}
            )
            # Tick marks
            msp.add_line(
                (p.x, dim_y + 0.3), (p.x, dim_y + 1.3),
                dxfattribs={"layer": layer, "color": color}
            )
            msp.add_line(
                (p.x + p.width, dim_y + 0.3), (p.x + p.width, dim_y + 1.3),
                dxfattribs={"layer": layer, "color": color}
            )

        # Overall dimension
        if placements:
            total_start = placements[0].x
            total_end = placements[-1].x + placements[-1].width
            total_width = total_end - total_start
            overall_dim_y = dim_y - 4.0

            text = f'{total_width:.0f}" OVERALL'
            msp.add_text(
                text,
                dxfattribs={
                    "layer": layer,
                    "color": color,
                    "height": 2.0,
                },
            ).set_placement(((total_start + total_end) / 2, overall_dim_y),
                             align=TextEntityAlignment.MIDDLE_CENTER)

            msp.add_line(
                (total_start, overall_dim_y + 1.2), (total_end, overall_dim_y + 1.2),
                dxfattribs={"layer": layer, "color": color}
            )

    def _add_product_numbers(self, msp, placements: List[PlacementInfo]):
        """Add product number labels inside each cabinet."""
        layer = self.layers["product_numbers"]
        color = self.colors["product_numbers"]

        for p in placements:
            if p.product_number and p.product_number != "UNMATCHED":
                mid_x = p.x + p.width / 2
                mid_y = p.y + p.height / 2

                msp.add_text(
                    p.product_number,
                    dxfattribs={
                        "layer": layer,
                        "color": color,
                        "height": 1.2,
                    },
                ).set_placement((mid_x, mid_y), align=TextEntityAlignment.MIDDLE_CENTER)

    def _add_flags(self, msp, match_results: List[MatchResult], scale: float):
        """Add visual flags for uncertain or unmatched items."""
        layer = self.layers["flags"]
        color = self.colors["flags"]

        flag_y_offset = 0.0
        for result in match_results:
            if not result.is_flagged:
                continue

            obj = result.detected_object
            x = obj.bbox[0] / scale if scale > 0 else obj.bbox[0]
            w = obj.estimated_width_inches or 24

            flag_y = (obj.estimated_height_inches or 34.75) + 5
            flag_y += flag_y_offset

            # Flag marker (triangle)
            flag_text = f"? {result.flag_reason}"
            msp.add_text(
                flag_text,
                dxfattribs={
                    "layer": layer,
                    "color": color,
                    "height": 1.0,
                },
            ).set_placement((x, flag_y), align=TextEntityAlignment.LEFT)

            # Draw attention marker
            msp.add_circle(
                (x + w / 2, flag_y - 1.5), radius=1.0,
                dxfattribs={"layer": layer, "color": color}
            )
            msp.add_text(
                "!",
                dxfattribs={
                    "layer": layer,
                    "color": color,
                    "height": 1.5,
                },
            ).set_placement((x + w / 2, flag_y - 1.5), align=TextEntityAlignment.MIDDLE_CENTER)

            flag_y_offset += 3.0

    def _add_title_block(self, msp, title: str, match_results: List[MatchResult]):
        """Add a simple title block to the drawing."""
        layer = self.layers["annotations"]
        color = self.colors["annotations"]

        total_matched = len([r for r in match_results if r.best_match])
        total_flagged = len([r for r in match_results if r.is_flagged])
        total = len(match_results)

        title_y = -15.0
        msp.add_text(
            title,
            dxfattribs={"layer": layer, "color": 7, "height": 3.0},
        ).set_placement((0, title_y), align=TextEntityAlignment.LEFT)

        msp.add_text(
            f"Generated by Casework AI Pipeline | "
            f"Items: {total} | Matched: {total_matched} | Flagged: {total_flagged}",
            dxfattribs={"layer": layer, "color": color, "height": 1.5},
        ).set_placement((0, title_y - 4), align=TextEntityAlignment.LEFT)
