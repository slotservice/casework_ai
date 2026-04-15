"""
PDF Parser Module
Extracts elevation drawings from architectural PDF sheets.
Handles both vector-based and image-based PDFs.
Uses PyMuPDF (fitz) for PDF reading and image extraction.
"""

import os
import logging
import json
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field

import fitz  # PyMuPDF
import numpy as np

logger = logging.getLogger(__name__)

try:
    import cv2
    HAS_CV2 = True
except ImportError:
    HAS_CV2 = False
    logger.warning("OpenCV not available. Image-based analysis will be limited.")


@dataclass
class ElevationRegion:
    """A detected elevation region within a PDF page."""
    label: str  # e.g., "E4", "E1", etc.
    bbox: Tuple[float, float, float, float]  # (x0, y0, x1, y1) in page coords
    pixel_bbox: Tuple[int, int, int, int]  # (x0, y0, x1, y1) in pixel coords
    width_px: int = 0
    height_px: int = 0
    image: Optional[np.ndarray] = None  # cropped image of the elevation
    vector_paths: List = field(default_factory=list)


@dataclass
class ParsedPage:
    """Result of parsing a single PDF page."""
    page_number: int
    width: float
    height: float
    total_vector_paths: int
    total_images: int
    elevations: List[ElevationRegion] = field(default_factory=list)
    full_image: Optional[np.ndarray] = None


