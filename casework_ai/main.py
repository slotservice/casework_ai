"""
Casework AI Pipeline - Main Entry Point
Run this script to execute the pipeline or launch the interactive CLI.

Usage:
    python -m casework_ai.main                    # Interactive mode
    python -m casework_ai.main --run              # Run pipeline with defaults
    python -m casework_ai.main --run --elevation E4 --pdf input.pdf
    python -m casework_ai.main --scan             # Scan project files only
    python -m casework_ai.main --library          # Show block library summary
"""

import os
import sys
import argparse
import logging
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from casework_ai.pipeline import CaseworkPipeline
from casework_ai.modules.cli_interface import CLIInterface


def setup_logging(log_dir: str = None, level: str = "INFO"):
    """Configure logging for the pipeline."""
    log_format = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"

    handlers = [logging.StreamHandler(sys.stdout)]

    if log_dir:
        os.makedirs(log_dir, exist_ok=True)
        log_file = os.path.join(log_dir, "pipeline.log")
        handlers.append(logging.FileHandler(log_file, encoding="utf-8"))

    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format=log_format,
        handlers=handlers,
    )


def main():
    parser = argparse.ArgumentParser(
        description="Casework AI Pipeline - Convert architectural elevations to DXF"
    )
    parser.add_argument("--run", action="store_true",
                        help="Run the pipeline (non-interactive)")
    parser.add_argument("--scan", action="store_true",
                        help="Scan project files and show inventory")
    parser.add_argument("--library", action="store_true",
                        help="Show block library summary")
    parser.add_argument("--elevation", "-e", default="E4",
                        help="Target elevation label (default: E4)")
    parser.add_argument("--pdf", "-p", default=None,
                        help="Input PDF path (auto-detected if not specified)")
    parser.add_argument("--output", "-o", default=None,
                        help="Output filename prefix")
    parser.add_argument("--project-root", default=None,
                        help="Project root directory")
    parser.add_argument("--config", default=None,
                        help="Path to config YAML file")
    parser.add_argument("--log-level", default="INFO",
                        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
                        help="Logging level")

    args = parser.parse_args()

    # Determine project root
    project_root = args.project_root
    if project_root is None:
        project_root = str(Path(__file__).parent.parent)

    # Setup logging
    log_dir = os.path.join(project_root, "logs")
    setup_logging(log_dir, args.log_level)

    logger = logging.getLogger(__name__)
    logger.info("Casework AI Pipeline starting...")

    # Create pipeline
    pipeline = CaseworkPipeline(
        project_root=project_root,
        config_path=args.config,
    )

    if args.scan:
        inventory = pipeline.scan_project()
        print(inventory.summary())
        return

    if args.library:
        print(pipeline.get_library_summary())
        return

    if args.run:
        # Non-interactive run
        try:
            results = pipeline.run(
                pdf_path=args.pdf,
                elevation_label=args.elevation,
                output_name=args.output,
            )

            print("\n" + "=" * 60)
            print("  PIPELINE RESULTS")
            print("=" * 60)
            for key, value in results.items():
                if key not in ("inventory_summary",):
                    print(f"  {key}: {value}")
            print("=" * 60)

        except Exception as e:
            logger.exception("Pipeline failed")
            print(f"\nError: {e}")
            sys.exit(1)
        return

    # Interactive mode
    cli = CLIInterface(pipeline)
    cli.run_interactive()


if __name__ == "__main__":
    main()
