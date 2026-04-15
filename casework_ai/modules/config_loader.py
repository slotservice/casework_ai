"""
Configuration Loader Module
Loads and validates project configuration from YAML settings file.
"""

import os
import yaml
import logging
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


class ConfigLoader:
    """Loads and manages pipeline configuration."""

    def __init__(self, config_path: Optional[str] = None):
        if config_path is None:
            config_path = os.path.join(
                os.path.dirname(os.path.dirname(__file__)),
                "config", "settings.yaml"
            )
        self.config_path = Path(config_path)
        self.config: Dict[str, Any] = {}
        self._load()

    def _load(self):
        """Load configuration from YAML file."""
        if not self.config_path.exists():
            raise FileNotFoundError(f"Config file not found: {self.config_path}")

        with open(self.config_path, "r", encoding="utf-8") as f:
            self.config = yaml.safe_load(f)

        # Resolve relative paths relative to config file location
        base_dir = self.config_path.parent.parent
        paths = self.config.get("paths", {})
        for key, value in paths.items():
            if isinstance(value, str) and value.startswith(".."):
                paths[key] = str((base_dir / value).resolve())

        # Ensure output directories exist
        for dir_key in ["output_dir", "logs_dir", "rules_dir"]:
            dir_path = paths.get(dir_key, "")
            if dir_path:
                os.makedirs(dir_path, exist_ok=True)

        logger.info(f"Configuration loaded from {self.config_path}")

    def get(self, key_path: str, default: Any = None) -> Any:
        """Get a nested config value using dot notation (e.g., 'detection.min_cabinet_width_inches')."""
        keys = key_path.split(".")
        value = self.config
        for k in keys:
            if isinstance(value, dict):
                value = value.get(k)
                if value is None:
                    return default
            else:
                return default
        return value

    @property
    def paths(self) -> Dict[str, str]:
        return self.config.get("paths", {})

    @property
    def detection(self) -> Dict[str, Any]:
        return self.config.get("detection", {})

    @property
    def matching(self) -> Dict[str, Any]:
        return self.config.get("matching", {})

    @property
    def cad(self) -> Dict[str, Any]:
        return self.config.get("cad", {})

    @property
    def product_encoding(self) -> Dict[str, Any]:
        return self.config.get("product_encoding", {})
