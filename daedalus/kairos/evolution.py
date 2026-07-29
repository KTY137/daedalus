import asyncio
import sys
from typing import List, Callable, Optional, Dict, Any
from pathlib import Path
import logging

from daedalus.kairos.shadow_shell import ShadowShellManager, CandidateBranch

logger = logging.getLogger(__name__)

# Wall-clock ceiling for ONE candidate's test run. Without it a candidate that
# hangs -- an agent that left an input() or an unbounded loop in the tree --
# blocks the whole `gather` below forever, and the run has no way to end.
DEFAULT_EVAL_TIMEOUT_S = 600.0

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

    async def evaluate_candidates(
        self,
        candidates: List[CandidateBranch],
        timeout_s: float = DEFAULT_EVAL_TIMEOUT_S,
    ) -> None:
        """
        Evaluates candidates using pytest concurrently. Populates candidate.score and candidate.error.

        THE INTERPRETER IS PART OF THE MEASUREMENT. This shells out to
        ``sys.executable -m pytest``, never to a bare ``pytest``, and the
        difference is not cosmetic -- it decides WHICH TREE gets scored.

        MEASURED 2026-07-29, running the same test file two ways inside a
        worktree that shadows ``daedalus/``:

            bare `pytest`          -> daedalus resolved to the PRIMARY checkout
            `python -m pytest`     -> daedalus resolved to the WORKTREE copy

        The editable install pins ``daedalus`` to the primary checkout by
        absolute path via an ``_EditableFinder`` on ``sys.meta_path``. Bare
        ``pytest`` puts only each test file's own basedir on ``sys.path``, never
        the worktree root, so nothing shadows that finder and the candidate's
        edits are invisible to its own tests. ``-m`` puts the working directory
        on ``sys.path[0]``, ahead of ``PathFinder``, which is ahead of
        ``_EditableFinder`` -- so the candidate's code wins, as it must.

        Until this changed, every score this class produced described the
        primary checkout's code running the candidate's tests.

        This is still a BINARY, whole-suite signal and it is still not a
        promotion boundary -- see ``docs/adrs/015-ariadne-preconditions.md``.
        The stronger measurement (``daedalus.eval.correctness.evaluate_change``,
        which freezes the selection before candidate code runs and reports five
        outcomes with precedence) is the intended replacement; this fix makes
        the interim signal describe the right tree, nothing more.
        """
        async def evaluate_single(candidate: CandidateBranch):
            if not candidate.completed or candidate.error:
                candidate.score = -1.0
                return

            process = None
            try:
                # Run pytest inside the worktree asynchronously. `-m` is
                # load-bearing: see the docstring.
                process = await asyncio.create_subprocess_exec(
                    sys.executable, "-m", "pytest",
                    cwd=str(candidate.worktree_path),
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(), timeout=timeout_s)

                if process.returncode == 0:
                    candidate.score = 100.0
                else:
                    candidate.score = 0.0
                    combined = (stdout + b"\n" + stderr).decode(errors="replace")
                    candidate.error = f"Tests failed. Output: {combined[-4000:]}"
            except asyncio.TimeoutError:
                # A hung candidate is a FAILED candidate, never an unscored one
                # left to block the gather. Kill it and say why.
                candidate.score = 0.0
                candidate.error = f"Evaluation timed out after {timeout_s}s"
                if process is not None:
                    try:
                        process.kill()
                        await process.wait()
                    except ProcessLookupError:
                        pass
                logger.error(
                    f"Evaluation of candidate {candidate.branch_name} timed out")
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
