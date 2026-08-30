# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

from abc import ABC, abstractmethod
from typing import Any, AsyncIterator, Dict, Optional
from .events import AgentCapabilities, AgentEvent

class AgentAdapter(ABC):
    @abstractmethod
    async def capabilities(self) -> AgentCapabilities:
        """Return the capabilities of this adapter."""
        pass

    @abstractmethod
    async def create_session(self, config: Dict[str, Any]) -> str:
        """Create a new session and return the session ID."""
        pass

    @abstractmethod
    async def send(self, session_id: str, message: Any) -> None:
        """Send a message to the agent session."""
        pass

    @abstractmethod
    async def events(self, session_id: str) -> AsyncIterator[AgentEvent]:
        """Iterate over events from the agent session."""
        pass

    @abstractmethod
    async def approve(self, session_id: str, call_id: str, result: Any = None) -> None:
        """Approve a pending tool request."""
        pass

    @abstractmethod
    async def reject(self, session_id: str, call_id: str, reason: str) -> None:
        """Reject a pending tool request."""
        pass

    @abstractmethod
    async def interrupt(self, session_id: str) -> None:
        """Interrupt the agent session."""
        pass

    @abstractmethod
    async def terminate(self, session_id: str) -> None:
        """Terminate the agent session."""
        pass
