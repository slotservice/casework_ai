# Casework AI Pipeline

AI-assisted tool to convert architectural casework elevation PDFs into editable AutoCAD DXF files using Mott Manufacturing block libraries.

## Quick Start

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Run the pipeline on elevation E4
python -m casework_ai.main --run --elevation E4

# 3. Or use interactive mode
python -m casework_ai.main
```

## Requirements

- Python 3.10+
- PyMuPDF (PDF reading)
- OpenCV (object detection)
- ezdxf (DXF generation)
- PyYAML (configuration)
- numpy (image processing)

Install all: `pip install -r requirements.txt`

## Project Structure

```
casework_ai/
├── main.py                  # Entry point (CLI)
├── pipeline.py              # Main orchestrator
├── config/settings.yaml     # All configuration
├── modules/
│   ├── config_loader.py     # Config management
│   ├── project_scanner.py   # File inventory
│   ├── pdf_parser.py        # PDF → elevation extraction
│   ├── block_library.py     # DWG block indexer (6,000 blocks)
│   ├── object_detector.py   # Cabinet detection (OpenCV)
│   ├── block_matcher.py     # Product number matching
│   ├── cad_writer.py        # DXF output (ezdxf)
│   ├── confidence_log.py    # Validation reports
│   ├── rule_trainer.py      # Natural language rule engine
│   └── cli_interface.py     # Interactive CLI
├── requirements.txt
└── PROGRESS_LOG.md          # Full audit trail
```

## CLI Commands

```bash
# Full pipeline run
python -m casework_ai.main --run --elevation E4

# With custom PDF input
python -m casework_ai.main --run --pdf "path/to/elevation.pdf" --elevation E4

# Scan project files only
python -m casework_ai.main --scan

# Show block library summary
python -m casework_ai.main --library

# Debug logging
python -m casework_ai.main --run --log-level DEBUG
```

## Output Files

After running the pipeline:

| File | Location | Description |
|------|----------|-------------|
| `*.dxf` | `output/` | Editable DXF with placed cabinets, dimensions, product numbers |
| `*_detection.png` | `output/` | Debug image showing detected objects |
| `block_index.json` | `output/` | Full block library index (5,995 entries) |
| `elevations/*.png` | `output/` | Extracted elevation images |
| `*_confidence.json` | `logs/` | Detailed matching log |
| `*_report.txt` | `logs/` | Human-readable validation report |
| `pipeline.log` | `logs/` | Execution log |

## How Detection Works

1. **PDF Parsing**: PyMuPDF renders the PDF at 300 DPI, then projection-based gap analysis segments the multi-elevation sheet into individual views
2. **Auto-rotation**: Portrait-oriented elevations are rotated to landscape
3. **Sub-view splitting**: Each elevation is further split into content bands
4. **Scale calibration**: Cabinet height (38") is used to calculate pixel-to-inch ratio
5. **Vertical boundary detection**: Strong vertical lines (70%+ cabinet height) identify cabinet boundaries
6. **Classification**: Interior features (horizontal lines, center verticals, circles) determine cabinet type
7. **Width snapping**: Detected widths are snapped to Mott standard sizes (12", 15", 18", 21", 24", 30", 36", 42", 48")

## Rule Trainer

Add matching rules in plain English:

```
"if a base cabinet is 36 inch wide, use product 1410011"
"for sink cabinets wider than 30 inches, use 1310011"
"map 48 inch base cabinet to 1510011"
```

Rules are stored in `rules/custom_rules.json` and applied automatically on future runs.

## Configuration

Edit `config/settings.yaml` to adjust:
- Detection thresholds
- Standard cabinet widths
- Layer names and colors
- Confidence thresholds
- File paths

## Current Capabilities

- Extracts individual elevations from dense multi-view architectural sheets
- Detects cabinet boundaries using geometric analysis
- Classifies cabinets as base, drawer, sink, open shelf, or filler
- Matches to Mott product numbers from 6,000-block library
- Generates clean editable DXF with proper layers, dimensions, product labels
- Flags uncertain items for manual review
- Supports natural language rule training for continuous improvement

## Known Limitations

- Detection relies on geometry analysis (no trained ML model yet)
- Drawing scale is estimated from cabinet height (manual override available in config)
- DWG blocks are referenced by product number; actual block insertion requires ODA File Converter
- Annotations and text in the source PDF cannot be read (image-only PDFs)
