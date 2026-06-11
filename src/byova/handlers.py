"""Event handlers for the SDK BYOVA media server."""

from __future__ import annotations

import logging

from typing import TYPE_CHECKING

from webex_byova.media.events import (
    AudioInputEvent,
    ErrorEvent,
    SessionEndEvent,
    SessionStartEvent,
    TurnEndedEvent,
    TurnStartedEvent,
)

from src.byova.catalog import catalog_id_set
from src.byova.events import ListVirtualAgentsEvent
from src.common.logging import log_event
from src.config.settings import Settings

if TYPE_CHECKING:
    from webex_byova.media import BYOVAMediaServer
    from webex_byova.media.session import MediaSession, TurnContext

logger = logging.getLogger("byods-webhook-server.media")


def register_handlers(server: "BYOVAMediaServer", settings: Settings) -> None:
    """Register structured logging and optional echo handlers on the media server."""
    catalog_ids = catalog_id_set(getattr(server, "_virtual_agent_catalog", []))

    @server.on("list_virtual_agents")
    async def on_list_virtual_agents(event: ListVirtualAgentsEvent) -> None:
        org = event.customer_org_id or "n/a"
        tracking = event.tracking_id or "n/a"
        log_event(
            logger,
            logging.INFO,
            (
                f"Flow Designer requested virtual agent list — org={org} "
                f"agents={event.agent_count} tracking_id={tracking}"
            ),
            operation="list_virtual_agents",
            outcome="success",
            org_id=event.customer_org_id,
            agent_count=event.agent_count,
            tracking_id=event.tracking_id,
            agent_names=event.agent_names,
        )

    @server.on("session_start")
    async def on_session_start(event: SessionStartEvent, session: "MediaSession") -> None:
        virtual_agent_id = event.metadata.get("virtual_agent_id")
        customer_org_id = event.metadata.get("customer_org_id")
        virtual_agent_id_str = str(virtual_agent_id) if virtual_agent_id else None

        log_event(
            logger,
            logging.INFO,
            (
                f"Media session started — conversation_id={event.conversation_id} "
                f"virtual_agent_id={virtual_agent_id_str or 'n/a'} "
                f"customer_org_id={customer_org_id or 'n/a'}"
            ),
            operation="media_session_start",
            outcome="success",
            conversation_id=event.conversation_id,
            session_id=session.session_id,
            org_id=str(customer_org_id) if customer_org_id else None,
            virtual_agent_id=virtual_agent_id_str,
        )

        if virtual_agent_id_str and virtual_agent_id_str not in catalog_ids:
            log_event(
                logger,
                logging.WARNING,
                (
                    f"virtual_agent_id={virtual_agent_id_str} not found in catalog — "
                    "session continues with catalog_match=false"
                ),
                operation="media_session_start",
                outcome="warning",
                conversation_id=event.conversation_id,
                session_id=session.session_id,
                virtual_agent_id=virtual_agent_id_str,
            )

    @server.on("turn_started")
    async def on_turn_started(
        event: TurnStartedEvent, session: "MediaSession", turn: "TurnContext"
    ) -> None:
        log_event(
            logger,
            logging.INFO,
            "Media turn started",
            operation="media_turn_started",
            outcome="success",
            conversation_id=session.conversation_id,
            session_id=session.session_id,
        )

    @server.on("audio_input")
    async def on_audio_input(
        event: AudioInputEvent, session: "MediaSession", turn: "TurnContext | None"
    ) -> None:
        log_event(
            logger,
            logging.DEBUG,
            "Inbound audio received",
            operation="media_audio_input",
            outcome="success",
            conversation_id=session.conversation_id,
            session_id=session.session_id,
        )
        if settings.media_echo_enabled and turn is not None and turn.is_active and event.audio:
            await turn.play_prompt(audio=event.audio)

    @server.on("turn_ended")
    async def on_turn_ended(
        event: TurnEndedEvent, session: MediaSession, turn: TurnContext
    ) -> None:
        log_event(
            logger,
            logging.INFO,
            f"Media turn ended: {event.reason}",
            operation="media_turn_ended",
            outcome="success",
            conversation_id=session.conversation_id,
            session_id=session.session_id,
        )

    @server.on("session_end")
    async def on_session_end(event: SessionEndEvent, session: MediaSession) -> None:
        log_event(
            logger,
            logging.INFO,
            f"Media session ended: {event.reason}",
            operation="media_session_end",
            outcome="success",
            conversation_id=session.conversation_id,
            session_id=session.session_id,
        )

    @server.on("error")
    async def on_error(
        event: ErrorEvent, session: MediaSession, turn: TurnContext | None
    ) -> None:
        log_event(
            logger,
            logging.ERROR,
            f"Media error: {event.code} {event.message}",
            operation="media_error",
            outcome="failure",
            conversation_id=session.conversation_id,
            session_id=session.session_id,
        )
