"""Shared validator for stock_scanner universe configuration (config/universe.yaml).

Validates that the universe YAML contains only well-formed category entries
with properly-typed symbol lists.  Rejects invalid data types (booleans, numbers,
null, lists, mappings) and structural problems early, rather than silently
filtering them out downstream.

This module is deliberately self-contained with no dependencies beyond the
standard library and ``yaml``, so it can be imported and used by any entry point
that loads the universe configuration.
"""
from __future__ import annotations

import yaml
from typing import Any, Dict, List, Set, Tuple

__all__ = [
    "validate_universe_yaml",
    "UniverseValidationError",
]


class UniverseValidationError(ValueError):
    """Raised when the universe configuration is malformed.

    Attributes:
        message: Human-readable explanation of the validation failure.
        file_path: Path to the YAML file that failed validation.
        category: Category name where the problem was found (if applicable).
        entry: Symbol or sub-entry that caused the failure (if applicable).
        line: Approximate line number within the YAML (if determinable).
    """

    def __init__(
        self,
        message: str,
        *,
        file_path: str | None = None,
        category: str | None = None,
        entry: str | None = None,
        line: int | None = None,
    ):
        super().__init__(message)
        self.message = message
        self.file_path = file_path
        self.category = category
        self.entry = entry
        self.line = line

    def __str__(self):
        parts = [self.message]
        if self.file_path:
            parts.append(f"in {self.file_path}")
        if self.category:
            parts.append(f"category '{self.category}'")
        if self.entry is not None:
            parts.append(f"entry '{self.entry}'")
        if self.line is not None:
            parts.append(f"at line {self.line}")
        return " | ".join(parts)


def _check_type(
    value: Any,
    expected: type,
    error_msg: str,
    path: str,
) -> None:
    """Raise UniverseValidationError if value is not of the expected type."""
    if not isinstance(value, expected):
        raise UniverseValidationError(
            error_msg,
            file_path=path,
        )


def _check_not_empty(
    value: str,
    *,
    error_msg: str,
    path: str,
    category: str | None = None,
    entry: str | None = None,
) -> None:
    """Raise UniverseValidationError if value is empty or whitespace-only."""
    if value is None or value.strip() == "":
        raise UniverseValidationError(
            error_msg,
            file_path=path,
            category=category,
            entry=entry,
        )


