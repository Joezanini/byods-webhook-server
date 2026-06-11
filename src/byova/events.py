"""Application-level BYOVA events not yet exported by the SDK."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field


class ListVirtualAgentsEvent(BaseModel):
    """Fired when Flow Designer or WxCC requests the virtual agent catalog."""

    type: Literal["list_virtual_agents"] = "list_virtual_agents"
    customer_org_id: str | None = None
    is_default_virtual_agent_enabled: bool = False
    agent_count: int = 0
    agent_names: list[str] = Field(default_factory=list)
    tracking_id: str | None = None
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
