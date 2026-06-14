"""Unit tests for catalog validation."""

from __future__ import annotations

import pytest

from src.byova.catalog import (
    CatalogLoadError,
    VirtualAgentCatalogEntry,
    validate_catalog_entries,
)


def test_validate_rejects_empty_catalog():
    with pytest.raises(CatalogLoadError):
        validate_catalog_entries([])


def test_validate_rejects_duplicate_ids():
    entries = [
        VirtualAgentCatalogEntry("1", "A"),
        VirtualAgentCatalogEntry("1", "B"),
    ]
    with pytest.raises(CatalogLoadError):
        validate_catalog_entries(entries)


def test_validate_rejects_multiple_defaults():
    entries = [
        VirtualAgentCatalogEntry("1", "A", is_default=True),
        VirtualAgentCatalogEntry("2", "B", is_default=True),
    ]
    with pytest.raises(CatalogLoadError):
        validate_catalog_entries(entries)
