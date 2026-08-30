# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

from daedalus.adapters.base import AgentAdapter
from daedalus.adapters.events import SessionEnded
from daedalus.kairos.worktree import GitWorktreeManager

@dataclass
class CandidateBranch:
    """Represents a completed task on a dedicated git branch."""
    branch_name: str
    worktree_path: Path
    task: str
    completed: bool = False
    error: Optional[str] = None
    score: float = 0.0

class ShadowShellManager:
    """
    Spawns an adapter and runs the agent inside a given GitWorktree.
    """
    def __init__(
        self,
        worktree_manager: GitWorktreeManager,
        adapter: AgentAdapter,
        base_commit: str,
        config: Dict[str, Any]
    ):
        self.worktree_manager = worktree_manager
        self.adapter = adapter
        self.base_commit = base_commit
        self.config = config

    async def run_task(self, task: str, branch_prefix: str = "candidate") -> CandidateBranch:
        """
        Executes the agent task inside a new worktree and returns a CandidateBranch.
        """
        branch_name = f"{branch_prefix}-{uuid.uuid4().hex[:8]}"
        worktree_path = self.worktree_manager.create_worktree(self.base_commit, branch_name)
        
        candidate = CandidateBranch(
            branch_name=branch_name, 
            worktree_path=worktree_path, 
            task=task
        )
        
        # The task is the initial one-shot prompt.  Crucially, ``cwd`` is the
        # worktree, and the adapter is required to honor it at process launch.
        session_config = dict(self.config)
        session_config['cwd'] = str(worktree_path)
        session_config['prompt'] = task
        
        session_id = await self.adapter.create_session(session_config)

        try:
            exit_event = None
            async for event in self.adapter.events(session_id):
                if isinstance(event, SessionEnded):
                    exit_event = event

            if exit_event is None:
                raise RuntimeError("agent session ended without a process result")
            if exit_event.exit_code != 0:
                detail = exit_event.stderr.strip() or "no stderr"
                raise RuntimeError(
                    f"agent exited with code {exit_event.exit_code}: {detail}"
                )
            if not self.worktree_manager.has_changes(worktree_path):
                raise RuntimeError("agent completed without changing the candidate worktree")
            
            # Commit any changes the agent made in the worktree
            self.worktree_manager.commit_candidate(
                worktree_path, 
                f"Shadow shell output for task: {task}"
            )
            candidate.completed = True
            
        except Exception as e:
            candidate.error = str(e)
            candidate.completed = False
        finally:
            try:
                await self.adapter.terminate(session_id)
            finally:
                if not candidate.completed:
                    self.worktree_manager.cleanup_worktree(worktree_path)
            
        return candidate
