import asyncio
from typing import List, Callable, Optional, Dict, Any
from pathlib import Path
import logging

from daedalus.kairos.shadow_shell import ShadowShellManager, CandidateBranch

logger = logging.getLogger(__name__)

class EvolutionaryOrchestrator:
    """
    Experimental candidate runner: generate isolated branches, run a configured
    test command, and retain only a passing candidate.

    This is not autonomous code evolution and it is not a promotion boundary.
    A trusted verifier still has to inspect a candidate before it can be merged
    into the primary workspace.
    """
    def __init__(self, shell_manager_factory: Callable[[], ShadowShellManager]):
        self.shell_manager_factory = shell_manager_factory

    async def generate_candidates(self, task: str, population_size: int) -> List[CandidateBranch]:
        """
        Spawns N ShadowShellManager instances in parallel to attempt the task.
        """
        tasks = []
        for _ in range(population_size):
            manager = self.shell_manager_factory()
            tasks.append(manager.run_task(task))
            
        try:
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            valid_candidates = []
            for i, res in enumerate(results):
                if isinstance(res, CandidateBranch):
                    valid_candidates.append(res)
                elif isinstance(res, Exception):
                    logger.error(f"Task {i} failed with exception: {res}")
            return valid_candidates
        except Exception as e:
            logger.error(f"Error during candidate generation: {e}")
            return []

    async def evaluate_candidates(self, candidates: List[CandidateBranch]) -> None:
        """
        Evaluates candidates using pytest concurrently. Populates candidate.score and candidate.error.
        """
        async def evaluate_single(candidate: CandidateBranch):
            if not candidate.completed or candidate.error:
                candidate.score = -1.0
                return
                
            try:
                # Run pytest inside the worktree asynchronously
                process = await asyncio.create_subprocess_exec(
                    "pytest",
                    cwd=str(candidate.worktree_path),
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )
                stdout, stderr = await process.communicate()
                
                if process.returncode == 0:
                    candidate.score = 100.0
                else:
                    candidate.score = 0.0
                    combined = (stdout + b"\n" + stderr).decode(errors="replace")
                    candidate.error = f"Tests failed. Output: {combined[-4000:]}"
            except FileNotFoundError:
                candidate.score = 0.0
                candidate.error = "pytest not found"
            except Exception as e:
                candidate.score = 0.0
                candidate.error = f"Evaluation failed: {e}"
                logger.error(f"Evaluation of candidate {candidate.branch_name} failed: {e}")

        try:
            tasks = [evaluate_single(c) for c in candidates]
            await asyncio.gather(*tasks)
        except Exception as e:
            logger.error(f"Error evaluating candidates: {e}")

    def select_best(self, candidates: List[CandidateBranch]) -> Optional[CandidateBranch]:
        """
        Selects the best candidate based on the score.
        """
        if not candidates:
            return None
            
        valid = [
            c for c in candidates
            if c.completed and not c.error and c.score >= 100.0
        ]
        if not valid:
            return None
            
        # Sort by score in descending order
        valid.sort(key=lambda c: c.score, reverse=True)
        
        best = valid[0]
        return valid[0]
