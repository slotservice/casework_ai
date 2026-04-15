"""
CLI Interface Module
Provides a command-line interface for running the pipeline,
reviewing results, and training rules.
"""

import os
import sys
import logging
from typing import Optional

logger = logging.getLogger(__name__)


class CLIInterface:
    """Command-line interface for the casework AI pipeline."""

    def __init__(self, pipeline):
        self.pipeline = pipeline

    def run_interactive(self):
        """Run the interactive CLI menu."""
        print("\n" + "=" * 60)
        print("  CASEWORK AI PIPELINE - Interactive Mode")
        print("=" * 60)

        while True:
            print("\nOptions:")
            print("  1. Run full pipeline on PDF")
            print("  2. Scan project files")
            print("  3. View block library summary")
            print("  4. Review detection results")
            print("  5. Add a matching rule (natural language)")
            print("  6. List all rules")
            print("  7. View confidence log")
            print("  8. Re-export DXF output")
            print("  9. Exit")
            print()

            choice = input("Select option (1-9): ").strip()

            if choice == "1":
                self._run_pipeline()
            elif choice == "2":
                self._scan_project()
            elif choice == "3":
                self._view_library()
            elif choice == "4":
                self._review_results()
            elif choice == "5":
                self._add_rule()
            elif choice == "6":
                self._list_rules()
            elif choice == "7":
                self._view_log()
            elif choice == "8":
                self._export_dxf()
            elif choice == "9":
                print("Goodbye!")
                break
            else:
                print("Invalid option. Please try again.")

    def _run_pipeline(self):
        """Run the full pipeline."""
        pdf_path = input("PDF path (or press Enter for default): ").strip()
        if not pdf_path:
            pdf_path = None

        elevation = input("Elevation label (default: E4): ").strip() or "E4"

        print(f"\nRunning pipeline for elevation {elevation}...")
        try:
            result = self.pipeline.run(pdf_path=pdf_path, elevation_label=elevation)
            if result:
                print(f"\nPipeline complete!")
                print(f"Output: {result.get('dxf_path', 'N/A')}")
                print(f"Report: {result.get('report_path', 'N/A')}")
                print(f"Summary: {result.get('summary', 'N/A')}")
            else:
                print("Pipeline returned no results.")
        except Exception as e:
            print(f"Error: {e}")
            logger.exception("Pipeline error")

    def _scan_project(self):
        """Scan and display project files."""
        inventory = self.pipeline.scan_project()
        print(inventory.summary())

    def _view_library(self):
        """View block library summary."""
        summary = self.pipeline.get_library_summary()
        print(summary)

    def _review_results(self):
        """Review detection results."""
        if not self.pipeline.last_results:
            print("No results available. Run the pipeline first.")
            return

        results = self.pipeline.last_results
        print(f"\nTotal items: {len(results)}")

        for r in results:
            status = "OK" if not r.is_flagged else "FLAG"
            product = r.product_number or "NONE"
            print(
                f"  [{status}] ID:{r.detected_object.obj_id} "
                f"Type: {r.detected_object.casework_type.value:20s} "
                f"Product: {product:12s} "
                f"Confidence: {r.confidence:.0%}"
            )

        # Option to correct
        print("\nTo correct an item, enter its ID (or press Enter to skip):")
        correction_id = input("> ").strip()
        if correction_id and correction_id.isdigit():
            self._correct_item(int(correction_id))

    def _correct_item(self, obj_id: int):
        """Allow user to correct a matched item."""
        results = self.pipeline.last_results
        target = None
        for r in results:
            if r.detected_object.obj_id == obj_id:
                target = r
                break

        if not target:
            print(f"Item ID {obj_id} not found.")
            return

        print(f"\nCurrent: {target.detected_object.casework_type.value} "
              f"-> {target.product_number or 'NONE'}")

        correct_product = input("Correct product number: ").strip()
        if correct_product:
            notes = input("Notes (optional): ").strip()
            rule = self.pipeline.rule_trainer.learn_from_correction(
                detected_type=target.detected_object.casework_type.value,
                detected_width=target.detected_object.estimated_width_inches or 0,
                correct_product=correct_product,
                notes=notes,
            )
            print(f"Rule learned: #{rule['id']} - {rule['description']}")

    def _add_rule(self):
        """Add a natural language rule."""
        print("\nEnter a matching rule in plain English.")
        print("Examples:")
        print('  "if a base cabinet is 36 inch wide, use product 1410011"')
        print('  "for sink cabinets wider than 30 inches, use 1310011"')
        print()

        text = input("Rule: ").strip()
        if text:
            rule = self.pipeline.rule_trainer.add_rule_natural(text)
            if rule:
                print(f"Rule added: #{rule['id']} - {rule['description']}")
            else:
                print("Could not parse that rule. Please try a different phrasing.")

    def _list_rules(self):
        """List all matching rules."""
        rules = self.pipeline.rule_trainer.list_rules()
        if not rules:
            print("No custom rules defined.")
            return

        print(self.pipeline.rule_trainer.export_rules(format="text"))

    def _view_log(self):
        """View the confidence log."""
        if self.pipeline.last_log:
            print(self.pipeline.last_log.get_summary_text())
            flagged = self.pipeline.last_log.get_flagged_items()
            if flagged:
                print(f"\nFlagged items ({len(flagged)}):")
                for item in flagged:
                    print(f"  ID:{item['object_id']} - {item['flag_reason']}")
        else:
            print("No log available. Run the pipeline first.")

    def _export_dxf(self):
        """Re-export the DXF with current rules."""
        if not self.pipeline.last_results:
            print("No results to export. Run the pipeline first.")
            return

        output = input("Output filename (default: output.dxf): ").strip() or "output.dxf"
        try:
            self.pipeline.export_dxf(output)
            print(f"DXF exported to {output}")
        except Exception as e:
            print(f"Error: {e}")
