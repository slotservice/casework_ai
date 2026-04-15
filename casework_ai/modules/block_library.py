"""
Block Library Loader Module
Loads, indexes, and manages the Mott casework DWG block library.
Creates a searchable index mapping product numbers to block files.
"""

import os
import re
import json
import logging
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class BlockInfo:
    """Information about a single DWG block."""
    product_number: str
    filename: str
    filepath: str
    library: str  # 'front_view' or 'section_metal'
    category: str = ""  # decoded category
    width_inches: Optional[float] = None
    config_type: str = ""  # 'open', 'door', 'door_drawer', 'drawer', etc.
    hand: str = ""  # 'right', 'left', 'both', ''
    description: str = ""


# Mott product number decoding tables
# Width codes (positions 2-3 of the 7-digit number for 1XXXXXX base cabinets)
WIDTH_MAP = {
    "01": 12, "02": 12,  # 12 inch
    "10": 18, "11": 18,  # 18 inch
    "19": 15, "09": 15,  # 15 inch
    "12": 24, "20": 24,  # 24 inch
    "13": 30,             # 30 inch
    "14": 36, "08": 36,  # 36 inch
    "15": 48,             # 48 inch
    "16": 21,             # 21 inch / 513mm
    "17": 42,             # 42 inch / 1000mm
    "18": 42,             # 42 inch
    "80": 36,             # 36 inch alt
    "91": 15,             # 15 inch alt
}

# Fallback: for unmapped 2-digit width codes, the second digit encodes the width tier.
# This covers codes 21-99, X1-X9, etc. that follow the Mott extended numbering
# where the first digit is a material/variant indicator and the second is the size code.
_SECOND_DIGIT_WIDTH = {
    "0": 12, "1": 18, "2": 24, "3": 30, "4": 36,
    "5": 48, "6": 21, "7": 42, "8": 42, "9": 15,
}


def decode_width(width_code: str) -> Optional[float]:
    """Decode a 2-character width code to inches, with fallback."""
    width = WIDTH_MAP.get(width_code)
    if width is not None:
        return float(width)
    # Fallback: use second digit as width tier
    if len(width_code) >= 2:
        return float(_SECOND_DIGIT_WIDTH.get(width_code[-1], 0)) or None
    return None

# Configuration type codes (positions 4-5)
CONFIG_MAP = {
    "00": "open",
    "01": "full_door",
    "02": "door_drawer",
    "03": "drawer",
    "04": "4_drawer",
    "05": "door_2drawer",
    "09": "shelf",
    "0A": "special_a",
    "0B": "special_b",
    "50": "open_500",
    "10": "variant_10",
    "11": "variant_11",
    "12": "variant_12",
    "22": "variant_22",
    "33": "variant_33",
    "44": "variant_44",
    "55": "variant_55",
    "66": "variant_66",
    "77": "variant_77",
    "88": "variant_88",
    "90": "variant_90",
    "93": "shelf_unit",
    "96": "shelf_wide",
}

# Hand/hinge codes (position 6)
HAND_MAP = {
    "0": "both",
    "1": "right",
    "2": "left",
    "3": "right_alt",
}

