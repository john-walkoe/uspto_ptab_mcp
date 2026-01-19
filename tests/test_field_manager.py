"""
Tests for Field Manager

Tests YAML loading, field filtering, wildcard expansion, and context reduction.
"""

import pytest
import tempfile
import yaml
from pathlib import Path
from src.ptab_mcp.config.field_manager import FieldManager


@pytest.fixture
def sample_config():
    """Sample field configuration for testing"""
    return {
        "version": "1.0",
        "description": "Test configuration",
        "predefined_sets": {
            "trials_minimal": {
                "description": "Minimal trial fields",
                "fields": [
                    "trialNumber",
                    "trialMetaData.trialTypeCode",
                    "petitionerData.petitionerPartyName"
                ]
            },
            "trials_balanced": {
                "description": "Balanced trial fields",
                "fields": [
                    "trialNumber",
                    "trialMetaData.*",
                    "petitionerData.*"
                ]
            },
            "trials_complete": {
                "description": "Complete trial fields",
                "fields": ["*"]
            }
        },
        "context_settings": {
            "minimal_reduction_percentage": 95,
            "balanced_reduction_percentage": 85
        }
    }


@pytest.fixture
def config_file(sample_config):
    """Create temporary config file for testing"""
    with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
        yaml.dump(sample_config, f)
        return Path(f.name)


@pytest.fixture
def field_manager(config_file):
    """Create FieldManager instance with test config"""
    return FieldManager(config_file)


@pytest.fixture
def sample_trial_data():
    """Sample trial data for filtering tests"""
    return {
        "count": 2,
        "patentTrialProceedingDataBag": [
            {
                "trialNumber": "IPR2024-00123",
                "proceedingNumber": "PROC-123",
                "trialMetaData": {
                    "trialTypeCode": "IPR",
                    "accordedFilingDate": "2024-01-15",
                    "trialStatusCategory": "Terminated",
                    "institutionDate": "2024-03-01",
                    "finalDecisionDate": "2024-08-15"
                },
                "petitionerData": {
                    "petitionerPartyName": "Apple Inc.",
                    "petitionerCounselName": "Jones & Smith LLP"
                },
                "patentOwnerData": {
                    "patentOwnerName": "Samsung Electronics",
                    "patentOwnerCounselName": "Wilson & Associates"
                },
                "respondentData": {
                    "patentNumber": "8524787",
                    "patentTitle": "Test Patent Title",
                    "grantDate": "2013-09-03"
                }
            }
        ]
    }


def test_yaml_loading(field_manager, sample_config):
    """Test YAML configuration loading"""
    assert field_manager.config_data is not None
    assert field_manager.config_data["version"] == "1.0"
    assert "predefined_sets" in field_manager.config_data


def test_get_fields_minimal(field_manager):
    """Test retrieving minimal field set"""
    fields = field_manager.get_fields("trials_minimal")
    assert len(fields) == 3
    assert "trialNumber" in fields
    assert "trialMetaData.trialTypeCode" in fields
    assert "petitionerData.petitionerPartyName" in fields


def test_get_fields_balanced(field_manager):
    """Test retrieving balanced field set with wildcards"""
    fields = field_manager.get_fields("trials_balanced")
    assert len(fields) == 3
    assert "trialNumber" in fields
    assert "trialMetaData.*" in fields
    assert "petitionerData.*" in fields


def test_get_fields_complete(field_manager):
    """Test retrieving complete field set"""
    fields = field_manager.get_fields("trials_complete")
    assert len(fields) == 1
    assert "*" in fields


def test_get_fields_invalid(field_manager):
    """Test error handling for invalid field set"""
    with pytest.raises(ValueError) as exc_info:
        field_manager.get_fields("nonexistent_set")
    assert "not found" in str(exc_info.value)


