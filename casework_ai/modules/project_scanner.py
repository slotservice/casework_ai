"""
Project Scanner Module
Scans the project directory and creates an inventory of all available files.
Identifies PDFs, DWG blocks, catalogs, and reference materials.
"""

import os
import logging
from pathlib import Path
from typing import Dict, List, Optional
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class FileInfo:
    """Information about a single project file."""
    path: str
    filename: str
    extension: str
    size_bytes: int
    category: str  # 'input_pdf', 'reference_pdf', 'catalog', 'block_front', 'block_section', 'other'


@dataclass
class ProjectInventory:
    """Complete inventory of project files."""
    input_pdfs: List[FileInfo] = field(default_factory=list)
    reference_pdfs: List[FileInfo] = field(default_factory=list)
    catalogs: List[FileInfo] = field(default_factory=list)
    block_front_views: List[FileInfo] = field(default_factory=list)
    block_sections: List[FileInfo] = field(default_factory=list)
    other_files: List[FileInfo] = field(default_factory=list)

    @property
    def total_blocks(self) -> int:
        return len(self.block_front_views) + len(self.block_sections)

    def summary(self) -> str:
        lines = [
            "=== PROJECT INVENTORY ===",
            f"Input PDFs: {len(self.input_pdfs)}",
            f"Reference PDFs: {len(self.reference_pdfs)}",
            f"Catalogs: {len(self.catalogs)}",
            f"Front View Blocks: {len(self.block_front_views)}",
            f"Section Blocks: {len(self.block_sections)}",
            f"Total Blocks: {self.total_blocks}",
            f"Other files: {len(self.other_files)}",
        ]
        return "\n".join(lines)


class ProjectScanner:
    """Scans and catalogs all project files."""

    def __init__(self, project_root: str, config=None):
        self.project_root = Path(project_root)
        self.config = config
        self.inventory = ProjectInventory()

    def scan(self) -> ProjectInventory:
        """Perform full project scan and return inventory."""
        logger.info(f"Scanning project directory: {self.project_root}")

        if not self.project_root.exists():
            raise FileNotFoundError(f"Project root not found: {self.project_root}")

        # Scan top-level files
        for item in self.project_root.iterdir():
            if item.is_file():
                info = self._make_file_info(item)
                self._categorize_top_level(info)

        # Scan block library directories
        front_dir = self.project_root / "Casework - Front Views"
        if front_dir.exists():
            self._scan_block_dir(front_dir, "block_front")

        section_dir = self.project_root / "Casework Section - Metal"
        if section_dir.exists():
            self._scan_block_dir(section_dir, "block_section")

        logger.info(f"Scan complete. {self.inventory.summary()}")
        return self.inventory

    def _make_file_info(self, path: Path) -> FileInfo:
        return FileInfo(
            path=str(path),
            filename=path.name,
            extension=path.suffix.lower(),
            size_bytes=path.stat().st_size,
            category="unknown"
        )

    def _categorize_top_level(self, info: FileInfo):
        """Categorize a top-level file."""
        name_lower = info.filename.lower()

        if info.extension == ".pdf":
            if "catalog" in name_lower or "mott" in name_lower:
                info.category = "catalog"
                self.inventory.catalogs.append(info)
            elif "before" in name_lower or "a407" in name_lower:
                info.category = "input_pdf"
                self.inventory.input_pdfs.append(info)
            elif "after" in name_lower or "2-08" in name_lower:
                info.category = "reference_pdf"
                self.inventory.reference_pdfs.append(info)
            else:
                info.category = "other"
                self.inventory.other_files.append(info)
        else:
            info.category = "other"
            self.inventory.other_files.append(info)

    def _scan_block_dir(self, directory: Path, block_type: str):
        """Scan a block library directory for DWG files."""
        count = 0
        for item in sorted(directory.iterdir()):
            if item.is_file() and item.suffix.lower() == ".dwg":
                info = FileInfo(
                    path=str(item),
                    filename=item.name,
                    extension=item.suffix.lower(),
                    size_bytes=item.stat().st_size,
                    category=block_type
                )
                if block_type == "block_front":
                    self.inventory.block_front_views.append(info)
                else:
                    self.inventory.block_sections.append(info)
                count += 1

        logger.info(f"Found {count} DWG blocks in {directory.name}")

    def find_elevation_pdf(self, elevation_name: str = "E4") -> Optional[FileInfo]:
        """Find the input PDF that contains the target elevation."""
        # The elevation is embedded in the A407 PDF
        for pdf in self.inventory.input_pdfs:
            return pdf
        return None

    def get_block_names(self) -> List[str]:
        """Get sorted list of all block names (without .dwg extension)."""
        names = []
        for block in self.inventory.block_front_views:
            names.append(block.filename.replace(".dwg", ""))
        for block in self.inventory.block_sections:
            names.append(block.filename.replace(".dwg", ""))
        return sorted(set(names))