# Category prefixes for named blocks
NAMED_BLOCK_CATEGORIES = {
    "GLS": "gable_leg",
    "GLD": "gable_leg_door",
    "FLS": "filler_strip",
    "FLW": "filler_strip_wood",
    "FSB": "filler_strip_base",
    "FSH": "filler_shelf",
    "FWR": "filler_wrap",
    "FPA": "filler_panel_assembly",
    "FBP": "filler_back_panel",
    "FDC": "filler_dc",
    "SCP": "scribe_panel",
    "SDC": "service_duct_cover",
    "WPA": "wall_panel_assembly",
    "WRS": "wall_reagent_shelf",
    "TAB": "table",
    "TAC": "table_cabinet",
    "TAA": "table_assembly",
    "TCB": "table_cabinet_base",
    "TCC": "table_cabinet_combo",
    "ROA": "row_assembly",
    "RTD": "return_detail",
    "SUF": "surface",
    "SWF": "side_wall_filler",
    "WFP": "wall_filler_panel",
    "WFS": "wall_filler_strip",
    "CAS": "casework_assembly",
    "CCS": "countertop_section",
    "CDL": "cabinet_detail",
    "CFC": "corner_filler_cabinet",
    "CIP": "cabinet_island_panel",
    "CIR": "cabinet_island_return",
    "CIS": "cabinet_island_side",
    "CRA": "cabinet_row_assembly",
    "CWP": "cabinet_wall_panel",
    "CWR": "cabinet_wall_return",
    "CWS": "cabinet_wall_side",
    "ECC": "end_cap_cabinet",
    "ECS": "end_cap_side",
    "FFC": "full_face_cabinet",
    "FFL": "full_face_left",
    "FFR": "full_face_right",
    "FPS": "filler_panel_side",
    "LFH": "lab_fume_hood",
    "MWS": "mobile_work_station",
    "MWD": "mobile_work_detail",
    "OTF": "option_feature",
    "RSA": "reagent_shelf_assembly",
    "RSG": "reagent_shelf_glass",
    "RSS": "reagent_shelf_side",
    "SAG": "shelf_assembly_glass",
    "SAR": "shelf_assembly_rack",
    "SAV": "shelf_assembly_vent",
    "STA": "shelf_top_assembly",
    "VOA": "vent_option_assembly",
    "VPF": "vent_panel_face",
    "VPL": "vent_panel_left",
    "VPR": "vent_panel_right",
    "VPS": "vent_panel_side",
    "VTD": "vent_top_detail",
    "VTL": "vent_top_left",
    "BIU": "built_in_unit",
    "BRS": "bracket_shelf",
    "BRE": "bracket_end",
    "BRM": "bracket_mid",
    "VRF": "vent_return_fixture",
    "PB": "pegboard",
    "AUA": "auto_assembly_a",
    "AUC": "auto_assembly_c",
    "BUA": "built_unit_a",
    "BUC": "built_unit_c",
    "BWU": "built_wall_unit",
    "DAG": "detail_assembly_glass",
    "EOD": "end_option_door",
    "EOP": "end_option_panel",
    "EOS": "end_option_side",
    "ERS": "end_return_side",
    "FEA": "front_end_assembly",
    "FEC": "front_end_cabinet",
    "FRA": "front_row_assembly",
    "FRB": "front_row_bracket",
    "FSC": "filler_strip_corner",
    "FSF": "filler_strip_front",
    "FSW": "filler_strip_wall",
    "FWF": "filler_wall_front",
    "FNF": "front_notch_filler",
    "FNS": "front_notch_side",
    "FPF": "front_panel_filler",
    "FPL": "front_panel_left",
    "FPR": "front_panel_right",
    "SDP": "side_detail_panel",
    "SOD": "side_option_door",
    "SOP": "side_option_panel",
    "SOS": "side_option_side",
    "SRS": "side_return_side",
}


