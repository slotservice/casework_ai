# Casework AI Pipeline - Progress & Audit Log

## Project Overview
- **Client**: Matt (via Freelancer)
- **Goal**: Build AI-assisted tool to convert architectural casework elevation PDFs into editable AutoCAD DWG/DXF files using Mott Manufacturing block libraries
- **Test Scope**: Elevation E4 from architectural sheet A407
- **Budget**: $120 paid test
- **Date**: 2026-04-16

---

## Phase 1: File Analysis & Inventory

### Files Received from Client
| File | Type | Details |
|------|------|---------|
| `before page a407 (1).pdf` | Input PDF | 1 page, 56,883 vector paths, NO extractable text. Full architectural elevation sheet with ~20+ casework elevation views |
| `after page 2-08 (2).pdf` | Reference PDF | 1 page, 7,648 vector paths, NO text. Mott shop drawing showing expected output format |
| `MottManufacturing_Version_9.1_FullCatalog_April2021-2.pdf` | Catalog | 372 pages. Full Mott product catalog with dimensions, item numbers, configurations |
| `Casework - Front Views/` | Block Library | **5,396 DWG files** - front elevation views of all Mott cabinet types |
| `Casework Section - Metal/` | Block Library | **604 DWG files** - cross-section views for metal cabinets |

### Key Findings from Analysis
1. **Both PDFs are purely graphical** - no extractable text. Detection must rely on image/vector analysis
2. **E4 elevation is embedded within the multi-elevation A407 sheet** - not a separate file
3. **The A407 sheet is oriented with content rotated 90 degrees** - elevations run vertically in the PDF
4. **Product numbering system decoded** from catalog:
   - 7-digit numbers: `1WWCCHR` where W=width code, C=config, H=hand, R=variant
   - Example: `1010011` = 12" wide, full door, right-hand, 1-door steel base cabinet
   - Width codes: 01=12", 11=18", 12=24", 13=30", 14=36", 15=48", 17=42"
5. **Block library is comprehensive** - 6,000 total DWG files covering all Mott product types
6. **Named blocks** use letter prefixes: GLS (gable legs), FLS (filler strips), TAB (tables), etc.

### Missing Items / Blockers Identified
- **E4 is not a separate file** - must be extracted from the multi-elevation A407 page
- **No labeled elevation numbers in the PDF text** - positions estimated by grid segmentation
- **DWG files cannot be directly read by ezdxf** (DWG is proprietary) - blocks are referenced by product number, actual DWG insertion would require ODA/LibreDWG or AutoCAD

---

## Phase 2: Architecture Design

### Pipeline Architecture
```
Input PDF → PDF Parser → Elevation Extractor → Object Detector → Block Matcher → CAD Writer → DXF Output
                                                                      ↑
                                                          Rule Trainer (user rules)
                                                                      ↓
                                                           Confidence Logger
```

### Module Structure
```
casework_ai/
├── __init__.py              # Package init
├── __main__.py              # Entry point for python -m
├── main.py                  # CLI entry point with argparse
├── pipeline.py              # Main orchestrator
├── config/
│   └── settings.yaml        # All configuration
├── modules/
│   ├── __init__.py
│   ├── config_loader.py     # YAML config management
│   ├── project_scanner.py   # File inventory scanner
│   ├── pdf_parser.py        # PDF reading + elevation extraction
│   ├── block_library.py     # DWG block library loader/indexer
│   ├── object_detector.py   # OpenCV-based casework detection
│   ├── block_matcher.py     # Product number matching engine
│   ├── cad_writer.py        # DXF output generation via ezdxf
│   ├── confidence_log.py    # Logging and validation reports
│   ├── rule_trainer.py      # Natural language rule engine
│   └── cli_interface.py     # Interactive CLI
├── rules/                   # Custom rule storage
├── output/                  # Generated DXF files
├── logs/                    # Pipeline logs and reports
├── tests/                   # Test directory
└── requirements.txt         # Python dependencies
```

