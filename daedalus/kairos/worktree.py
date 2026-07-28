import hashlib
import os
import subprocess
import shutil
import tempfile
from pathlib import Path
from typing import Optional

from daedalus.storage import require_storage


def _worktree_root_for(repo_path: Path) -> Path:
    """Resolve the root directory that holds candidate worktrees for a repo.

    Worktrees must live OUTSIDE the primary checkout so they never pollute
    ``git status`` or whole-repo snapshot attribution. Placement, in order:

    1. ``DAEDALUS_WORKTREE_ROOT`` env override (still namespaced per repo).
    2. ``%LOCALAPPDATA%/daedalus/worktrees``.
    3. ``tempfile.gettempdir()/daedalus/worktrees`` when LOCALAPPDATA is unset.

    Each repo gets its own subdirectory keyed by a short digest of the
    resolved repo path so distinct checkouts never collide.
    """
    override = os.environ.get('DAEDALUS_WORKTREE_ROOT')
    if override:
        base = Path(override)
    else:
        local_appdata = os.environ.get('LOCALAPPDATA')
        base_dir = Path(local_appdata) if local_appdata else Path(tempfile.gettempdir())
        base = base_dir / 'daedalus' / 'worktrees'
    digest = hashlib.sha256(str(repo_path).encode('utf-8')).hexdigest()[:12]
    return base / digest


class GitWorktreeManager:
    """Manages isolated Git worktrees for agent execution."""

    def __init__(self, repo_path: str | Path):
        self.repo_path = Path(repo_path).resolve()

    @property
    def worktree_root(self) -> Path:
        """Directory (outside the repo) where this repo's worktrees are placed."""
        return _worktree_root_for(self.repo_path)

    def _run_git(self, *args, cwd: Optional[Path] = None) -> str:
        """Executes a git command in the specified directory."""
        cmd = ['git'] + list(args)
        cwd_path = cwd or self.repo_path
        try:
            result = subprocess.run(
                cmd,
                cwd=cwd_path,
                capture_output=True,
                text=True,
                check=True
            )
            return result.stdout.strip()
        except subprocess.CalledProcessError as e:
            raise RuntimeError(f"Git command failed: {' '.join(cmd)}\nError: {e.stderr}")

    def create_worktree(self, base_commit: str, branch_name: str) -> Path:
        """
        Creates a new git worktree branching from a specific commit.

        Args:
            base_commit: The commit hash or reference to branch from.
            branch_name: The name of the new branch to create.

        Returns:
            The path to the new worktree.

        Raises:
            StorageUnavailable: If the worktree root volume is missing or below
                the free-space watermark (fail-closed; never spills elsewhere).
        """
        root = self.worktree_root
        worktree_path = root / branch_name
        worktree_path.parent.mkdir(parents=True, exist_ok=True)
        require_storage(str(worktree_path.parent))

        # Create a new branch and worktree
        self._run_git('worktree', 'add', '-b', branch_name, str(worktree_path), base_commit)

        return worktree_path

    def cleanup_worktree(self, path: str | Path) -> None:
        """
        Removes a git worktree and cleans up the directory.

        Args:
            path: The path to the worktree to remove.

        Raises:
            RuntimeError: If the worktree directory could not be removed. A
                failed removal is never swallowed silently.
        """
        path = Path(path).resolve()

        git_error: Optional[RuntimeError] = None
        try:
            # Force remove the worktree
            self._run_git('worktree', 'remove', '--force', str(path))
        except RuntimeError as e:
            # Git may no longer consider this a valid worktree; fall through to
            # direct directory removal, but keep the error for reporting.
            git_error = e

        if path.exists():
            try:
                shutil.rmtree(path)
            except OSError as e:
                detail = f"failed to remove worktree directory {path}: {e}"
                if git_error is not None:
                    detail += f" (git worktree remove also failed: {git_error})"
                raise RuntimeError(detail) from e

        if git_error is not None:
            # The directory is gone but git could not deregister it; prune the
            # stale registration (raises RuntimeError if pruning fails too).
            self._run_git('worktree', 'prune')

    def commit_candidate(self, path: str | Path, message: str, author: Optional[str] = None) -> None:
        """
        Commits all changes in the specified worktree.

        Args:
            path: The path to the worktree.
            message: The commit message.
            author: Optional author string (e.g., "Name <email>").
        """
        path = Path(path).resolve()

        # Stage all changes
        self._run_git('add', '-A', cwd=path)

        # Commit the changes
        commit_args = ['commit', '-m', message]
        if author:
            commit_args.extend(['--author', author])

        self._run_git(*commit_args, cwd=path)

    def has_changes(self, path: str | Path) -> bool:
        """Return whether the candidate worktree differs from its HEAD."""
        return bool(self._run_git("status", "--porcelain", cwd=Path(path).resolve()))
