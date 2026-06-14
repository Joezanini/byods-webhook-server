"""Unit tests for virtual agent catalog loading and validation."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.byova.catalog import CatalogLoadError, load_catalog


@pytest.fixture
def sample_catalog_path(tmp_path: Path) -> Path:
    path = tmp_path / "virtual_agents.json"
    path.write_text(
        json.dumps(
            [
                {
                    "virtual_agent_id": 1,
                    "virtual_agent_name": "Travel Booking Agent",
                    "is_default": False,
                },
                {
                    "virtual_agent_id": 2,
                    "virtual_agent_name": "Credit card service",
                    "is_default": False,
                },
            ]
        ),
        encoding="utf-8",
    )
    return path


def test_load_catalog_coerces_numeric_ids_to_string(sample_catalog_path: Path):
    entries = load_catalog(sample_catalog_path)
    assert len(entries) == 2
    assert entries[0].virtual_agent_id == "1"
    assert entries[0].virtual_agent_name == "Travel Booking Agent"


def test_load_default_sample_has_six_agents():
    entries = load_catalog("config/virtual_agents.json")
    assert len(entries) == 6
    names = {entry.virtual_agent_name for entry in entries}
    assert "Travel Booking Agent" in names
    assert "Barge-in General Agent" in names


def test_load_catalog_missing_file(tmp_path: Path):
    with pytest.raises(CatalogLoadError, match="not found"):
        load_catalog(tmp_path / "missing.json")


def test_load_catalog_invalid_json(tmp_path: Path):
    path = tmp_path / "bad.json"
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(CatalogLoadError, match="Invalid JSON"):
        load_catalog(path)


def test_load_catalog_empty_array(tmp_path: Path):
    path = tmp_path / "empty.json"
    path.write_text("[]", encoding="utf-8")
    with pytest.raises(CatalogLoadError, match="empty"):
        load_catalog(path)


def test_load_catalog_duplicate_ids(tmp_path: Path):
    path = tmp_path / "dup.json"
    path.write_text(
        json.dumps(
            [
                {"virtual_agent_id": 1, "virtual_agent_name": "A", "is_default": False},
                {"virtual_agent_id": 1, "virtual_agent_name": "B", "is_default": False},
            ]
        ),
        encoding="utf-8",
    )
    with pytest.raises(CatalogLoadError, match="Duplicate"):
        load_catalog(path)


def test_load_catalog_multiple_defaults(tmp_path: Path):
    path = tmp_path / "defaults.json"
    path.write_text(
        json.dumps(
            [
                {"virtual_agent_id": 1, "virtual_agent_name": "A", "is_default": True},
                {"virtual_agent_id": 2, "virtual_agent_name": "B", "is_default": True},
            ]
        ),
        encoding="utf-8",
    )
    with pytest.raises(CatalogLoadError, match="more than one"):
        load_catalog(path)


def test_load_catalog_invalid_structure(tmp_path: Path):
    path = tmp_path / "invalid.json"
    path.write_text(json.dumps({"virtual_agent_id": 1}), encoding="utf-8")
    with pytest.raises(CatalogLoadError, match="JSON array"):
        load_catalog(path)