class BlockLibrary:
    """Manages the Mott DWG block library."""

    def __init__(self, front_views_dir: str, section_dir: str, config=None):
        self.front_views_dir = Path(front_views_dir)
        self.section_dir = Path(section_dir)
        self.config = config

        # Additional library directories (e.g., wood casework)
        self.extra_dirs: List[Tuple[str, str]] = []  # (path, library_type)

        self.blocks: Dict[str, BlockInfo] = {}
        self.by_category: Dict[str, List[BlockInfo]] = {}
        self.by_width: Dict[float, List[BlockInfo]] = {}
        self.by_config: Dict[str, List[BlockInfo]] = {}

    def add_directory(self, path: str, library_type: str):
        """Add an additional block library directory."""
        self.extra_dirs.append((path, library_type))

    def load(self) -> int:
        """Load and index all blocks from the library directories."""
        count = 0

        if self.front_views_dir.exists():
            count += self._load_directory(self.front_views_dir, "front_view")

        if self.section_dir.exists():
            count += self._load_directory(self.section_dir, "section_metal")

        # Load additional directories
        for dir_path, lib_type in self.extra_dirs:
            p = Path(dir_path)
            if p.exists():
                count += self._load_directory(p, lib_type)

        self._build_indexes()
        logger.info(f"Loaded {count} blocks ({len(self.by_category)} categories, {len(self.by_width)} widths)")
        return count

    def _load_directory(self, directory: Path, library: str) -> int:
        """Load all DWG files from a directory."""
        count = 0
        for item in sorted(directory.iterdir()):
            if item.is_file() and item.suffix.lower() == ".dwg":
                product_num = item.stem
                block = self._decode_block(product_num, str(item), library)
                self.blocks[product_num] = block
                count += 1
        return count

    def _decode_block(self, product_number: str, filepath: str, library: str) -> BlockInfo:
        """Decode a product number into a BlockInfo."""
        block = BlockInfo(
            product_number=product_number,
            filename=os.path.basename(filepath),
            filepath=filepath,
            library=library,
        )

        # Strip wood suffix "W" for decoding (e.g., "1010011W" -> "1010011")
        # Also handle variant suffixes like "-40", "-30" in section views
        decode_num = product_number
        if decode_num.endswith("W"):
            decode_num = decode_num[:-1]
            block.description = "Wood "
        else:
            block.description = ""

        # Strip variant suffixes like "-40", "-30", "-08"
        if "-" in decode_num:
            decode_num = decode_num.split("-")[0]

        # Check if it's a named block (starts with letters)
        # Handle X- prefix blocks (e.g., "X-GLS1022W" -> prefix "GLS")
        check_num = decode_num
        if check_num.startswith("X-"):
            check_num = check_num[2:]

        if check_num and check_num[0].isalpha():
            prefix = ""
            for char in check_num:
                if char.isalpha():
                    prefix += char
                else:
                    break

            block.category = NAMED_BLOCK_CATEGORIES.get(prefix, f"named_{prefix.lower()}")
            block.description += f"Named block: {prefix}"

            # Try to extract width from suffix digits
            suffix = check_num[len(prefix):]
            if suffix and suffix.isdigit() and len(suffix) >= 4:
                try:
                    width_val = int(suffix[:2])
                    if 10 <= width_val <= 96:
                        block.width_inches = width_val
                except ValueError:
                    pass
            return block

        # Numeric product number - decode based on Mott system
        if len(decode_num) >= 7 and decode_num[:1].isdigit():
            series = decode_num[0]
            width_code = decode_num[1:3]
            config_code = decode_num[3:5]
            hand_code = decode_num[5] if len(decode_num) > 5 else ""
            variant = decode_num[6] if len(decode_num) > 6 else ""

            # Decode width (with fallback for extended codes)
            block.width_inches = decode_width(width_code)

            # Decode configuration
            block.config_type = CONFIG_MAP.get(config_code, f"config_{config_code}")

            # Decode hand
            block.hand = HAND_MAP.get(hand_code, "")

            # Set category based on series
            if series == "1":
                block.category = "base_cabinet"
            elif series == "3":
                block.category = "accessory"
            elif series == "5":
                block.category = "wall_cabinet"
            elif series == "6":
                block.category = "floor_cabinet"
            elif series == "7":
                block.category = "specialty"
            elif series == "8":
                block.category = "suspended"
            elif series == "9":
                block.category = "option"
            else:
                block.category = f"series_{series}"

            block.description += f"{block.category} {block.width_inches}\" {block.config_type} {block.hand}".strip()
        else:
            block.category = "unclassified"
            block.description = f"Unclassified: {product_number}"

        return block

    def _build_indexes(self):
        """Build lookup indexes for fast searching."""
        self.by_category = {}
        self.by_width = {}
        self.by_config = {}

        for block in self.blocks.values():
            # Index by category
            if block.category not in self.by_category:
                self.by_category[block.category] = []
            self.by_category[block.category].append(block)

            # Index by width
            if block.width_inches is not None:
                if block.width_inches not in self.by_width:
                    self.by_width[block.width_inches] = []
                self.by_width[block.width_inches].append(block)

            # Index by config type
            if block.config_type:
                if block.config_type not in self.by_config:
                    self.by_config[block.config_type] = []
                self.by_config[block.config_type].append(block)

    def search(self, category: str = None, width: float = None,
               config_type: str = None, hand: str = None,
               library: str = None) -> List[BlockInfo]:
        """Search for blocks matching given criteria."""
        results = list(self.blocks.values())

        if category:
            results = [b for b in results if b.category == category]
        if width is not None:
            tolerance = 2.0
            if self.config:
                tolerance = self.config.get("matching.size_tolerance_inches", 2.0)
            results = [b for b in results if b.width_inches and abs(b.width_inches - width) <= tolerance]
        if config_type:
            results = [b for b in results if b.config_type == config_type]
        if hand:
            results = [b for b in results if b.hand == hand or b.hand == "both"]
        if library:
            results = [b for b in results if b.library == library]

        return results

    def get_block(self, product_number: str) -> Optional[BlockInfo]:
        """Get a specific block by product number."""
        return self.blocks.get(product_number)

    def export_index(self, output_path: str):
        """Export the block index to JSON for inspection."""
        index = {}
        for pn, block in sorted(self.blocks.items()):
            index[pn] = {
                "category": block.category,
                "width_inches": block.width_inches,
                "config_type": block.config_type,
                "hand": block.hand,
                "library": block.library,
                "description": block.description,
            }

        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(index, f, indent=2)

        logger.info(f"Exported block index ({len(index)} entries) to {output_path}")

    def summary(self) -> str:
        """Return a summary of the loaded library."""
        lines = [
            "=== BLOCK LIBRARY SUMMARY ===",
            f"Total blocks: {len(self.blocks)}",
            "",
            "By category:",
        ]
        for cat in sorted(self.by_category.keys()):
            lines.append(f"  {cat}: {len(self.by_category[cat])}")

        lines.append("")
        lines.append("By width (inches):")
        for w in sorted(self.by_width.keys()):
            lines.append(f"  {w}\": {len(self.by_width[w])}")

        return "\n".join(lines)