def validate_universe_yaml(
    config: dict,
    *,
    file_path: str | None = None,
) -> None:
    """Validate a loaded universe YAML configuration.

    Performs the following checks:

    1. The root object is a mapping (dict).
    2. The ``categories`` key exists and maps to a dict.
    3. Each category value is a mapping with at least a ``symbols`` key.
    4. Each category's ``symbols`` entry is a list.
    5. Every symbol in every ``symbols`` list is a non-empty string
       after ``str.strip()``.
    6. Boolean, numeric, null, list, or mapping entries in symbol lists
       are rejected.
    7. Duplicate symbols within a category are rejected.
    8. Duplicate symbols across categories are permitted (following existing
       documented universe/category semantics where a symbol may belong to
       multiple categories — e.g., NVDA appears in both ``semiconductors``
       and ``technology``).
    9. Empty ``symbols`` lists and categories with no valid symbols are
       rejected.
    10. Empty or whitespace-only category names are rejected.

    Unknown top-level fields (beyond ``market_benchmarks``,
    ``etf_symbols``, ``sector_indexes``, ``categories``) are permitted without
    error, following the existing convention of forward-compatible YAML.

    Args:
        config: The parsed YAML dict (as returned by ``yaml.safe_load``).
        file_path: Optional path to the YAML file, for inclusion in error messages.

    Raises:
        UniverseValidationError: If any validation rule is violated.
    """
    if not isinstance(config, dict):
        raise UniverseValidationError(
            "Universe configuration root must be a mapping (dict).",
            file_path=file_path,
        )

    # Require that 'categories' key exists and is a non-empty mapping.
    if "categories" not in config or not config["categories"]:
        raise UniverseValidationError(
            "Universe configuration must contain a non-empty 'categories' field.",
            file_path=file_path,
        )

    # Validate that 'categories' key is a mapping.
    _check_type(
        config["categories"], dict,
        "'categories' field must be a mapping (dict).",
        file_path or "config/universe.yaml",
    )

    # 2. Validate each category.
    categories: dict[str, Any] = config["categories"]
    # Track symbols seen across categories for duplicate-across-category reporting.
    # We permit cross-category duplicates per documented semantics, but we track
    # them here in case future behavior changes.
    seen_across_categories: Dict[str, List[Tuple[str, int]]] = {}  # symbol -> [(category, idx), ...]

    for cat_name, cat_data in categories.items():
        # Category name must be a string.
        _check_type(
            cat_name, str,
            f"Category name must be a string, got {type(cat_name).__name__}.",
            file_path or "config/universe.yaml",
        )
        # Category name must not be empty or whitespace-only.
        _check_not_empty(
            cat_name,
            error_msg="Category name must not be empty or whitespace-only.",
            path=file_path or "config/universe.yaml",
            category=cat_name,
        )

        # Category data must be a mapping.
        _check_type(
            cat_data, dict,
            f"Category '{cat_name}' data must be a mapping (dict).",
            file_path or "config/universe.yaml",
        )

        # The category must have a 'symbols' key.
        if "symbols" not in cat_data:
            raise UniverseValidationError(
                "Each category must contain a 'symbols' key.",
                file_path=file_path or "config/universe.yaml",
                category=cat_name,
            )

        symbols = cat_data["symbols"]
        # Symbols must be a list.
        _check_type(
            symbols, list,
            f"Category '{cat_name}' 'symbols' must be a list.",
            file_path or "config/universe.yaml",
        )

        # Validate each symbol in the list.
        cat_seen: Set[str] = set()
        for idx, sym in enumerate(symbols):
            # Every symbol must be a string (not bool, int, None, list, dict, etc.).
            if not isinstance(sym, str):
                raise UniverseValidationError(
                    f"Symbol at index {idx} in category '{cat_name}' must be a string, "
                    f"got {type(sym).__name__} {sym!r}.",
                    file_path=file_path or "config/universe.yaml",
                    category=cat_name,
                    entry=f"symbol[{idx}] = {sym!r} ({type(sym).__name__})",
                )

            # After stripping whitespace, symbol must not be empty.
            stripped = sym.strip()
            _check_not_empty(
                stripped,
                error_msg="Symbol must be a non-empty string after trimming whitespace.",
                path=file_path or "config/universe.yaml",
                category=cat_name,
                entry=f"symbol[{idx}] = '{sym}'",
            )

            # Check for duplicates within this category.
            if stripped in cat_seen:
                raise UniverseValidationError(
                    f"Duplicate symbol '{stripped}' within category '{cat_name}'.",
                    file_path=file_path or "config/universe.yaml",
                    category=cat_name,
                    entry=f"symbol[{idx}] = '{sym}'",
                )
            cat_seen.add(stripped)

            # Track across categories (permit duplicates, just record them).
            if stripped not in seen_across_categories:
                seen_across_categories[stripped] = []
            seen_across_categories[stripped].append((cat_name, idx))

    # 3. Reject categories where all symbols were invalid/empty so that the
    #    category effectively has no valid symbols.
    for cat_name, cat_data in categories.items():
        if "symbols" in cat_data and len(cat_data["symbols"]) == 0:
            # Empty symbols list — this is technically valid per the strict
            # rules (an empty list is a list), but it's likely unintentional.
            # We raise an error to be safe.
            raise UniverseValidationError(
                f"Category '{cat_name}' has an empty 'symbols' list.",
                file_path=file_path or "config/universe.yaml",
                category=cat_name,
            )

    # 4. Cross-category duplicate check: we permit them per documented
    #    semantics, but we log for awareness.  No error is raised for
    #    cross-category duplicates because symbols like NVDA legitimately
    #    appear in both ``semiconductors`` and ``technology``.
    #    (If future behavior changes, this is the place to add the restriction.)

    # Validation passed.
    return None