class PDFParser:
    """Parses architectural PDF files and extracts elevation regions."""

    def __init__(self, config=None):
        self.config = config
        self.dpi = 200
        if config:
            self.dpi = config.get("pdf.elevation_detection_dpi", 200)

    def parse_pdf(self, pdf_path: str) -> List[ParsedPage]:
        """Parse all pages of a PDF file."""
        pdf_path = Path(pdf_path)
        if not pdf_path.exists():
            raise FileNotFoundError(f"PDF not found: {pdf_path}")

        logger.info(f"Parsing PDF: {pdf_path}")
        doc = fitz.open(str(pdf_path))
        pages = []

        for page_idx in range(len(doc)):
            page = doc[page_idx]
            parsed = self._parse_page(page, page_idx)
            pages.append(parsed)

        doc.close()
        logger.info(f"Parsed {len(pages)} pages, found {sum(len(p.elevations) for p in pages)} elevation regions")
        return pages

    def _parse_page(self, page: fitz.Page, page_idx: int) -> ParsedPage:
        """Parse a single page and extract elevation regions."""
        rect = page.rect
        drawings = page.get_drawings()
        images = page.get_images()

        parsed = ParsedPage(
            page_number=page_idx + 1,
            width=rect.width,
            height=rect.height,
            total_vector_paths=len(drawings),
            total_images=len(images),
        )

        # Render page to image for analysis
        pix = page.get_pixmap(dpi=self.dpi)
        img_data = np.frombuffer(pix.samples, dtype=np.uint8)
        if pix.n == 4:  # RGBA
            img = img_data.reshape(pix.h, pix.w, 4)
            if HAS_CV2:
                img = cv2.cvtColor(img, cv2.COLOR_RGBA2BGR)
        elif pix.n == 3:  # RGB
            img = img_data.reshape(pix.h, pix.w, 3)
            if HAS_CV2:
                img = cv2.cvtColor(img, cv2.COLOR_RGB2BGR)
        else:
            img = img_data.reshape(pix.h, pix.w)

        parsed.full_image = img

        # Detect elevation regions using grid analysis
        if HAS_CV2:
            elevations = self._detect_elevation_regions(img, page, pix)
            parsed.elevations = elevations
        else:
            # Fallback: treat entire page as single elevation
            parsed.elevations = [ElevationRegion(
                label="FULL_PAGE",
                bbox=(0, 0, rect.width, rect.height),
                pixel_bbox=(0, 0, pix.w, pix.h),
                width_px=pix.w,
                height_px=pix.h,
                image=img,
            )]

        return parsed

    def _detect_elevation_regions(self, img: np.ndarray, page: fitz.Page, pix) -> List[ElevationRegion]:
        """Detect individual elevation views within a multi-elevation sheet.
        Uses projection-based segmentation: finds whitespace gaps to split the page
        into a grid, then filters for meaningful drawing regions."""
        h, w = img.shape[:2]
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if len(img.shape) == 3 else img

        _, binary = cv2.threshold(gray, 230, 255, cv2.THRESH_BINARY_INV)

        # Horizontal projection: find row gaps (whitespace bands)
        h_proj = np.sum(binary > 0, axis=1)
        row_gaps = self._find_gaps(h_proj, threshold=w * 0.03, min_gap=5)

        # Split into row bands
        row_bands = self._gaps_to_bands(row_gaps, h, min_size=50)

        # For each row band, find column gaps
        elevation_rects = []
        for y_start, y_end in row_bands:
            row_strip = binary[y_start:y_end, :]
            v_proj = np.sum(row_strip > 0, axis=0)
            col_gaps = self._find_gaps(v_proj, threshold=(y_end - y_start) * 0.03, min_gap=5)
            col_bands = self._gaps_to_bands(col_gaps, w, min_size=80)

            for x_start, x_end in col_bands:
                cw = x_end - x_start
                ch = y_end - y_start
                # Filter out regions that are too narrow or too small
                if cw < 80 or ch < 80:
                    continue
                if cw * ch < (h * w) * 0.005:
                    continue
                elevation_rects.append((x_start, y_start, x_end, y_end))

        # Build ElevationRegion objects
        regions = []
        for x0, y0, x1, y1 in elevation_rects:
            padding = 5
            px0 = max(0, x0 - padding)
            py0 = max(0, y0 - padding)
            px1 = min(w, x1 + padding)
            py1 = min(h, y1 + padding)

            cropped = img[py0:py1, px0:px1].copy()

            # Auto-rotate: if the region is taller than wide (portrait),
            # rotate 90° clockwise so elevations are landscape-oriented
            crop_h, crop_w = cropped.shape[:2]
            if crop_h > crop_w * 1.5:
                cropped = cv2.rotate(cropped, cv2.ROTATE_90_CLOCKWISE)

            regions.append(ElevationRegion(
                label=f"REGION_{len(regions)+1}",
                bbox=(
                    px0 * page.rect.width / w,
                    py0 * page.rect.height / h,
                    px1 * page.rect.width / w,
                    py1 * page.rect.height / h,
                ),
                pixel_bbox=(px0, py0, px1, py1),
                width_px=px1 - px0,
                height_px=py1 - py0,
                image=cropped,
            ))

        # Sort regions top-to-bottom, left-to-right (reading order)
        regions.sort(key=lambda r: (r.pixel_bbox[1] // 100, r.pixel_bbox[0]))

        # Label regions as E1, E2, ...
        self._label_regions(regions, gray)

        # If no regions found, fall back to full page
        if not regions:
            logger.warning("No elevation regions detected, using full page as single region")
            regions = [ElevationRegion(
                label="E1",
                bbox=(0, 0, page.rect.width, page.rect.height),
                pixel_bbox=(0, 0, w, h),
                width_px=w,
                height_px=h,
                image=img,
            )]

        logger.info(f"Detected {len(regions)} elevation regions")
        return regions

    def _find_gaps(self, projection: np.ndarray, threshold: float, min_gap: int) -> list:
        """Find whitespace gaps in a projection profile."""
        is_white = projection < threshold
        gaps = []
        in_gap = False
        gap_start = 0
        for i in range(len(is_white)):
            if is_white[i] and not in_gap:
                gap_start = i
                in_gap = True
            elif not is_white[i] and in_gap:
                if i - gap_start >= min_gap:
                    gaps.append((gap_start, i))
                in_gap = False
        if in_gap and len(is_white) - gap_start >= min_gap:
            gaps.append((gap_start, len(is_white)))
        return gaps

    def _gaps_to_bands(self, gaps: list, total_size: int, min_size: int) -> list:
        """Convert a list of gaps into content bands between them."""
        bands = []
        prev_end = 0
        for gap_start, gap_end in gaps:
            if gap_start > prev_end + min_size:
                bands.append((prev_end, gap_start))
            prev_end = gap_end
        if prev_end < total_size - min_size:
            bands.append((prev_end, total_size))
        return bands

    def _label_regions(self, regions: List[ElevationRegion], gray_img: np.ndarray):
        """Label elevation regions using config-based mapping or sequential fallback.

        The config can specify an elevation_map that maps region indices to
        elevation labels, which is essential since architectural sheets often
        number elevations non-sequentially across the page.
        """
        # Check config for a manual elevation mapping
        elev_map = None
        if self.config:
            elev_map = self.config.get("pdf.elevation_map", None)

        if elev_map and isinstance(elev_map, dict):
            # Use configured mapping: keys are 1-based region indices, values are labels
            for i, region in enumerate(regions):
                idx_key = str(i + 1)
                if idx_key in elev_map:
                    region.label = str(elev_map[idx_key])
                else:
                    region.label = f"E{i+1}"
            logger.info(f"Applied configured elevation mapping for {len(elev_map)} regions")
        else:
            # Fallback: label sequentially
            for i, region in enumerate(regions):
                region.label = f"E{i+1}"

    def extract_elevation(self, pdf_path: str, elevation_label: str = "E4",
                          output_dir: Optional[str] = None) -> Optional[ElevationRegion]:
        """Extract a specific elevation from a PDF."""
        pages = self.parse_pdf(pdf_path)

        for page in pages:
            for elev in page.elevations:
                if elev.label.upper() == elevation_label.upper():
                    if output_dir and HAS_CV2 and elev.image is not None:
                        os.makedirs(output_dir, exist_ok=True)
                        out_path = os.path.join(output_dir, f"{elevation_label}_extracted.png")
                        cv2.imwrite(out_path, elev.image)
                        logger.info(f"Saved extracted elevation to {out_path}")
                    return elev

        logger.warning(f"Elevation {elevation_label} not found. Available: {[e.label for p in pages for e in p.elevations]}")
        return None

    def save_all_elevations(self, pdf_path: str, output_dir: str) -> List[ElevationRegion]:
        """Extract and save all detected elevations as individual images."""
        os.makedirs(output_dir, exist_ok=True)
        pages = self.parse_pdf(pdf_path)
        all_elevations = []

        for page in pages:
            for elev in page.elevations:
                if HAS_CV2 and elev.image is not None:
                    out_path = os.path.join(output_dir, f"page{page.page_number}_{elev.label}.png")
                    cv2.imwrite(out_path, elev.image)
                all_elevations.append(elev)

        logger.info(f"Saved {len(all_elevations)} elevation images to {output_dir}")
        return all_elevations

    def get_page_as_image(self, pdf_path: str, page_num: int = 0, dpi: int = 300) -> Optional[np.ndarray]:
        """Get a single page rendered as a numpy image array."""
        doc = fitz.open(str(pdf_path))
        if page_num >= len(doc):
            return None

        page = doc[page_num]
        pix = page.get_pixmap(dpi=dpi)
        img_data = np.frombuffer(pix.samples, dtype=np.uint8)

        if pix.n == 4:
            img = img_data.reshape(pix.h, pix.w, 4)
            if HAS_CV2:
                img = cv2.cvtColor(img, cv2.COLOR_RGBA2BGR)
        elif pix.n == 3:
            img = img_data.reshape(pix.h, pix.w, 3)
            if HAS_CV2:
                img = cv2.cvtColor(img, cv2.COLOR_RGB2BGR)
        else:
            img = img_data.reshape(pix.h, pix.w)

        doc.close()
        return img