---

## Phase 3: Implementation Log

### Module-by-Module Implementation

#### 1. config_loader.py
- Loads YAML configuration with dot-notation access
- Resolves relative paths to absolute
- Auto-creates output directories

#### 2. project_scanner.py
- Scans project root recursively
- Categorizes files: input PDF, reference PDF, catalog, blocks
- Provides file inventory with size and type info
- **Result**: Successfully scanned 6,000+ files

#### 3. pdf_parser.py
- Uses PyMuPDF (fitz) for PDF reading
- **Projection-based elevation segmentation**: finds whitespace gaps using horizontal and vertical pixel projections to split dense multi-elevation sheets into individual views
- **Auto-rotation**: detects portrait-oriented elevations and rotates to landscape
- Exports individual elevation images as PNG for review
- **Bug fixed**: Initial contour-based approach failed because the dense A407 sheet merged into one blob. Replaced with projection gap analysis.

#### 4. block_library.py
- Loads and indexes all 6,000 DWG blocks
- Decodes Mott product numbering system into structured data:
  - Category (base_cabinet, wall_cabinet, floor_cabinet, etc.)
  - Width in inches
  - Configuration type (open, full_door, door_drawer, drawer, etc.)
  - Hand/hinge orientation (right, left, both)
- Named block recognition (GLS, FLS, TAB, etc.)
- Search by category, width, config, hand, library type
- Exports full JSON index for inspection
- **Result**: 142 categories, 35 width values indexed

#### 5. object_detector.py
- OpenCV-based detection pipeline:
  - Binary thresholding + morphological closing
  - Contour detection with area/aspect ratio filtering
  - Horizontal line detection (Hough transform) for drawer patterns
  - Circle detection (Hough circles) for sinks - conservative parameters
  - Door pattern detection (vertical center line analysis)
- Feature extraction: edge density, fill density, line counts
- Scale estimation from image dimensions
- Debug visualization output with color-coded bounding boxes
- **Bug fixed**: Overflow in numpy uint16 for circle coordinates
- **Bug fixed**: False positive sink detection from aggressive circle params - tightened to only accept circles within existing cabinet regions

#### 6. block_matcher.py
- Multi-factor scoring engine:
  - Category match (base score)
  - Width match (exact +0.3, close +0.15, mismatch -0.2)
  - Configuration preference (drawer, door, etc.)
  - Feature-based scoring (horizontal lines → drawers, door pattern → doors)
  - Hand preference (right-hand standard +0.02)
- Custom rule engine integration
- Context refinement (neighbor-based improvement)
- Confidence thresholds: min 0.4, high 0.8
- **Bug fixed**: Missing type mappings for sink, countertop, unknown types caused "No search strategy" errors

#### 7. cad_writer.py
- ezdxf R2010 format for maximum compatibility
- 10 dedicated layers with color coding:
  - CASEWORK-CABINETS (white), CASEWORK-COUNTERTOPS (green), CASEWORK-SINKS (blue), etc.
