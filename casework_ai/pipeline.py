"""
Casework AI Pipeline - Main Orchestrator
Coordinates all modules to convert architectural elevation PDFs
into editable DXF/DWG files using the Mott block library.
"""

import os
import sys
import logging
from pathlib import Path
from typing import Dict, List, Optional
from datetime import datetime

from .modules.config_loader import ConfigLoader
from .modules.project_scanner import ProjectScanner, ProjectInventory
from .modules.pdf_parser import PDFParser
from .modules.block_library import BlockLibrary
from .modules.object_detector import ObjectDetector, DetectionResult
from .modules.block_matcher import BlockMatcher, MatchResult
from .modules.cad_writer import CADWriter
from .modules.confidence_log import ConfidenceLog
from .modules.rule_trainer import RuleTrainer

logger = logging.getLogger(__name__)


class CaseworkPipeline:
    """Main pipeline orchestrator for casework conversion."""

    def __init__(self, project_root: str = None, config_path: str = None):
        # Determine project root
        if project_root is None:
            project_root = str(Path(__file__).parent.parent)
        self.project_root = Path(project_root)

        # Load config
        self.config = ConfigLoader(config_path)

        # Initialize modules
        self.scanner = ProjectScanner(str(self.project_root), self.config)
        self.pdf_parser = PDFParser(self.config)

        # Block library
        front_dir = self.config.paths.get("block_library_front",
                                          str(self.project_root / "Casework - Front Views"))
        section_dir = self.config.paths.get("block_library_section",
                                            str(self.project_root / "Casework Section - Metal"))
        self.block_library = BlockLibrary(front_dir, section_dir, self.config)

        # Load additional block library directories from config
        extra_libs = self.config.get("paths.extra_libraries", [])
        if extra_libs and isinstance(extra_libs, list):
            for lib_entry in extra_libs:
                if isinstance(lib_entry, dict):
                    lib_path = lib_entry.get("path", "")
                    lib_type = lib_entry.get("type", "extra")
                    if lib_path.startswith(".."):
                        lib_path = str((self.project_root / "casework_ai" / lib_path).resolve())
                    self.block_library.add_directory(lib_path, lib_type)

        self.detector = ObjectDetector(self.config)
        self.matcher = BlockMatcher(self.block_library, self.config)
        self.cad_writer = CADWriter(self.config)

        # Rule trainer
        rules_dir = self.config.paths.get("rules_dir",
                                          str(self.project_root / "casework_ai" / "rules"))
        self.rule_trainer = RuleTrainer(rules_dir)

        # Output/logs dirs
        self.output_dir = self.config.paths.get("output_dir",
                                                str(self.project_root / "output"))
        self.logs_dir = self.config.paths.get("logs_dir",
                                              str(self.project_root / "logs"))

        # State
        self.inventory: Optional[ProjectInventory] = None
        self.last_results: Optional[List[MatchResult]] = None
        self.last_detection: Optional[DetectionResult] = None
        self.last_log: Optional[ConfidenceLog] = None

    def run(self, pdf_path: str = None, elevation_label: str = "E4",
            output_name: str = None) -> Dict:
        """
        Run the full pipeline on a PDF elevation.

        Args:
            pdf_path: Path to the input PDF (auto-detected if None)
            elevation_label: Target elevation label (e.g., "E4")
            output_name: Output filename prefix (auto-generated if None)

        Returns:
            Dict with paths to generated files and summary info
        """
        run_timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        if output_name is None:
            output_name = f"{elevation_label}_{run_timestamp}"

        logger.info(f"=== PIPELINE START: {elevation_label} ===")
        results = {"elevation": elevation_label, "timestamp": run_timestamp}

        # Step 1: Scan project
        logger.info("Step 1: Scanning project files...")
        self.inventory = self.scanner.scan()
        results["inventory_summary"] = self.inventory.summary()

        # Step 2: Load block library
        logger.info("Step 2: Loading block library...")
        block_count = self.block_library.load()
        results["blocks_loaded"] = block_count

        # Export block index
        index_path = os.path.join(self.output_dir, "block_index.json")
        self.block_library.export_index(index_path)
        results["block_index_path"] = index_path

        # Step 3: Load custom rules
        logger.info("Step 3: Loading custom rules...")
        active_rules = self.rule_trainer.get_active_rules()
        self.matcher.load_rules(active_rules)
        results["active_rules"] = len(active_rules)

        # Step 4: Parse PDF and extract elevation
        logger.info(f"Step 4: Parsing PDF and extracting elevation {elevation_label}...")
        if pdf_path is None:
            pdf_info = self.scanner.find_elevation_pdf(elevation_label)
            if pdf_info:
                pdf_path = pdf_info.path
            else:
                raise FileNotFoundError(
                    f"No input PDF found. Please provide a PDF path."
                )

        # Save all elevation extractions for review
        elevations_dir = os.path.join(self.output_dir, "elevations")
        all_elevations = self.pdf_parser.save_all_elevations(pdf_path, elevations_dir)
        results["elevations_found"] = len(all_elevations)
        results["elevations_dir"] = elevations_dir

        # Get the target elevation
        target_elevation = None
        for elev in all_elevations:
            if elev.label.upper() == elevation_label.upper():
                target_elevation = elev
                break

        if target_elevation is None:
            # Fallback: use the closest match or the 4th region
            available = [e.label for e in all_elevations]
            logger.warning(
                f"Elevation {elevation_label} not found by label. "
                f"Available: {available}. Using best match..."
            )
            # Try to find E4 by index (4th region)
            if len(all_elevations) >= 4:
                target_elevation = all_elevations[3]  # 0-indexed, so index 3 = E4
                target_elevation.label = elevation_label
            elif all_elevations:
                target_elevation = all_elevations[0]
                target_elevation.label = elevation_label
            else:
                raise ValueError("No elevation regions detected in the PDF.")

        results["target_elevation"] = target_elevation.label

        # Step 5: Object detection
        logger.info("Step 5: Running object detection...")
        if target_elevation.image is not None:
            self.last_detection = self.detector.detect(target_elevation.image)
        else:
            raise ValueError("No image data available for the target elevation.")

        results["objects_detected"] = len(self.last_detection.objects)
        results["scale_factor"] = self.last_detection.scale_factor

        # Save debug image
        try:
            import cv2
            debug_path = os.path.join(self.output_dir, f"{output_name}_detection.png")
            if self.last_detection.debug_image is not None:
                cv2.imwrite(debug_path, self.last_detection.debug_image)
                results["debug_image_path"] = debug_path
        except ImportError:
            pass

        # Step 6: Block matching
        logger.info("Step 6: Matching detected objects to blocks...")
        self.last_results = self.matcher.match_all(self.last_detection.objects)
        results["matched_count"] = len([r for r in self.last_results if r.best_match])
        results["flagged_count"] = len([r for r in self.last_results if r.is_flagged])

        # Step 7: Generate DXF output
        logger.info("Step 7: Generating DXF output...")
        dxf_path = os.path.join(self.output_dir, f"{output_name}.dxf")
        self.cad_writer.generate_dxf(
            self.last_results,
            self.last_detection,
            dxf_path,
            title=f"Elevation {elevation_label} - Mott Casework",
            elevation_label=elevation_label,
        )
        results["dxf_path"] = dxf_path

        # Step 8: Generate confidence log and validation report
        logger.info("Step 8: Generating confidence log and validation report...")
        self.last_log = ConfidenceLog(self.logs_dir)
        self.last_log.log_results(self.last_results, self.last_detection, elevation_label)

        log_path = self.last_log.save_json(f"{output_name}_confidence.json")
        report_path = self.last_log.save_report(f"{output_name}_report.txt")
        results["log_path"] = log_path
        results["report_path"] = report_path
        results["summary"] = self.last_log.get_summary_text()

        logger.info(f"=== PIPELINE COMPLETE ===")
        logger.info(f"Summary: {results['summary']}")
        logger.info(f"DXF output: {dxf_path}")
        logger.info(f"Report: {report_path}")

        return results

    def scan_project(self) -> ProjectInventory:
        """Scan project files and return inventory."""
        self.inventory = self.scanner.scan()
        return self.inventory

    def get_library_summary(self) -> str:
        """Get block library summary."""
        if not self.block_library.blocks:
            self.block_library.load()
        return self.block_library.summary()

    def export_dxf(self, output_filename: str):
        """Re-export DXF with current results and rules."""
        if not self.last_results or not self.last_detection:
            raise RuntimeError("No results available. Run the pipeline first.")

        output_path = os.path.join(self.output_dir, output_filename)
        self.cad_writer.generate_dxf(
            self.last_results,
            self.last_detection,
            output_path,
        )
