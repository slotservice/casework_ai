# Casework AI Pipeline - Project Status & Plan

**Last updated**: 2026-04-16 (Session 3)
**Project**: AI-Assisted Casework Elevation to DXF Conversion for Mott Manufacturing
**Client**: Matt (Freelancer)
**Budget**: $120 paid test
**Status**: PAID TEST COMPLETE - Client feedback incorporated, Mott format matched

---

## Current Status

### Paid Test (Elevation E4) - COMPLETE

| Deliverable | Status | Details |
|------------|--------|---------|
| PDF parsing & elevation extraction | Done | Handles rotated content, multi-elevation sheets, projection-based segmentation |
| Object detection | Done | 26 objects detected from E4, band-based approach with scale calibration |
| Cabinet classification | Done | base_cabinet, drawer_unit, filler - no false positives |
| Block matching | Done | 26/26 matched to Mott products, 85% avg confidence |
| Product number placement | Done | Mott product codes labeled in each cabinet |
| DXF output | Done | Mott shop-drawing format: 14 layers, brick wall hatch, horizontal leaders, section marks, elevation marker |
| Spatial layout | Done | Preserves original cabinet run groupings with gaps, "CLEAR" annotations between runs |
| Dimensions | Done | Feet-inches format (3'-6½") on TOP, heights on LEFT (cabinet, counter, toe kick), overall run totals |
| Rule trainer | Done | Natural language rules, learn-from-correction |
| Confidence log | Done | Per-item JSON + human-readable report |
| Interactive CLI | Done | Menu-driven interface |
| Presentation images | Done | 3-step comparison, dark DXF preview, detail view |

### Test Results

| Metric | Value |
|--------|-------|
| Objects detected | 26 |
| Match rate | 100% (26/26) |
| Average confidence | 85% |
| High confidence (>80%) | 18 of 26 |
| Flagged items | 0 |
| Cabinet types | 7 base_cabinet, 15 drawer_unit, 4 narrow/filler |
| DXF entities | 900+ across 14 layers |
| Cabinet runs | 2 (334" + 79") |
| DXF format | Mott shop-drawing style matching client reference |

### Output Files

| File | Purpose |
|------|---------|
| `output/E4_*.dxf` | Editable DXF file for AutoCAD |
| `output/E4_*_detection.png` | Detection visualization with labeled bounding boxes |
| `output/E4_comparison.png` | 3-step comparison (Original -> Detection -> DXF) |
| `output/E4_dxf_preview_dark.png` | Full DXF preview render (dark background) |
| `output/E4_dxf_detail.png` | Zoomed detail view of DXF |
| `logs/E4_*_report.txt` | Validation report |
| `logs/E4_*_confidence.json` | Detailed per-item matching log |

---

## Architecture

```
Input PDF
  |
  v
PDF Parser (PyMuPDF, 300 DPI)
  |-- projection-based segmentation
  |-- auto-rotation
  |-- elevation mapping (config)
  |
  v
Object Detector (OpenCV)
  |-- sub-view splitting
  |-- scale calibration (38" cabinet height)
  |-- vertical boundary detection (70%+ height lines)
  |-- classification: drawers (evenly-spaced lines), doors (center vertical), sinks (circles + width check), fillers (narrow)
  |
  v
Block Matcher
  |-- type -> category mapping
  |-- width matching (40% of score)
  |-- config matching (20% of score)
  |-- feature scoring (15% of score)
  |-- custom rule override
  |
  v
CAD Writer (ezdxf)
  |-- spatial layout from pixel positions (preserves cabinet run groupings)
  |-- Mott shop-drawing format: raised panels, drawer pulls, sink basins
  |-- brick/masonry wall hatch above countertop
  |-- feet-inches dimensions on TOP, heights on LEFT
  |-- horizontal leader annotations (Mott style, no crossing)
  |-- "CLEAR" gap annotations between runs
  |-- section cut markers, elevation marker, title block
  |-- 14 layers with proper colors
  |
  v
Output: DXF + Detection PNG + Confidence Log + Report
```

### Module Files

| Module | File | Purpose |
|--------|------|---------|
| Config | `casework_ai/config/settings.yaml` | All configuration |
| PDF Parser | `casework_ai/modules/pdf_parser.py` | PDF -> elevation images |
| Block Library | `casework_ai/modules/block_library.py` | 6,000 DWG block indexer |
| Object Detector | `casework_ai/modules/object_detector.py` | Cabinet detection & classification |
| Block Matcher | `casework_ai/modules/block_matcher.py` | Product number matching |
| CAD Writer | `casework_ai/modules/cad_writer.py` | DXF generation |
| Confidence Log | `casework_ai/modules/confidence_log.py` | Logging & reports |
| Rule Trainer | `casework_ai/modules/rule_trainer.py` | Natural language rules |
| CLI | `casework_ai/modules/cli_interface.py` | Interactive menu |
| Pipeline | `casework_ai/pipeline.py` | Orchestrator |
| Entry | `casework_ai/main.py` | CLI entry point |

---

## Development History

### Session 1: Initial build
- Built all 10 modules from scratch
- 7 test runs with progressive fixes:
  - Run 1-4: Fixed elevation segmentation (contour -> projection), rotation, sink false positives
  - Run 5: Revealed old detector couldn't find cabinet boundaries, triggered full rewrite
  - Run 6: New band-based detector, 88% match rate
  - Run 7: Fixed 4 critical bugs (feature field names, width map, drawing logic, elevation mapping), 100% match

### Session 2: Quality overhaul for delivery
- Fixed classification: eliminated 14 false sink detections (circle detection param2: 50->120, width validation >=24")
- Fixed drawer detection: evenly-spaced line signature check, exclude structural lines
- Redesigned block matcher scoring: base 0.5->0.2, width 40%, config 20%, features 15%
- Rewrote CAD writer: shop-drawing-style with raised panels, drawer pulls, toe kick recess, sink basins
- Added spatial layout preservation: cabinet runs maintain original groupings with gaps
- Per-run countertops and dimensions
- Improved debug image: scaled up, colored labels, legend
- Created presentation materials: dark DXF preview, detail view, 3-step comparison image

### Session 3: Client feedback - match Mott shop drawing format
- Client provided reference image (Mott "SCIENCE PREP - SOUTH" E4 shop drawing)
- Compared our output against client's reference, identified 7 format gaps
- **Dimension overhaul**: feet-inches format (3'-6½") with ½" fraction support, widths moved to TOP of drawing above wall, heights moved to LEFT side with 3 stacked markers (cabinet height, counter height, toe kick), overall run dimensions on second tier
- **Wall hatching**: replaced diagonal crosshatch with brick/masonry pattern (modular 8" x 2-2/3" bricks with staggered joints, matching architectural standard)
- **Leader lines**: completely redesigned — horizontal leaders on RIGHT side of each run, dots at run edge, text on right margin. Leaders no longer cross over cabinets
- **"CLEAR" annotations**: gap dimensions between cabinet runs with feet-inches labels
- **Leader descriptions**: updated to Mott format ("LOWER CASEWORK W/ DOORS\nATTACHED TOE KICKS - LG-1")
- **Countertop**: simplified to clean single rectangle (removed double line)
- **14 layers** (was 11): added wall, leaders, section_marks, titleblock layers

---

## Known Limitations

1. **Parametric drawings, not block insertion**: DXF contains drawn cabinet elevations with product numbers. Actual .dwg block insertion requires ODA File Converter or AutoCAD COM.
2. **Classification accuracy**: Geometry-based (no trained ML). Some narrow items (6-7") classified as base_cabinet rather than filler.
3. **Scale estimation**: Heuristic from cabinet height. Non-standard heights need manual config.
4. **No text/OCR**: Both PDFs are purely graphical. Dimension annotations can't be read.
5. **Single elevation**: Processes one elevation per run. Multi-elevation batch not yet implemented.

---

## Next Steps (Full POC)

| Priority | Feature | Effort | Impact |
|----------|---------|--------|--------|
| 1 | YOLO fine-tuning on Matt's drawings | 2-3 days | Major detection accuracy improvement |
| 2 | DWG block insertion via ODA Converter | 1-2 days | Actual Mott blocks in output |
| 3 | Vision LLM for dimension reading | 1 day | Read annotated dimensions from drawings |
| 4 | Multi-elevation batch processing | 1 day | Process all elevations from one sheet |
| 5 | Section view generation | 2 days | Match to Casework Section - Metal blocks |
| 6 | GUI rule trainer (Tkinter/web) | 2-3 days | Non-technical user interface |
| 7 | Drawing comparison learning | 3-4 days | Auto-learn from user-corrected DWG |

---

## How to Run

```bash
pip install -r casework_ai/requirements.txt
python -m casework_ai.main --run --elevation E4    # Full pipeline
python -m casework_ai.main                         # Interactive mode
python -m casework_ai.main --scan                  # File inventory
python -m casework_ai.main --library               # Block library summary
```
