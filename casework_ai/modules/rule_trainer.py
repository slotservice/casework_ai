"""
Rule Trainer Module
Natural language rule engine for teaching the AI matching rules in plain English.
Stores rules in human-readable JSON/YAML format.
Supports viewing, editing, enabling/disabling rules.
"""

import os
import json
import re
import logging
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from pathlib import Path

logger = logging.getLogger(__name__)


class RuleTrainer:
    """Manages custom matching rules with natural language input support."""

    def __init__(self, rules_dir: str):
        self.rules_dir = Path(rules_dir)
        self.rules_dir.mkdir(parents=True, exist_ok=True)
        self.rules_file = self.rules_dir / "custom_rules.json"
        self.rules: List[Dict] = []
        self._load_rules()

    def _load_rules(self):
        """Load existing rules from disk."""
        if self.rules_file.exists():
            with open(self.rules_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                self.rules = data.get("rules", [])
            logger.info(f"Loaded {len(self.rules)} custom rules")
        else:
            self.rules = []
            self._save_rules()

    def _save_rules(self):
        """Save rules to disk."""
        data = {
            "version": "1.0",
            "last_updated": datetime.now().isoformat(),
            "rules": self.rules,
        }
        with open(self.rules_file, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        logger.info(f"Saved {len(self.rules)} rules to {self.rules_file}")

    def add_rule_natural(self, text: str) -> Optional[Dict]:
        """
        Parse a natural language rule and add it.

        Supported patterns:
        - "if a base cabinet is 36 inch wide, use product 1410011"
        - "when width is 24 inches and type is drawer, assign 1210044"
        - "for sink cabinets wider than 30 inches, use 1310011"
        - "map 48 inch base cabinet to 1510011"
        """
        text = text.strip().lower()

        rule = self._parse_natural_rule(text)
        if rule:
            rule["id"] = len(self.rules) + 1
            rule["created"] = datetime.now().isoformat()
            rule["enabled"] = True
            rule["source_text"] = text
            self.rules.append(rule)
            self._save_rules()
            logger.info(f"Added rule #{rule['id']}: {rule['description']}")
            return rule
        else:
            logger.warning(f"Could not parse rule: {text}")
            return None

    def _parse_natural_rule(self, text: str) -> Optional[Dict]:
        """Parse natural language into a structured rule."""
        conditions = {}
        product_number = None
        description = text

        # Extract product number
        product_match = re.search(r'(?:use|assign|map\s+to)\s+(?:product\s+)?(\w{7,})', text)
        if product_match:
            product_number = product_match.group(1).upper()

        # Extract type conditions
        type_patterns = {
            "base cabinet": "base_cabinet",
            "wall cabinet": "wall_cabinet",
            "sink cabinet": "sink_cabinet",
            "drawer": "drawer_unit",
            "sink": "sink",
            "shelf": "open_shelf",
            "filler": "filler",
        }
        for pattern, type_val in type_patterns.items():
            if pattern in text:
                conditions["type"] = type_val
                break

        # Extract width conditions
        width_exact = re.search(r'(\d+)\s*(?:inch|")\s*wide', text)
        if width_exact:
            conditions["min_width"] = int(width_exact.group(1)) - 1
            conditions["max_width"] = int(width_exact.group(1)) + 1

        width_gt = re.search(r'wider\s+than\s+(\d+)', text)
        if width_gt:
            conditions["min_width"] = int(width_gt.group(1))

        width_lt = re.search(r'narrower\s+than\s+(\d+)', text)
        if width_lt:
            conditions["max_width"] = int(width_lt.group(1))

        # Extract feature conditions
        if "below sink" in text or "under sink" in text:
            conditions["has_circle"] = True

        if not product_number:
            return None

        return {
            "description": description,
            "conditions": conditions,
            "assign_product": product_number,
        }

    def add_rule_structured(self, conditions: Dict, product_number: str,
                           description: str = "") -> Dict:
        """Add a rule with structured conditions."""
        rule = {
            "id": len(self.rules) + 1,
            "description": description or f"Assign {product_number} when conditions match",
            "conditions": conditions,
            "assign_product": product_number,
            "created": datetime.now().isoformat(),
            "enabled": True,
            "source_text": "",
        }
        self.rules.append(rule)
        self._save_rules()
        return rule

    def list_rules(self) -> List[Dict]:
        """List all rules."""
        return self.rules

    def get_active_rules(self) -> List[Dict]:
        """Get only enabled rules."""
        return [r for r in self.rules if r.get("enabled", True)]

    def enable_rule(self, rule_id: int):
        """Enable a rule by ID."""
        for rule in self.rules:
            if rule.get("id") == rule_id:
                rule["enabled"] = True
                self._save_rules()
                return True
        return False

    def disable_rule(self, rule_id: int):
        """Disable a rule by ID."""
        for rule in self.rules:
            if rule.get("id") == rule_id:
                rule["enabled"] = False
                self._save_rules()
                return True
        return False

    def delete_rule(self, rule_id: int):
        """Delete a rule by ID."""
        self.rules = [r for r in self.rules if r.get("id") != rule_id]
        self._save_rules()

    def export_rules(self, format: str = "json") -> str:
        """Export rules for review."""
        if format == "json":
            return json.dumps(self.rules, indent=2)
        else:
            lines = ["=== CUSTOM MATCHING RULES ===", ""]
            for rule in self.rules:
                status = "ENABLED" if rule.get("enabled", True) else "DISABLED"
                lines.append(f"Rule #{rule['id']} [{status}]")
                lines.append(f"  Description: {rule['description']}")
                lines.append(f"  Conditions:  {json.dumps(rule['conditions'])}")
                lines.append(f"  Assigns:     {rule['assign_product']}")
                if rule.get("source_text"):
                    lines.append(f"  Original:    \"{rule['source_text']}\"")
                lines.append(f"  Created:     {rule['created']}")
                lines.append("")
            return "\n".join(lines)

    def learn_from_correction(self, detected_type: str, detected_width: float,
                              correct_product: str, notes: str = "") -> Dict:
        """
        Learn a new rule from a user correction.
        When the user corrects the AI's output, this creates a rule to handle
        similar cases in the future.
        """
        conditions = {"type": detected_type}
        if detected_width:
            conditions["min_width"] = detected_width - 1
            conditions["max_width"] = detected_width + 1

        description = (
            f"Learned from correction: {detected_type} ~{detected_width}\" "
            f"-> {correct_product}"
        )
        if notes:
            description += f" ({notes})"

        return self.add_rule_structured(conditions, correct_product, description)
