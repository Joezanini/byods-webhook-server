"""SDK compatibility layer until webex-byova>=0.3.0 ships native catalog support.

Extends the SDK VoiceVirtualAgentService to return configured agents, dispatch
list_virtual_agents events, and enrich session_start metadata with virtual_agent_id.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING, Any

import grpc

from webex_byova.exceptions import AuthenticationError
from webex_byova.media._internal import grpc_service as grpc_service_module
from webex_byova.media._internal.generated import byova_common_pb2, voicevirtualagent_pb2
from webex_byova.media._internal.grpc_service import (
    VoiceVirtualAgentService,
    _DTMF_MAP,
    _struct_to_dict,
)
from webex_byova.media._internal.generated.voicevirtualagent_pb2_grpc import (
    add_VoiceVirtualAgentServicer_to_server,
)
from webex_byova.media.events import (
    AudioInputEvent,
    DtmfInputEvent,
    SessionEndEvent,
    SessionStartEvent,
)
from webex_byova.media.exceptions import DuplicateTurnStreamError
from webex_byova.media.session import MediaSession, TurnContext

from src.byova.catalog import VirtualAgentCatalogEntry
from src.byova.events import ListVirtualAgentsEvent

if TYPE_CHECKING:
    from webex_byova.media.server import BYOVAMediaServer

logger = logging.getLogger(__name__)

_PATCH_APPLIED = False


def sdk_supports_native_catalog() -> bool:
    """Return True when the installed SDK exposes MediaServerConfig.virtual_agents."""
    try:
        from webex_byova.media.config import MediaServerConfig

        return "virtual_agents" in MediaServerConfig.model_fields
    except Exception:
        return False


def _enrich_session_metadata(
    metadata: dict[str, Any], request: voicevirtualagent_pb2.VoiceVARequest
) -> dict[str, Any]:
    enriched = dict(metadata)
    if request.virtual_agent_id:
        enriched["virtual_agent_id"] = request.virtual_agent_id
    if request.customer_org_id:
        enriched["customer_org_id"] = request.customer_org_id
    return enriched


async def _dispatch_list_virtual_agents(
    server: BYOVAMediaServer, event: ListVirtualAgentsEvent
) -> None:
    """Invoke list_virtual_agents handlers without a media session."""
    handlers = server._handlers.get("list_virtual_agents", [])  # noqa: SLF001
    for fn in handlers:
        sig = inspect.signature(fn)
        kwargs: dict[str, Any] = {}
        for name in sig.parameters:
            if name in {"event", "evt"}:
                kwargs[name] = event
        if inspect.iscoroutinefunction(fn):
            await fn(**kwargs)
        else:
            await asyncio.to_thread(fn, **kwargs)


class CatalogVoiceVirtualAgentService(VoiceVirtualAgentService):
    """SDK servicer subclass that serves the configured virtual agent catalog."""

    async def ListVirtualAgents(  # noqa: N802
        self,
        request: byova_common_pb2.ListVARequest,
        context: grpc.aio.ServicerContext,
    ) -> byova_common_pb2.ListVAResponse:
        if self._config.verify_tokens:
            await self._verify_context(context)

        catalog: list[VirtualAgentCatalogEntry] = getattr(
            self._server, "_virtual_agent_catalog", []
        )
        response = byova_common_pb2.ListVAResponse()
        agent_names: list[str] = []

        for entry in catalog:
            info = response.virtual_agents.add()
            info.virtual_agent_id = entry.virtual_agent_id
            info.virtual_agent_name = entry.virtual_agent_name
            info.is_default = entry.is_default
            agent_names.append(entry.virtual_agent_name)

        invocation_metadata = dict(context.invocation_metadata())
        tracking_id = invocation_metadata.get("trackingid")

        event = ListVirtualAgentsEvent(
            customer_org_id=request.customer_org_id or None,
            is_default_virtual_agent_enabled=request.is_default_virtual_agent_enabled,
            agent_count=len(catalog),
            agent_names=agent_names,
            tracking_id=tracking_id,
        )
        await _dispatch_list_virtual_agents(self._server, event)

        return response

    async def ProcessCallerInput(  # noqa: N802
        self,
        request_iterator: AsyncIterator[voicevirtualagent_pb2.VoiceVARequest],
        context: grpc.aio.ServicerContext,
    ) -> AsyncIterator[voicevirtualagent_pb2.VoiceVAResponse]:
        """Handle ProcessCallerInput with virtual_agent_id in session_start metadata."""
        import uuid

        stream_id = str(uuid.uuid4())
        conversation_id = ""
        turn: TurnContext | None = None
        session: MediaSession | None = None
        response_queue: asyncio.Queue[voicevirtualagent_pb2.VoiceVAResponse | None] = (
            asyncio.Queue()
        )

        async def send_response(response: voicevirtualagent_pb2.VoiceVAResponse) -> None:
            await response_queue.put(response)

        async def close_stream() -> None:
            await response_queue.put(None)

        async def request_reader() -> None:
            nonlocal conversation_id, turn, session
            first_audio = True
            try:
                if self._config.verify_tokens:
                    await self._verify_context(context)

                async for request in request_iterator:
                    conversation_id = request.conversation_id or conversation_id
                    if not conversation_id:
                        continue

                    await self._store.register_stream(conversation_id, stream_id)

                    if request.HasField("event_input"):
                        event = request.event_input
                        if event.event_type == byova_common_pb2.EventInput.SESSION_START:
                            metadata = _enrich_session_metadata(
                                _struct_to_dict(event.parameters), request
                            )
                            session = await self._store.get_or_create(
                                conversation_id,
                                MediaSession,
                                config=self._config,
                                server=self._server,
                                metadata=metadata,
                            )
                            turn_number = session.turn_count + 1
                            turn = TurnContext(
                                session=session,
                                config=self._config,
                                send_response=send_response,
                                close_stream=close_stream,
                                turn_number=turn_number,
                            )
                            session.bind_turn(turn)
                            await self._turn_manager.start_turn(session, turn)
                            await self._server._dispatch_event(  # noqa: SLF001
                                "session_start",
                                SessionStartEvent(
                                    conversation_id=conversation_id,
                                    metadata=metadata,
                                ),
                                session,
                                turn,
                            )
                        elif event.event_type == byova_common_pb2.EventInput.SESSION_END:
                            if session and turn:
                                await self._server._dispatch_event(  # noqa: SLF001
                                    "session_end",
                                    SessionEndEvent(reason="webex_terminate"),
                                    session,
                                    turn,
                                )
                            await self._store.release_session(conversation_id)
                            return
                        elif event.event_type == byova_common_pb2.EventInput.NO_INPUT:
                            if turn:
                                self._turn_manager.cancel_no_input_timer(turn)

                    elif request.HasField("audio_input") and session and turn:
                        audio = request.audio_input
                        self._turn_manager.cancel_no_input_timer(turn)
                        await self._turn_manager.on_inbound_audio(
                            session, turn, is_first=first_audio
                        )
                        first_audio = False
                        audio_event = AudioInputEvent(
                            audio=audio.caller_audio,
                            encoding="mulaw",
                            sample_rate=audio.sample_rate_hertz or self._config.sample_rate,
                        )
                        await self._server._dispatch_event(  # noqa: SLF001
                            "audio_input", audio_event, session, turn
                        )
                        session._resolve_input(audio_event)

                    elif request.HasField("dtmf_input") and session and turn:
                        digits = "".join(
                            _DTMF_MAP.get(d, "") for d in request.dtmf_input.dtmf_events
                        )
                        if digits:
                            dtmf_event = DtmfInputEvent(digits=digits)
                            await self._server._dispatch_event(  # noqa: SLF001
                                "dtmf_input", dtmf_event, session, turn
                            )
                            session._resolve_input(dtmf_event)

            except DuplicateTurnStreamError:
                context.set_code(grpc.StatusCode.ALREADY_EXISTS)
                context.set_details("Duplicate turn stream")
            except AuthenticationError:
                context.set_code(grpc.StatusCode.UNAUTHENTICATED)
                context.set_details("Invalid token")
            except Exception as exc:
                logger.exception("ProcessCallerInput failed")
                if session and turn:
                    await self._server._handle_handler_error(exc, session, turn)  # noqa: SLF001
            finally:
                if conversation_id:
                    await self._store.unregister_stream(conversation_id, stream_id)
                await response_queue.put(None)

        reader_task = asyncio.create_task(request_reader())

        try:
            while True:
                response = await response_queue.get()
                if response is None:
                    break
                yield response
        finally:
            reader_task.cancel()
            try:
                await reader_task
            except asyncio.CancelledError:
                pass


def _patched_register_service(grpc_server: grpc.aio.Server, media_server: BYOVAMediaServer) -> None:
    add_VoiceVirtualAgentServicer_to_server(  # type: ignore[no-untyped-call]
        CatalogVoiceVirtualAgentService(media_server),
        grpc_server,
    )


def apply_sdk_catalog_patch() -> None:
    """Patch SDK gRPC registration to use catalog-aware servicer (no-op when native support exists)."""
    global _PATCH_APPLIED
    if _PATCH_APPLIED or sdk_supports_native_catalog():
        return
    grpc_service_module.register_service = _patched_register_service
    # BYOVAMediaServer imports register_service at module load — update that binding too.
    import webex_byova.media.server as media_server_module

    media_server_module.register_service = _patched_register_service
    _PATCH_APPLIED = True
    logger.debug("Applied virtual agent catalog patch for webex-byova <0.3.0")
