"""
Field Configuration Manager for PTAB MCP

Manages loading and filtering of field configurations from YAML.
Provides wildcard pattern expansion and context reduction calculation.
"""

import yaml
import json
from pathlib import Path
from typing import Dict, List, Any, Optional
from ..shared.safe_logger import get_safe_logger

logger = get_safe_logger(__name__)


class FieldManager:
    """Manages field configurations for PTAB API responses"""

    def __init__(self, config_path: Path):
        """
        Initialize field manager with configuration file.

        Args:
            config_path: Path to field_configs.yaml file
        """
        self.config_path = config_path
        self.config_data: Dict[str, Any] = {}
        self.load_config()

    def load_config(self) -> None:
        """Load field configuration from YAML file with graceful fallback"""
        try:
            if not self.config_path.exists():
                raise FileNotFoundError(f"Field config file not found: {self.config_path}")

            with open(self.config_path, 'r', encoding='utf-8') as f:
                self.config_data = yaml.safe_load(f)

            logger.info(f"Loaded field configuration from {self.config_path}")
            logger.debug(f"Available field sets: {list(self.get_predefined_sets().keys())}")

        except (FileNotFoundError, yaml.YAMLError, Exception) as e:
            logger.error(f"Failed to load field configuration: {e}. Using defaults.")
            self.config_data = self._get_default_config()
            logger.info("Using default field configuration")

    def _get_default_config(self) -> Dict[str, Any]:
        """Provide default field configuration when config file fails to load"""
        return {
            "version": "1.0",
            "description": "Default configuration (fallback)",
            "predefined_sets": {
                "trials_minimal": {
                    "description": "Essential fields for trial discovery",
                    "fields": [
                        "trialNumber",
                        "trialMetaData.accordedFilingDate",
                        "trialMetaData.trialTypeCode",
                        "regularPetitionerData.realPartyInInterestName",
                        "patentOwnerData.patentOwnerName",
                        "patentOwnerData.patentNumber"
                    ]
                },
                "appeals_minimal": {
                    "description": "Essential fields for appeal discovery",
                    "fields": [
                        "appealNumber",
                        "applicationNumber",
                        "documentData.documentFilingDate",
                        "appellantData.technologyCenterNumber"
                    ]
                },
                "interferences_minimal": {
                    "description": "Essential fields for interference discovery",
                    "fields": [
                        "interferenceNumber",
                        "documentData.documentFilingDate"
                    ]
                }
            },
            "context_settings": {
                "minimal_reduction_percentage": 95,
                "balanced_reduction_percentage": 85,
                "complete_reduction_percentage": 80,
                "max_field_count_minimal": 15,
                "max_field_count_balanced": 50
            }
        }

    def get_predefined_sets(self) -> Dict[str, Dict]:
        """Get all predefined field sets"""
        return self.config_data.get("predefined_sets", {})

    def get_fields(self, field_set: str) -> List[str]:
        """
        Get fields for a specific field set.

        Args:
            field_set: Name of field set (e.g., 'trials_minimal')

        Returns:
            List of field names (may include wildcards)
        """
        sets = self.get_predefined_sets()
        if field_set not in sets:
            available = list(sets.keys())
            raise ValueError(f"Field set '{field_set}' not found. Available: {available}")

        fields = sets[field_set].get("fields", [])
        logger.debug(f"Retrieved {len(fields)} fields for set '{field_set}'")
        return fields

    def get_context_settings(self) -> Dict[str, int]:
        """Get context management settings"""
        return self.config_data.get("context_settings", {})

    def filter_response_custom(self, data: Dict[str, Any], custom_fields: List[str]) -> Dict[str, Any]:
        """
        Filter API response to custom field list (PFW-style dynamic field selection).

        Args:
            data: Raw API response data
            custom_fields: List of field names (with dot notation for nested fields)
                          Examples: ["trialNumber", "trialMetaData.trialStatusCategory"]

        Returns:
            Filtered response data with context_info metadata

        Example:
            custom_fields = ["trialNumber", "trialMetaData.trialStatusCategory"]
            Returns only these 2 fields per trial
        """
        return self._filter_response_impl(data, custom_fields, "custom")

    def filter_response(self, data: Dict[str, Any], field_set: str) -> Dict[str, Any]:
        """
        Filter API response to only include configured fields.

        Args:
            data: Raw API response data
            field_set: Name of field set to use for filtering

        Returns:
            Filtered response data with context_info metadata
        """
        return self._filter_response_impl(data, self.get_fields(field_set), field_set)

    def _filter_response_impl(
        self, data: Dict[str, Any], fields: List[str], field_set_name: str
    ) -> Dict[str, Any]:
        """Shared body of filter_response / filter_response_custom (dedup 2.2)."""
        # Handle wildcard "*" - return all data as-is
        if "*" in fields:
            logger.debug("Wildcard '*' detected, returning complete data")
            return data

        # Determine results key based on data type
        results_key = self._detect_results_key(data)
        count_key = "count" if "count" in data else "recordTotalQuantity"

        if results_key and results_key in data and isinstance(data[results_key], list):
            # Filter each result item
            filtered_results = []
            for item in data[results_key]:
                # Expand wildcards based on actual data structure
                expanded_fields = self._expand_wildcards(fields, item)
                filtered_item = self._filter_item(item, expanded_fields)
                filtered_results.append(filtered_item)

            # Create filtered response
            filtered_data = {
                results_key: filtered_results,
                count_key: data.get(count_key, len(filtered_results)),
            }

            # Calculate context reduction
            original_sample = data[results_key][0] if data[results_key] else {}
            filtered_sample = filtered_results[0] if filtered_results else {}

            # Add context info
            filtered_data["context_info"] = {
                "field_set": field_set_name,
                "fields_configured": len(fields),
                "fields_expanded": len(expanded_fields) if filtered_results else 0,
                "original_field_count": len(self._get_all_keys(original_sample)),
                "filtered_field_count": len(self._get_all_keys(filtered_sample)),
                "context_reduction": self._calculate_reduction(original_sample, filtered_sample)
            }

            logger.debug(f"Filtered response ({field_set_name}): {len(filtered_results)} items with {len(expanded_fields)} fields each")
            return filtered_data

        else:
            # Single item or unexpected format
            expanded_fields = self._expand_wildcards(fields, data)
            return self._filter_item(data, expanded_fields)

    def _detect_results_key(self, data: Dict[str, Any]) -> Optional[str]:
        """Detect the results key based on data structure"""
        # PTAB API uses different keys for different data types
        if "patentTrialProceedingDataBag" in data:
            return "patentTrialProceedingDataBag"
        elif "patentAppealDataBag" in data:
            return "patentAppealDataBag"
        elif "patentInterferenceDataBag" in data:
            return "patentInterferenceDataBag"
        elif "results" in data:
            return "results"
        return None

    def _expand_wildcards(self, fields: List[str], sample_data: Dict[str, Any]) -> List[str]:
        """
        Expand wildcard patterns to actual field names.

        Args:
            fields: Field list with potential wildcards (e.g., "trialMetaData.*")
            sample_data: Sample data item to expand wildcards against

        Returns:
            Expanded field list with wildcards replaced by actual field names
        """
        expanded = []

        for field in fields:
            if field == "*":
                # Full wildcard - get all fields
                expanded.extend(self._get_all_keys(sample_data))
            elif field.endswith(".*"):
                # Prefix wildcard (e.g., "trialMetaData.*")
                prefix = field[:-2]  # Remove ".*"
                matching_fields = self._find_matching_fields(prefix, sample_data)
                expanded.extend(matching_fields)
            else:
                # Regular field
                expanded.append(field)

        # Remove duplicates while preserving order
        seen = set()
        result = []
        for field in expanded:
            if field not in seen:
                seen.add(field)
                result.append(field)

        return result

    def _find_matching_fields(self, prefix: str, data: Dict[str, Any]) -> List[str]:
        """
        Find all fields matching a prefix pattern.

        Args:
            prefix: Field prefix (e.g., "trialMetaData")
            data: Data to search for matching fields

        Returns:
            List of matching field names with full paths
        """
        matching = []

        # Check if prefix is a nested object
        if prefix in data and isinstance(data[prefix], dict):
            # Expand all sub-fields
            for sub_field in data[prefix].keys():
                matching.append(f"{prefix}.{sub_field}")
        else:
            # Search for fields starting with prefix
            for key in data.keys():
                if key.startswith(prefix):
                    matching.append(key)

        return matching

    def _get_all_keys(self, data: Dict[str, Any], prefix: str = "") -> List[str]:
        """
        Get all keys from a nested dictionary.

        Args:
            data: Dictionary to extract keys from
            prefix: Current prefix for nested keys

        Returns:
            List of all keys (including nested ones with dot notation)
        """
        keys = []

        if not isinstance(data, dict):
            return keys

        for key, value in data.items():
            full_key = f"{prefix}.{key}" if prefix else key
            keys.append(full_key)

            if isinstance(value, dict):
                # Recursively get nested keys
                nested_keys = self._get_all_keys(value, full_key)
                keys.extend(nested_keys)

        return keys

    def _filter_item(self, item: Dict[str, Any], fields: List[str]) -> Dict[str, Any]:
        """
        Filter a single item to only include specified fields.

        Supports dot notation for nested fields (e.g., "trialMetaData.trialTypeCode")

        Args:
            item: Item to filter
            fields: List of field paths to include

        Returns:
            Filtered item
        """
        if not isinstance(item, dict):
            return item

        filtered = {}

        for field in fields:
            # Handle nested fields with dot notation
            if "." in field:
                parts = field.split(".", 1)
                parent = parts[0]
                child_path = parts[1]

                if parent in item:
                    if parent not in filtered:
                        filtered[parent] = {}

                    # Recursively filter nested object
                    if isinstance(item[parent], dict):
                        child_value = self._filter_item(item[parent], [child_path])
                        if child_value:
                            # Merge nested results
                            if isinstance(filtered[parent], dict):
                                filtered[parent].update(child_value)
                            else:
                                filtered[parent] = child_value
            else:
                # Simple field - direct copy
                if field in item:
                    filtered[field] = item[field]

        return filtered

    def _calculate_reduction(self, original_data: Dict[str, Any], filtered_data: Dict[str, Any]) -> str:
        """
        Calculate actual character-based context reduction percentage.

        Args:
            original_data: Original unfiltered data sample
            filtered_data: Filtered data sample

        Returns:
            Context reduction percentage as string (e.g., "95%")
        """
        try:
            # Calculate character count of JSON representations
            original_chars = len(json.dumps(original_data, separators=(',', ':')))
            filtered_chars = len(json.dumps(filtered_data, separators=(',', ':')))

            if original_chars == 0:
                return "0%"

            # Calculate actual context reduction
            reduction = ((original_chars - filtered_chars) / original_chars) * 100
            return f"{reduction:.1f}%"

        except Exception as e:
            logger.warning(f"Could not calculate character reduction: {e}")
            return "N/A"

    def reload_config(self) -> bool:
        """
        Reload configuration from YAML file.

        This allows updating field configurations without restarting the server.
        Call this after editing field_configs.yaml to apply changes.

        Returns:
            bool: True if reload successful, False otherwise
        """
        try:
            self.load_config()
            logger.info(f"Configuration reloaded successfully from {self.config_path}")
            return True
        except Exception as e:
            logger.error(f"Failed to reload configuration: {e}")
            return False
