# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

import pytest
import asyncio
from pathlib import Path
from unittest.mock import MagicMock

from daedalus.kairos.shadow_shell import ShadowShellManager, CandidateBranch
from daedalus.kairos.evolution import EvolutionaryOrchestrator
from daedalus.adapters.base import AgentAdapter
from daedalus.adapters.events import SessionEnded

class DummyAdapter(AgentAdapter):
    async def capabilities(self):
        pass

    async def create_session(self, config):
        return "dummy_session"

    async def send(self, session_id, message):
        pass

    async def events(self, session_id):
        yield SessionEnded(session_id=session_id, exit_code=0)

    async def approve(self, session_id, call_id, result=None): pass
    async def reject(self, session_id, call_id, reason): pass
    async def interrupt(self, session_id): pass
    async def terminate(self, session_id): pass

@pytest.fixture
def mock_worktree_manager():
    manager = MagicMock()
    manager.create_worktree.return_value = Path("/fake/worktree")
    manager.commit_candidate.return_value = None
    manager.has_changes.return_value = True
    return manager

@pytest.fixture
def mock_adapter():
    return DummyAdapter()

@pytest.mark.asyncio
async def test_shadow_shell_manager(mock_worktree_manager, mock_adapter):
    manager = ShadowShellManager(
        worktree_manager=mock_worktree_manager,
        adapter=mock_adapter,
        base_commit="HEAD",
        config={}
    )
    
    candidate = await manager.run_task("do some refactoring")
    
    assert candidate.task == "do some refactoring"
    assert candidate.completed is True
    assert candidate.error is None
    assert candidate.worktree_path == Path("/fake/worktree")
    assert candidate.branch_name.startswith("candidate-")
    
    mock_worktree_manager.create_worktree.assert_called_once_with("HEAD", candidate.branch_name)
    mock_worktree_manager.has_changes.assert_called_once_with(candidate.worktree_path)
    mock_worktree_manager.commit_candidate.assert_called_once()

@pytest.mark.asyncio
async def test_evolution_generate(mock_worktree_manager, mock_adapter):
    def factory():
        return ShadowShellManager(
            worktree_manager=mock_worktree_manager,
            adapter=mock_adapter,
            base_commit="HEAD",
            config={}
        )
        
    orchestrator = EvolutionaryOrchestrator(shell_manager_factory=factory)
    
    candidates = await orchestrator.generate_candidates("task", population_size=3)
    
    assert len(candidates) == 3
    assert all(c.completed for c in candidates)
    assert mock_worktree_manager.create_worktree.call_count == 3

def test_evolution_select():
    orchestrator = EvolutionaryOrchestrator(shell_manager_factory=lambda: None)
    
    c1 = CandidateBranch(branch_name="c1", worktree_path=Path(""), task="t", completed=True, score=50.0)
    c2 = CandidateBranch(branch_name="c2", worktree_path=Path(""), task="t", completed=True, score=100.0)
    c3 = CandidateBranch(branch_name="c3", worktree_path=Path(""), task="t", completed=True, score=10.0)
    c4 = CandidateBranch(branch_name="c4", worktree_path=Path(""), task="t", completed=False, score=100.0)
    
    best = orchestrator.select_best([c1, c2, c3, c4])
    assert best == c2


def test_evolution_never_selects_a_failing_candidate():
    orchestrator = EvolutionaryOrchestrator(shell_manager_factory=lambda: None)
    failed = CandidateBranch(
        branch_name="failed",
        worktree_path=Path(""),
        task="t",
        completed=True,
        score=10.0,
        error="tests failed",
    )

    assert orchestrator.select_best([failed]) is None