- Cabinet drawing with:
  - Outline rectangles
  - Toe kick line (4" from bottom)
  - Door centerlines for double doors
  - Handle marks (circles)
  - Drawer division lines
- Countertop outline with 1" overhang
- Dimension annotations below cabinets (individual + overall)
- Product number labels centered in each cabinet
- Flag markers for uncertain items
- Title block with summary statistics

#### 8. confidence_log.py
- Detailed JSON log with per-object entry
- Summary statistics: total, matched, flagged, confidence distribution
- Human-readable validation report (TXT)
- Flagged items with reasons and top candidates
- **Bug fixed**: numpy integer types not JSON serializable - added custom encoder

#### 9. rule_trainer.py
- Natural language rule parser supports patterns like:
  - "if a base cabinet is 36 inch wide, use product 1410011"
  - "for sink cabinets wider than 30 inches, use 1310011"
- Structured rule API for programmatic rules
- Learn-from-correction: creates rules from user corrections
- Rule enable/disable/delete
- JSON storage in rules directory
- Export to human-readable text format

#### 10. cli_interface.py
- Interactive menu-driven interface
- Options: run pipeline, scan files, view library, review results, add rules, view logs
- Correction workflow: select item by ID, provide correct product number, auto-learn rule

---

## Phase 4: Testing & Iteration

### Test Run 1 (200 DPI, initial detection)
- **Issue**: Elevation detection failed - 0 regions found
- **Root cause**: Contour-based approach merged entire dense page into one blob
- **Fix**: Replaced with projection-based gap analysis

### Test Run 2 (200 DPI, projection-based)
- 6 regions detected, E4 extracted (still rotated sideways)
- 129 objects detected, only 2 matched (1.6%)
- **Issues**: Image not rotated, sink false positives, missing type mappings

### Test Run 3 (200 DPI, with rotation)
- Elevations properly rotated to landscape
- 165 objects, 125 matched (75.8%)
- **Issue**: Most "matches" were false positive sink circles (115 sinks)

### Test Run 4 (200 DPI, tightened sinks)
- 57 objects, 17 matched (29.8%)
- Sinks reduced but drawer_unit/base_cabinet failing
- **Issue**: At 200 DPI, individual cabinet regions only 20-30px wide, too small for reliable detection

### Test Run 5 (300 DPI, false 100%)
- 29 objects detected, 29 matched (100%) - BUT this was misleading
- 24 out of 29 "objects" were false positive circle detections labeled as sinks
- Only 5 real rectangular objects detected
- **Root cause**: Old detector used contour-based approach that couldn't find cabinet boundaries
- **Decision**: Complete rewrite of object detector needed

### Test Run 6 (300 DPI, rewritten detector)
- **Complete rewrite of object_detector.py** with band-based approach:
  1. Split elevation into sub-views via vertical whitespace gaps
  2. Calibrate scale from cabinet height (38" visible = content height in pixels)
  3. Find vertical boundary lines (70%+ height) between cabinets
  4. Classify each segment by interior features
- **Result: 25 objects detected, 22 matched (88%), 3 flagged**
- Average confidence: 81%
- 3 flagged items are small segments (6-7") likely fillers
- **Issues identified**: wrong elevation selected, feature scoring dead code, incomplete width map

### Bug Fix Session (Session 2)
Four critical bugs identified and fixed:

1. **block_matcher.py**: Feature field names `horizontal_lines` and `has_door_pattern` didn't match detector's `horizontal_line_groups` and `has_center_vertical` — drawer/door scoring was dead code
2. **block_library.py**: WIDTH_MAP only covered ~15 of 60+ width codes. Added fallback decoder using second-digit pattern, giving 2000+ blocks proper widths
3. **cad_writer.py**: Used `"drawer" in label.lower()` (unreliable) instead of casework_type enum. Hard-coded 4 drawers instead of using detected count
4. **Elevation mapping**: Elevations were labeled sequentially (E1-E7) by position, but architect numbered them non-sequentially. Parser E7 = actual E4. Added config-based elevation mapping

### Test Run 7 (300 DPI, all bugs fixed, CORRECT E4)
- **Processing the correct E4 elevation** (was previously processing wrong region)
- **Result: 26 objects detected, 26 matched (100%), 0 flagged**
- Average confidence: 91%
- Scale factor: 5.92 px/inch
- 5 sub-views identified in the actual E4 strip
- Diverse cabinet widths: 12", 15", 18", 21", 24", 30", 36"
- Proper product types: sink_cabinet, drawer_unit, base_cabinet, filler_strip
- Matched product numbers: 1131011, 1010211, 1110100, 1160211, 1310311, 1080211, 1910100, 1120211, FLS1024

---

## Phase 5: Deliverables Summary

### Generated Output Files
| File | Description |
|------|-------------|
| `output/E4_20260416_043223.dxf` | Clean editable DXF with 26 placed cabinets, dimensions, product numbers |
| `output/E4_20260416_043223_detection.png` | Debug image showing detected objects with bounding boxes |
| `output/block_index.json` | Full 5,995-entry block library index with extended width mappings |
| `output/elevations/page1_*.png` | Individual extracted elevation images (DETAIL, E2-E6, E4) |
| `logs/E4_20260416_043223_confidence.json` | Detailed matching log with per-object confidence (JSON) |
| `logs/E4_20260416_043223_report.txt` | Human-readable validation report: 26/26 matched, 0 flagged, 91% avg confidence |
| `logs/pipeline.log` | Full pipeline execution log |
| `rules/custom_rules.json` | Custom rule storage (empty, ready for user rules) |

### Source Code Files
| File | Lines | Description |
|------|-------|-------------|
| `config/settings.yaml` | 95 | All pipeline configuration |
| `modules/config_loader.py` | 75 | Config management |
| `modules/project_scanner.py` | 115 | File scanning/inventory |
| `modules/pdf_parser.py` | 250 | PDF parsing + elevation extraction |
| `modules/block_library.py` | 350 | Block library loader/indexer |
| `modules/object_detector.py` | 400 | Object detection engine |
| `modules/block_matcher.py` | 250 | Block matching engine |
| `modules/cad_writer.py` | 320 | DXF output generation |
| `modules/confidence_log.py` | 200 | Logging/reporting |
| `modules/rule_trainer.py` | 230 | Natural language rule engine |
| `modules/cli_interface.py` | 170 | Interactive CLI |
| `pipeline.py` | 200 | Main orchestrator |
| `main.py` | 110 | Entry point |
| `requirements.txt` | 15 | Dependencies |

---

## Known Limitations & Next Steps

### Current Limitations
1. **DWG block insertion**: ezdxf generates DXF files. Actual DWG block insertion from the .dwg library files requires ODA File Converter or AutoCAD COM automation. Currently, blocks are represented as parametric rectangles with product numbers.
2. **Scale estimation**: Auto-scale is heuristic-based (calibrated from cabinet height). Manual scale calibration or dimension detection would improve accuracy.
3. **Classification accuracy**: Without YOLO fine-tuning or Vision LLM, classification relies on geometric features (aspect ratio, line counts, circles). Accuracy improves with higher DPI and custom rules.
4. **Elevation labeling**: Uses config-based mapping (`pdf.elevation_map` in settings.yaml). For new sheets, the mapping must be verified and updated.
5. **Section views**: Not yet generated. Would require mapping to "Casework Section - Metal" blocks.
6. **Width code mapping**: Extended width codes use second-digit fallback pattern. Some codes may need manual verification against the Mott catalog.

### Recommended Next Steps for Full POC
1. **YOLO fine-tuning**: Label 50-100 sample cabinets from actual drawings, train YOLOv8 for precise detection
2. **Vision LLM integration**: Use GPT-4o/Claude to read dimension annotations and interpret context
3. **DWG block insertion**: Integrate ODA File Converter or pyautocad for native DWG block placement
4. **Dimension reading**: OCR or vector text extraction for reading annotated dimensions
5. **Section view generation**: Match detected cabinets to section metal blocks
6. **Multi-elevation processing**: Process all elevations from a sheet, not just one
7. **Drawing comparison learning**: Compare AI output vs user-corrected DWG to auto-learn rules

---

## How to Run

```bash
# Install dependencies
pip install -r casework_ai/requirements.txt

# Run full pipeline on elevation E4
python -m casework_ai.main --run --elevation E4

# Interactive mode
python -m casework_ai.main

# Scan project files only
python -m casework_ai.main --scan

# View block library summary
python -m casework_ai.main --library
```

---

*Last updated: 2026-04-16 04:35 UTC*
