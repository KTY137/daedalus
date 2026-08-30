"""Caller-owned lifecycle for a Hermes request and its Daedalus tool gateway."""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from .configuration import HermesRuntimeConfig
from .context_provider import ExplicitContextProvider
from .memory_provider import ReadOnlyMemoryProvider
from .runtime_adapter import HermesRuntimeRequest
from .tool_gateway import HermesToolGatewayServer
from .tool_provider import DaedalusToolProvider


@contextmanager
def hermes_runtime_session(
    *,
    tool_provider: DaedalusToolProvider,
    control_root: str | Path,
    workspace: str | Path,
    system_prompt: str,
    user_prompt: str,
    config: HermesRuntimeConfig,
    context: ExplicitContextProvider | None = None,
    memory: ReadOnlyMemoryProvider | None = None,
    cancellation_marker: str | Path | None = None,
) -> Iterator[HermesRuntimeRequest]:
    """Yield an authenticated-data request while the caller-owned gateway lives."""

    server = HermesToolGatewayServer(
        tool_provider,
        control_root=control_root,
        lifetime_seconds=min(86_400.0, config.sandbox.max_wall_seconds + 60.0),
    )
    descriptor = server.start(max_calls=config.sandbox.max_tool_calls)
    try:
        yield HermesRuntimeRequest(
            request_id=tool_provider.request_id,
            task_id=tool_provider.task_id,
            workspace=str(Path(workspace).expanduser().resolve(strict=True)),
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            config=config,
            context=context or ExplicitContextProvider(),
            memory=memory or ReadOnlyMemoryProvider(),
            tools=tool_provider.specifications,
            gateway=descriptor,
            cancellation_marker=(
                str(Path(cancellation_marker).expanduser().resolve(strict=False))
                if cancellation_marker
                else ""
            ),
        )
    finally:
        server.close()
