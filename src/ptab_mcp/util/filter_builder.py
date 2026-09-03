"""
FilterBuilder - Fluent API for building USPTO API filter arrays.

Eliminates 135 lines of duplicated filter-building code across search functions.
Implements the Builder Pattern with method chaining for clean, readable code.
"""

from datetime import date
from typing import Any, Dict, List, Optional, Union

#: Floor used when a caller gives only the upper bound of a date range. The
#: USPTO ODP API rejects a rangeFilter carrying a null bound with HTTP 400
#: Bad Request (verified live 2026-08-30 on trials/proceedings/search, both
#: directions), so a one-sided range has to be closed client-side. 1990-01-01
#: predates the PTAB itself (the AIA trials began in 2012) and every PTAB
#: appeal and interference record in the corpus, so it is an open lower bound
#: in practice.
DEFAULT_RANGE_FROM = "1990-01-01"


def _today() -> str:
    """Ceiling used when a caller gives only the lower bound of a range."""
    return date.today().isoformat()


class FilterBuilder:
    """
    Fluent API for building USPTO Open Data Portal API filter arrays.

    This class eliminates duplicated filter-building logic by providing a
    chainable interface for constructing filter and range filter arrays.

    Benefits:
    - Eliminates 135 lines of duplicated code (6% of codebase)
    - Single source of truth for filter construction
    - Type-safe and IDE-friendly with autocomplete
    - Consistent behavior across all search functions

    Example:
        >>> from ptab_mcp.util.filter_builder import FilterBuilder
        >>> from ptab_mcp.config.filter_field_mapping import TrialFilterFields as Fields
        >>>
        >>> filters, range_filters = (FilterBuilder()
        ...     .add_if(Fields.TRIAL_NUMBER, "IPR2024-01353")
        ...     .add_if(Fields.PATENT_NUMBER, "10701173")
        ...     .add_if(Fields.PETITIONER_NAME, "Apple Inc")
        ...     .add_range_if(Fields.FILING_DATE, "2024-01-01", "2024-12-31")
        ...     .build())
        >>>
        >>> # Result:
        >>> # filters = [
        >>> #     {"name": "trialNumber", "value": ["IPR2024-01353"]},
        >>> #     {"name": "patentOwnerData.patentNumber", "value": ["10701173"]},
        >>> #     {"name": "regularPetitionerData.realPartyInInterestName", "value": ["Apple Inc"]}
        >>> # ]
        >>> # range_filters = [
        >>> #     {"field": "trialMetaData.accordedFilingDate", "valueFrom": "2024-01-01", "valueTo": "2024-12-31"}
        >>> # ]
    """

    def __init__(self):
        """Initialize empty filter arrays."""
        self._filters: List[Dict[str, Any]] = []
        self._range_filters: List[Dict[str, Any]] = []

    def add_if(self, field_name: str, value: Optional[Union[str, List[str]]]) -> 'FilterBuilder':
        """
        Add exact-match filter only if value is not None (fluent interface).
        Accepts a single string or a list of strings (OR semantics in the API).

        Args:
            field_name: API field name (e.g., "trialNumber", "patentOwnerData.patentNumber")
            value: Filter value — string or list of strings (only added if not None/empty)

        Returns:
            Self for method chaining

        Example:
            >>> builder = FilterBuilder()
            >>> builder.add_if("trialNumber", "IPR2024-01353")  # Single value
            >>> builder.add_if("trialNumber", ["IPR2024-01353", "IPR2024-00965"])  # Bulk OR
            >>> builder.add_if("patentNumber", None)  # Skipped
            >>> builder.add_if("petitioner", "")  # Skipped
        """
        if value is None or value == "" or value == []:
            return self
        if isinstance(value, list):
            values = [v for v in value if v]
            if values:
                self._filters.append({"name": field_name, "value": values})
        else:
            self._filters.append({"name": field_name, "value": [value]})
        return self

    def add_range_if(
        self,
        field_name: str,
        value_from: Optional[str],
        value_to: Optional[str],
        *,
        default_from: str = DEFAULT_RANGE_FROM,
        default_to: Optional[str] = None,
    ) -> 'FilterBuilder':
        """
        Add range filter only if at least one value is not None.

        Used for date ranges, numeric ranges, etc.

        A ONE-SIDED range is closed client-side rather than passed through.
        The API rejects {"valueFrom": X, "valueTo": null} with HTTP 400 Bad
        Request (and the mirror image too), so every "everything since
        2024-01-01" search used to fail outright instead of returning
        results. The missing bound is filled with DEFAULT_RANGE_FROM
        (1990-01-01, well before the PTAB's own records) or today.

        Args:
            field_name: API field name (e.g., "trialMetaData.accordedFilingDate")
            value_from: Start of range (inclusive). Defaults to
                DEFAULT_RANGE_FROM when only value_to is given.
            value_to: End of range (inclusive). Defaults to today when only
                value_from is given.
            default_from: Override the substituted lower bound.
            default_to: Override the substituted upper bound (defaults to today).

        Returns:
            Self for method chaining

        Example:
            >>> builder = FilterBuilder()
            >>> builder.add_range_if("filingDate", "2024-01-01", "2024-12-31")  # Added
            >>> builder.add_range_if("filingDate", "2024-01-01", None)  # Added, valueTo = today
            >>> builder.add_range_if("filingDate", None, "2024-12-31")  # Added, valueFrom = 1990-01-01
            >>> builder.add_range_if("filingDate", None, None)  # Skipped
        """
        if value_from is None and value_to is None:
            return self
        self._range_filters.append({
            "field": field_name,
            "valueFrom": value_from if value_from is not None else default_from,
            "valueTo": value_to if value_to is not None else (default_to or _today()),
        })
        return self

    def build(self) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """
        Build and return filter arrays.

        Returns:
            Tuple of (filters, range_filters) ready for USPTO API calls

        Example:
            >>> filters, range_filters = (FilterBuilder()
            ...     .add_if("trialNumber", "IPR2024-01353")
            ...     .add_range_if("filingDate", "2024-01-01", "2024-12-31")
            ...     .build())
        """
        return self._filters, self._range_filters

    def __repr__(self) -> str:
        """String representation for debugging."""
        return f"FilterBuilder(filters={len(self._filters)}, range_filters={len(self._range_filters)})"
