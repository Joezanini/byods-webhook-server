"""Load and validate the virtual agent catalog for Flow Designer discovery."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


class CatalogLoadError(Exception):
    """Raised when the virtual agent catalog cannot be loaded or validated."""


@dataclass(frozen=True)
class VirtualAgentCatalogEntry:
    """One agent advertised to Webex Contact Center Flow Designer."""

    virtual_agent_id: str
    virtual_agent_name: str
    is_default: bool = False



def validate_catalog_entries(entries: list[VirtualAgentCatalogEntry]) -> None:
    """Validate aggregate catalog rules (≥1 agent, unique ids, ≤1 default)."""
    if not entries:
        raise CatalogLoadError(
            "Catalog is empty. At least one virtual agent is required."
        )

    seen_ids: set[str] = set()
    default_count = 0
    for entry in entries:
        if not entry.virtual_agent_id.strip():
            raise CatalogLoadError("virtual_agent_id must be non-empty.")
        if not entry.virtual_agent_name.strip():
            raise CatalogLoadError(
                f"virtual_agent_id '{entry.virtual_agent_id}' has an empty virtual_agent_name."
            )
        if entry.virtual_agent_id in seen_ids:
            raise CatalogLoadError(
                f"Duplicate virtual_agent_id '{entry.virtual_agent_id}' in catalog."
            )
        seen_ids.add(entry.virtual_agent_id)
        if entry.is_default:
            default_count += 1

    if default_count > 1:
        raise CatalogLoadError(
            "Catalog marks more than one agent as is_default=true. "
            "At most one default agent is allowed."
        )


def _parse_catalog_item(item: dict, *, source: str) -> VirtualAgentCatalogEntry:
    agent_id_raw = item.get("virtual_agent_id")
    agent_name = item.get("virtual_agent_name")
    is_default = bool(item.get("is_default", False))

    if agent_id_raw is None:
        raise CatalogLoadError(f"Catalog entry in {source} is missing virtual_agent_id.")

    agent_id = str(agent_id_raw).strip()
    if not agent_id:
        raise CatalogLoadError(f"Catalog entry in {source} has an empty virtual_agent_id.")

    if not isinstance(agent_name, str) or not agent_name.strip():
        raise CatalogLoadError(
            f"Catalog entry '{agent_id}' in {source} has an empty virtual_agent_name."
        )

    return VirtualAgentCatalogEntry(
        virtual_agent_id=agent_id,
        virtual_agent_name=agent_name.strip(),
        is_default=is_default,
    )


def load_catalog(path: str | Path) -> list[VirtualAgentCatalogEntry]:
    """Load, validate, and return catalog entries from a JSON file."""
    catalog_path = Path(path)
    if not catalog_path.is_file():
        raise CatalogLoadError(
            f"Catalog file not found: {catalog_path}. "
            "Copy config/virtual_agents.json or set WEBEX_VIRTUAL_AGENTS_CONFIG."
        )

    try:
        raw = json.loads(catalog_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise CatalogLoadError(f"Invalid JSON in catalog file {catalog_path}: {exc}") from exc

    if not isinstance(raw, list):
        raise CatalogLoadError(
            f"Catalog file {catalog_path} must contain a JSON array of agent objects."
        )

    entries = [
        _parse_catalog_item(item, source=str(catalog_path))
        for item in raw
        if isinstance(item, dict)
    ]
    if len(entries) != len(raw):
        raise CatalogLoadError(
            f"Catalog file {catalog_path} contains invalid entry types."
        )

    validate_catalog_entries(entries)
    return entries


def catalog_id_set(entries: list[VirtualAgentCatalogEntry]) -> set[str]:
    """Return the set of agent identifiers for membership checks at session start."""
    return {entry.virtual_agent_id for entry in entries}