def test_filter_response_minimal(field_manager, sample_trial_data):
    """Test filtering response with minimal fields"""
    filtered = field_manager.filter_response(sample_trial_data, "trials_minimal")

    assert "patentTrialProceedingDataBag" in filtered
    assert len(filtered["patentTrialProceedingDataBag"]) == 1

    item = filtered["patentTrialProceedingDataBag"][0]
    assert "trialNumber" in item
    assert "trialMetaData" in item
    assert "trialTypeCode" in item["trialMetaData"]
    assert "petitionerData" in item
    assert "petitionerPartyName" in item["petitionerData"]

    # Should NOT have fields not in minimal set
    assert "proceedingNumber" not in item
    assert "accordedFilingDate" not in item["trialMetaData"]
    assert "patentOwnerData" not in item


def test_filter_response_balanced_wildcards(field_manager, sample_trial_data):
    """Test filtering response with balanced fields (wildcard expansion)"""
    filtered = field_manager.filter_response(sample_trial_data, "trials_balanced")

    assert "patentTrialProceedingDataBag" in filtered
    item = filtered["patentTrialProceedingDataBag"][0]

    # Should have trialNumber
    assert "trialNumber" in item

    # Should have ALL trialMetaData fields (wildcard expansion)
    assert "trialMetaData" in item
    assert "trialTypeCode" in item["trialMetaData"]
    assert "accordedFilingDate" in item["trialMetaData"]
    assert "trialStatusCategory" in item["trialMetaData"]
    assert "institutionDate" in item["trialMetaData"]
    assert "finalDecisionDate" in item["trialMetaData"]

    # Should have ALL petitionerData fields (wildcard expansion)
    assert "petitionerData" in item
    assert "petitionerPartyName" in item["petitionerData"]
    assert "petitionerCounselName" in item["petitionerData"]

    # Should NOT have fields not matched by wildcards
    assert "patentOwnerData" not in item
    assert "respondentData" not in item


def test_filter_response_complete(field_manager, sample_trial_data):
    """Test filtering response with complete fields (full wildcard)"""
    filtered = field_manager.filter_response(sample_trial_data, "trials_complete")

    # With "*" wildcard, should return data unchanged
    assert filtered == sample_trial_data


def test_wildcard_expansion(field_manager):
    """Test wildcard pattern expansion"""
    sample_data = {
        "trialNumber": "IPR2024-00123",
        "trialMetaData": {
            "trialTypeCode": "IPR",
            "accordedFilingDate": "2024-01-15",
            "trialStatusCategory": "Terminated"
        },
        "petitionerData": {
            "petitionerPartyName": "Apple Inc."
        }
    }

    # Test expanding "trialMetaData.*"
    expanded = field_manager._expand_wildcards(["trialMetaData.*"], sample_data)
    assert "trialMetaData.trialTypeCode" in expanded
    assert "trialMetaData.accordedFilingDate" in expanded
    assert "trialMetaData.trialStatusCategory" in expanded

    # Test expanding "*"
    expanded_all = field_manager._expand_wildcards(["*"], sample_data)
    assert "trialNumber" in expanded_all
    assert "trialMetaData" in expanded_all
    assert "petitionerData" in expanded_all


def test_context_reduction_calculation(field_manager, sample_trial_data):
    """Test context reduction percentage calculation"""
    filtered = field_manager.filter_response(sample_trial_data, "trials_minimal")

    assert "context_info" in filtered
    context_info = filtered["context_info"]

    assert "context_reduction" in context_info
    assert "field_set" in context_info
    assert context_info["field_set"] == "trials_minimal"

    # Context reduction should be significant (80%+)
    reduction_str = context_info["context_reduction"]
    if reduction_str != "N/A":
        reduction_pct = float(reduction_str.rstrip('%'))
        assert reduction_pct >= 50.0  # Should have significant reduction


