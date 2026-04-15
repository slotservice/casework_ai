"""
Confidence Log Generator Module
Creates detailed logs and reports of the pipeline's detection and matching results.
Includes confidence scores, flagged items, and validation notes.
"""

import os
import json
import logging
from datetime import datetime
from typing import Dict, List, Optional

import numpy as np

from .block_matcher import MatchResult
from .object_detector import DetectionResult

logger = logging.getLogger(__name__)


class ConfidenceLog:
    """Generates detailed confidence and validation logs."""

    def __init__(self, output_dir: str):
        self.output_dir = output_dir
        os.makedirs(output_dir, exist_ok=True)
        self.entries: List[Dict] = []
        self.summary_stats: Dict = {}

    def log_results(self, match_results: List[MatchResult],
                    detection_result: DetectionResult,
                    elevation_label: str = ""):
        """Log all matching results."""
        timestamp = datetime.now().isoformat()

        for result in match_results:
            entry = {
                "timestamp": timestamp,
                "elevation": elevation_label,
                "object_id": result.detected_object.obj_id,
                "casework_type": result.detected_object.casework_type.value,
                "bbox": list(result.detected_object.bbox),
                "estimated_width": result.detected_object.estimated_width_inches,
                "estimated_height": result.detected_object.estimated_height_inches,
                "detection_confidence": result.detected_object.confidence,
                "matched_product": result.product_number,
                "match_confidence": result.confidence,
                "is_flagged": result.is_flagged,
                "flag_reason": result.flag_reason,
                "notes": result.notes,
                "candidates": [],
            }

            for candidate in result.candidates[:3]:
                entry["candidates"].append({
                    "product_number": candidate.block.product_number,
                    "score": candidate.score,
                    "reasons": candidate.match_reasons,
                    "penalties": candidate.penalty_reasons,
                })

            self.entries.append(entry)

        # Compute summary
        self._compute_summary(match_results, detection_result)

    def _compute_summary(self, match_results: List[MatchResult],
                         detection_result: DetectionResult):
        """Compute summary statistics."""
        total = len(match_results)
        matched = len([r for r in match_results if r.best_match])
        flagged = len([r for r in match_results if r.is_flagged])
        high_conf = len([r for r in match_results if r.confidence >= 0.8])
        low_conf = len([r for r in match_results if 0 < r.confidence < 0.5])

        avg_confidence = 0
        if match_results:
            confidences = [r.confidence for r in match_results if r.confidence > 0]
            avg_confidence = sum(confidences) / len(confidences) if confidences else 0

        self.summary_stats = {
            "total_objects_detected": total,
            "total_matched": matched,
            "total_flagged": flagged,
            "total_unmatched": total - matched,
            "high_confidence_count": high_conf,
            "low_confidence_count": low_conf,
            "average_confidence": round(avg_confidence, 3),
            "match_rate": round(matched / total * 100, 1) if total > 0 else 0,
            "detection_scale_factor": detection_result.scale_factor,
            "total_width_inches": detection_result.total_width_inches,
        }

    def save_json(self, filename: str = "confidence_log.json") -> str:
        """Save the full log as JSON."""
        output_path = os.path.join(self.output_dir, filename)
        data = {
            "summary": self.summary_stats,
            "entries": self.entries,
        }

        class NumpyEncoder(json.JSONEncoder):
            def default(self, obj):
                if isinstance(obj, (np.integer,)):
                    return int(obj)
                if isinstance(obj, (np.floating,)):
                    return float(obj)
                if isinstance(obj, np.ndarray):
                    return obj.tolist()
                return super().default(obj)

        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, cls=NumpyEncoder)
        logger.info(f"Confidence log saved to {output_path}")
        return output_path

    def save_report(self, filename: str = "validation_report.txt") -> str:
        """Save a human-readable validation report."""
        output_path = os.path.join(self.output_dir, filename)

        lines = []
        lines.append("=" * 70)
        lines.append("CASEWORK AI PIPELINE - VALIDATION REPORT")
        lines.append(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        lines.append("=" * 70)
        lines.append("")

        # Summary
        s = self.summary_stats
        lines.append("SUMMARY")
        lines.append("-" * 40)
        lines.append(f"Total objects detected:  {s.get('total_objects_detected', 0)}")
        lines.append(f"Successfully matched:    {s.get('total_matched', 0)}")
        lines.append(f"Flagged/uncertain:       {s.get('total_flagged', 0)}")
        lines.append(f"Unmatched:               {s.get('total_unmatched', 0)}")
        lines.append(f"High confidence (>=80%): {s.get('high_confidence_count', 0)}")
        lines.append(f"Low confidence (<50%):   {s.get('low_confidence_count', 0)}")
        lines.append(f"Average confidence:      {s.get('average_confidence', 0):.1%}")
        lines.append(f"Overall match rate:      {s.get('match_rate', 0):.1f}%")
        lines.append(f"Scale factor:            {s.get('detection_scale_factor', 0):.2f} px/inch")
        lines.append(f"Total width estimated:   {s.get('total_width_inches', 0):.1f}\"")
        lines.append("")

        # Matched items
        lines.append("MATCHED ITEMS")
        lines.append("-" * 40)
        for entry in self.entries:
            if not entry["is_flagged"] and entry["matched_product"]:
                lines.append(
                    f"  [{entry['object_id']:3d}] {entry['casework_type']:20s} "
                    f"-> {entry['matched_product']:12s} "
                    f"(conf: {entry['match_confidence']:.0%}, "
                    f"width: {entry['estimated_width'] or '?'}\")"
                )
        lines.append("")

        # Flagged items
        lines.append("FLAGGED / UNCERTAIN ITEMS")
        lines.append("-" * 40)
        flagged = [e for e in self.entries if e["is_flagged"]]
        if flagged:
            for entry in flagged:
                lines.append(f"  [{entry['object_id']:3d}] {entry['casework_type']:20s}")
                lines.append(f"        Reason: {entry['flag_reason']}")
                lines.append(f"        Notes:  {entry['notes']}")
                if entry["candidates"]:
                    lines.append(f"        Top candidates:")
                    for c in entry["candidates"]:
                        lines.append(
                            f"          - {c['product_number']} (score: {c['score']:.2f})"
                        )
                lines.append("")
        else:
            lines.append("  No flagged items.")
        lines.append("")

        # Detailed breakdown
        lines.append("DETAILED BREAKDOWN")
        lines.append("-" * 40)
        for entry in self.entries:
            status = "OK" if not entry["is_flagged"] else "FLAG"
            lines.append(
                f"  [{status:4s}] ID:{entry['object_id']:3d} | "
                f"Type: {entry['casework_type']:20s} | "
                f"Product: {entry['matched_product'] or 'NONE':12s} | "
                f"DetConf: {entry['detection_confidence']:.0%} | "
                f"MatchConf: {entry['match_confidence']:.0%} | "
                f"Width: {entry['estimated_width'] or '?'}\""
            )

        lines.append("")
        lines.append("=" * 70)
        lines.append("END OF REPORT")
        lines.append("=" * 70)

        report_text = "\n".join(lines)
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(report_text)

        logger.info(f"Validation report saved to {output_path}")
        return output_path

    def get_flagged_items(self) -> List[Dict]:
        """Get list of all flagged items for review."""
        return [e for e in self.entries if e["is_flagged"]]

    def get_summary_text(self) -> str:
        """Get a brief text summary."""
        s = self.summary_stats
        return (
            f"Detection: {s.get('total_objects_detected', 0)} objects | "
            f"Matched: {s.get('total_matched', 0)} | "
            f"Flagged: {s.get('total_flagged', 0)} | "
            f"Avg confidence: {s.get('average_confidence', 0):.0%}"
        )
