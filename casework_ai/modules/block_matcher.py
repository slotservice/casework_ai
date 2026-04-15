"""
Block Matching Engine Module
Matches detected casework objects to Mott product numbers from the block library.
Uses type, size, configuration, and contextual rules to find the best match.
Includes fallback logic and confidence scoring.
"""

import logging
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field

from .object_detector import DetectedObject, CaseworkType
from .block_library import BlockLibrary, BlockInfo

logger = logging.getLogger(__name__)


@dataclass
class MatchCandidate:
    """A potential block match for a detected object."""
    block: BlockInfo
    score: float  # 0.0 to 1.0
    match_reasons: List[str] = field(default_factory=list)
    penalty_reasons: List[str] = field(default_factory=list)


@dataclass
class MatchResult:
    """The matching result for a single detected object."""
    detected_object: DetectedObject
    best_match: Optional[BlockInfo] = None
    confidence: float = 0.0
    candidates: List[MatchCandidate] = field(default_factory=list)
    is_flagged: bool = False
    flag_reason: str = ""
    product_number: str = ""
    notes: str = ""


class BlockMatcher:
    """Matches detected objects to Mott block library entries."""

    def __init__(self, block_library: BlockLibrary, config=None):
        self.library = block_library
        self.config = config

        self.min_confidence = 0.35
        self.high_confidence = 0.7
        self.size_tolerance = 2.0  # inches

        if config:
            self.min_confidence = config.get("matching.min_confidence", 0.5)
            self.high_confidence = config.get("matching.high_confidence_threshold", 0.8)
            self.size_tolerance = config.get("matching.size_tolerance_inches", 2.0)

        # Rules loaded from rule trainer
        self.custom_rules: List[Dict] = []

    def match_all(self, objects: List[DetectedObject]) -> List[MatchResult]:
        """Match all detected objects to blocks."""
        results = []
        for obj in objects:
            result = self.match_single(obj)
            results.append(result)

        # Post-processing: check for context-based improvements
        self._context_refinement(results)

        matched = len([r for r in results if r.best_match])
        flagged = len([r for r in results if r.is_flagged])
        logger.info(f"Matching complete: {matched}/{len(results)} matched, {flagged} flagged")
        return results

    def match_single(self, obj: DetectedObject) -> MatchResult:
        """Find the best block match for a single detected object."""
        result = MatchResult(detected_object=obj)

        # Apply custom rules first
        custom_match = self._apply_custom_rules(obj)
        if custom_match:
            result.best_match = custom_match.block
            result.confidence = custom_match.score
            result.candidates = [custom_match]
            result.product_number = custom_match.block.product_number
            result.notes = "Matched via custom rule"
            return result

        # Map detected type to library search parameters
        search_params = self._type_to_search_params(obj)
        if not search_params:
            result.is_flagged = True
            result.flag_reason = f"No search strategy for type: {obj.casework_type.value}"
            return result

        # Search the library
        candidates = self._find_candidates(obj, search_params)
        result.candidates = candidates

        if candidates:
            best = max(candidates, key=lambda c: c.score)
            if best.score >= self.min_confidence:
                result.best_match = best.block
                result.confidence = best.score
                result.product_number = best.block.product_number
                result.notes = "; ".join(best.match_reasons)
            else:
                result.is_flagged = True
                result.flag_reason = f"Best match score too low: {best.score:.2f} < {self.min_confidence}"
                result.notes = f"Best candidate: {best.block.product_number} ({best.score:.2f})"
        else:
            result.is_flagged = True
            result.flag_reason = "No matching blocks found in library"

        return result

    def _type_to_search_params(self, obj: DetectedObject) -> Optional[Dict]:
        """Convert a casework type to block library search parameters."""
        params = {}

        type_map = {
            CaseworkType.BASE_CABINET: {"category": "base_cabinet"},
            CaseworkType.WALL_CABINET: {"category": "wall_cabinet"},
            CaseworkType.SINK: {"category": "base_cabinet", "prefer_config": "full_door"},
            CaseworkType.SINK_CABINET: {"category": "base_cabinet", "prefer_config": "full_door"},
            CaseworkType.DRAWER_UNIT: {"category": "base_cabinet", "prefer_config": "drawer"},
            CaseworkType.OPEN_SHELF: {"category": "base_cabinet", "prefer_config": "open"},
            CaseworkType.FILLER: {"category": "filler_strip"},
            CaseworkType.FIXTURE: {"category": "specialty"},
            CaseworkType.COUNTERTOP: {"category": "countertop_section"},
            CaseworkType.PEGBOARD: {"category": "specialty"},
            CaseworkType.FUME_HOOD: {"category": "named_lfh"},
            CaseworkType.END_PANEL: {"category": "end_cap_cabinet"},
            CaseworkType.UNKNOWN: {"category": "base_cabinet"},
        }

        base_params = type_map.get(obj.casework_type)
        if not base_params:
            return None

        params.update(base_params)

        # Add width constraint if estimated
        if obj.estimated_width_inches:
            params["width"] = obj.estimated_width_inches

        return params

    def _find_candidates(self, obj: DetectedObject, search_params: Dict) -> List[MatchCandidate]:
        """Search library and score candidates."""
        category = search_params.get("category")
        width = search_params.get("width")
        prefer_config = search_params.get("prefer_config")

        # Search with width tolerance
        blocks = self.library.search(
            category=category,
            width=width,
            library="front_view"
        )

        candidates = []
        for block in blocks:
            score, reasons, penalties = self._score_candidate(obj, block, search_params)
            if score > 0.1:
                candidates.append(MatchCandidate(
                    block=block,
                    score=score,
                    match_reasons=reasons,
                    penalty_reasons=penalties,
                ))

        # Sort by score descending
        candidates.sort(key=lambda c: c.score, reverse=True)

        # Keep top 5 candidates
        return candidates[:5]

    def _score_candidate(self, obj: DetectedObject, block: BlockInfo,
                         search_params: Dict) -> Tuple[float, List[str], List[str]]:
        """Score how well a block matches a detected object.

        Scoring breakdown:
          Width match:   0.0 - 0.40  (most important - exact match rewards heavily)
          Config match:  0.0 - 0.20  (drawer vs door vs open)
          Features:      0.0 - 0.15  (visual features corroborate classification)
          Preferences:   0.0 - 0.07  (hand, wood)
          Base:          0.20        (category match baseline)
          Total max:     ~1.0
        """
        score = 0.20  # lower base - category match alone shouldn't be confident
        reasons = ["Category match"]
        penalties = []

        # Width match (most important factor - 40% of total possible score)
        if obj.estimated_width_inches and block.width_inches:
            width_diff = abs(obj.estimated_width_inches - block.width_inches)
            if width_diff < 0.5:
                score += 0.40
                reasons.append(f"Exact width match ({block.width_inches}\")")
            elif width_diff < 1.5:
                score += 0.30
                reasons.append(f"Close width match ({block.width_inches}\" vs {obj.estimated_width_inches:.0f}\")")
            elif width_diff < self.size_tolerance:
                score += 0.15
                reasons.append(f"Approximate width ({block.width_inches}\" vs {obj.estimated_width_inches:.0f}\")")
            else:
                score -= 0.15
                penalties.append(f"Width mismatch ({block.width_inches}\" vs {obj.estimated_width_inches:.0f}\")")

        # Configuration preference (20% of total)
        prefer_config = search_params.get("prefer_config")
        if prefer_config:
            if block.config_type == prefer_config:
                score += 0.20
                reasons.append(f"Config match: {prefer_config}")
            elif block.config_type and prefer_config in ("drawer",) and block.config_type in ("4_drawer", "door_drawer"):
                score += 0.12
                reasons.append(f"Related config: {block.config_type}")
            elif block.config_type:
                score -= 0.08
                penalties.append(f"Config mismatch: want {prefer_config}, got {block.config_type}")

        # Feature-based scoring (15% of total)
        features = obj.features
        if features:
            drawer_count = features.get("drawer_count", 0)
            h_line_groups = features.get("horizontal_line_groups", 0)

            # Drawer features
            has_drawer_features = drawer_count >= 2 or h_line_groups >= 3
            is_drawer_block = block.config_type in ("drawer", "4_drawer", "door_drawer", "door_2drawer")

            if has_drawer_features and is_drawer_block:
                score += 0.15
                reasons.append(f"Drawer features confirmed ({drawer_count} drawers, {h_line_groups} h-lines)")
            elif has_drawer_features and block.config_type in ("full_door", "open"):
                score -= 0.12
                penalties.append("Drawer features detected but block is door/open")

            # Door features
            if features.get("has_center_vertical") and block.config_type and "door" in block.config_type:
                score += 0.10
                reasons.append("Double door pattern confirmed")
            elif features.get("has_center_vertical") and is_drawer_block:
                score -= 0.05
                penalties.append("Center line suggests doors, not drawers")

            # Sink features
            if features.get("has_circle") and obj.casework_type == CaseworkType.SINK_CABINET:
                score += 0.10
                reasons.append("Sink basin detected")

        # Prefer right-hand (standard)
        if block.hand == "right":
            score += 0.02
            reasons.append("Standard right-hand")

        # Prefer wood blocks (W suffix) for wood casework projects
        if block.product_number.endswith("W"):
            score += 0.05
            reasons.append("Wood block")

        return max(0, min(1.0, score)), reasons, penalties

    def _apply_custom_rules(self, obj: DetectedObject) -> Optional[MatchCandidate]:
        """Apply user-defined custom rules for matching."""
        for rule in self.custom_rules:
            if self._rule_matches(rule, obj):
                product_num = rule.get("assign_product")
                if product_num:
                    block = self.library.get_block(product_num)
                    if block:
                        return MatchCandidate(
                            block=block,
                            score=0.95,
                            match_reasons=[f"Custom rule: {rule.get('description', 'user rule')}"],
                        )
        return None

    def _rule_matches(self, rule: Dict, obj: DetectedObject) -> bool:
        """Check if a custom rule's conditions match a detected object."""
        conditions = rule.get("conditions", {})

        if "type" in conditions:
            if obj.casework_type.value != conditions["type"]:
                return False

        if "min_width" in conditions and obj.estimated_width_inches:
            if obj.estimated_width_inches < conditions["min_width"]:
                return False

        if "max_width" in conditions and obj.estimated_width_inches:
            if obj.estimated_width_inches > conditions["max_width"]:
                return False

        if "has_circle" in conditions:
            if obj.features.get("has_circle") != conditions["has_circle"]:
                return False

        return True

    def _context_refinement(self, results: List[MatchResult]):
        """Refine matches based on context of neighboring items."""
        for i, result in enumerate(results):
            if not result.is_flagged:
                continue

            obj = result.detected_object
            width = obj.estimated_width_inches or 0

            # Look at neighbors for context clues
            left_neighbor = results[i - 1] if i > 0 else None
            right_neighbor = results[i + 1] if i < len(results) - 1 else None

            # Narrow items (< 10") between cabinets are likely filler strips
            if width < 10:
                # Try to match as filler strip - search multiple filler categories
                filler_blocks = []
                for filler_cat in ("filler_strip", "filler_strip_base", "corner_filler_cabinet",
                                   "filler_strip_wood", "filler_panel_assembly"):
                    filler_blocks = self.library.search(category=filler_cat, library="front_view")
                    if filler_blocks:
                        break
                if filler_blocks:
                    best_filler = filler_blocks[0]
                    result.best_match = best_filler
                    result.confidence = 0.6
                    result.product_number = best_filler.product_number
                    result.is_flagged = False
                    result.flag_reason = ""
                    result.notes = f"Filler strip ({width:.0f}\" wide, matched by context)"
                else:
                    result.notes += f" [Likely filler strip, {width:.0f}\" wide, no filler blocks in library]"
                continue

            # If surrounded by base cabinets, likely also a base cabinet
            if left_neighbor and right_neighbor:
                if (left_neighbor.best_match and right_neighbor.best_match and
                    left_neighbor.best_match.category == "base_cabinet" and
                    right_neighbor.best_match.category == "base_cabinet"):
                    result.notes += " [Context: between base cabinets]"

    def load_rules(self, rules: List[Dict]):
        """Load custom matching rules."""
        self.custom_rules = rules
        logger.info(f"Loaded {len(rules)} custom matching rules")