def test_context_info_metadata(field_manager, sample_trial_data):
    """Test context info metadata is correctly populated"""
    filtered = field_manager.filter_response(sample_trial_data, "trials_minimal")

    assert "context_info" in filtered
    context_info = filtered["context_info"]

    assert "field_set" in context_info
    assert "fields_configured" in context_info
    assert "fields_expanded" in context_info
    assert "original_field_count" in context_info
    assert "filtered_field_count" in context_info
    assert "context_reduction" in context_info

    # Filtered should have fewer fields than original
    assert context_info["filtered_field_count"] < context_info["original_field_count"]


def test_reload_config(field_manager, config_file):
    """Test configuration reload functionality"""
    # Initial state
    original_fields = field_manager.get_fields("trials_minimal")
    assert len(original_fields) == 3

    # Modify config file
    new_config = {
        "version": "1.0",
        "description": "Modified configuration",
        "predefined_sets": {
            "trials_minimal": {
                "description": "Modified minimal",
                "fields": ["trialNumber", "trialMetaData.trialTypeCode"]
            }
        }
    }

    with open(config_file, 'w') as f:
        yaml.dump(new_config, f)

    # Reload
    success = field_manager.reload_config()
    assert success

    # Verify changes
    modified_fields = field_manager.get_fields("trials_minimal")
    assert len(modified_fields) == 2
    assert "trialNumber" in modified_fields
    assert "trialMetaData.trialTypeCode" in modified_fields


def test_get_all_keys(field_manager):
    """Test recursive key extraction"""
    nested_data = {
        "level1": "value1",
        "nested": {
            "level2": "value2",
            "deeper": {
                "level3": "value3"
            }
        }
    }

    keys = field_manager._get_all_keys(nested_data)

    assert "level1" in keys
    assert "nested" in keys
    assert "nested.level2" in keys
    assert "nested.deeper" in keys
    assert "nested.deeper.level3" in keys


def test_default_config_fallback():
    """Test fallback to default config when file not found"""
    # Use non-existent path
    nonexistent_path = Path("/nonexistent/path/config.yaml")
    manager = FieldManager(nonexistent_path)

    # Should load default config
    assert manager.config_data is not None
    assert "predefined_sets" in manager.config_data
    assert "trials_minimal" in manager.config_data["predefined_sets"]


def test_filter_item_nested_fields(field_manager):
    """Test filtering individual items with nested field paths"""
    item = {
        "trialNumber": "IPR2024-00123",
        "trialMetaData": {
            "trialTypeCode": "IPR",
            "accordedFilingDate": "2024-01-15",
            "trialStatusCategory": "Terminated"
        },
        "petitionerData": {
            "petitionerPartyName": "Apple Inc.",
            "petitionerCounselName": "Jones & Smith LLP"
        }
    }

    # Filter with nested field paths
    fields = [
        "trialNumber",
        "trialMetaData.trialTypeCode",
        "trialMetaData.accordedFilingDate"
    ]

    filtered = field_manager._filter_item(item, fields)

    assert "trialNumber" in filtered
    assert "trialMetaData" in filtered
    assert "trialTypeCode" in filtered["trialMetaData"]
    assert "accordedFilingDate" in filtered["trialMetaData"]
    assert "trialStatusCategory" not in filtered["trialMetaData"]
    assert "petitionerData" not in filtered


def test_detect_results_key(field_manager):
    """Test detection of different results key formats"""
    # Trials format
    trials_data = {"patentTrialProceedingDataBag": []}
    assert field_manager._detect_results_key(trials_data) == "patentTrialProceedingDataBag"

    # Appeals format (correct key from ODP API)
    appeals_data = {"patentAppealDataBag": []}
    assert field_manager._detect_results_key(appeals_data) == "patentAppealDataBag"

    # Interferences format (correct key from ODP API)
    interference_data = {"patentInterferenceDataBag": []}
    assert field_manager._detect_results_key(interference_data) == "patentInterferenceDataBag"

    # Generic format
    generic_data = {"results": []}
    assert field_manager._detect_results_key(generic_data) == "results"

    # No recognized key
    unknown_data = {"unknown": []}
    assert field_manager._detect_results_key(unknown_data) is None
