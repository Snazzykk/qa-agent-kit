"""GraphIndexer — one-shot .index(root) + incremental .refresh().

This is the only place a full walk of the SUT happens. Every downstream
query goes through GraphQueryClient instead of touching the filesystem.
"""
from __future__ import annotations

import subprocess
import time
from pathlib import Path
from typing import Self

import allure

from tests.framework.codegraph.graph_provider import GraphProvider


class GraphIndexer:
    """Build or refresh the code graph for a given SUT root.

    Typical usage:

        provider = CodeGraphContextProvider().ensure_installed()
        GraphIndexer(provider).index(Path("/Users/me/Code/my-saas"))

    After a `git pull`:

        GraphIndexer(provider).refresh(root, since="HEAD~1")
    """

    def __init__(self, provider: GraphProvider) -> None:
        self._provider = provider
        self._last_indexed_at: float | None = None
        self._last_root: Path | None = None

    # --------------------------------------------------------------- one-shot
    @allure.step("GraphIndexer.index({root})")
    def index(self, root: Path) -> Self:
        if not root.exists():
            raise FileNotFoundError(root)
        self._provider.ensure_installed()
        started = time.monotonic()
        self._provider.index(root)
        self._last_indexed_at = time.monotonic()
        self._last_root = root
        elapsed = self._last_indexed_at - started
        allure.attach(
            f"provider={self._provider.name} root={root} elapsed={elapsed:.1f}s",
            name="index-summary",
            attachment_type=allure.attachment_type.TEXT,
        )
        return self

    # ------------------------------------------------------------- incremental
    @allure.step("GraphIndexer.refresh({root}, since={since})")
    def refresh(self, root: Path, since: str = "HEAD~1") -> Self:
        if not root.exists():
            raise FileNotFoundError(root)
        self._provider.ensure_installed()
        changed_files = self._changed_files(root, since)
        if not changed_files:
            # Nothing to do — graph is already fresh.
            return self
        self._provider.refresh(root, since=since)
        self._last_indexed_at = time.monotonic()
        self._last_root = root
        allure.attach(
            "\n".join(str(f) for f in changed_files),
            name=f"refresh-files ({len(changed_files)})",
            attachment_type=allure.attachment_type.TEXT,
        )
        return self

    # -------------------------------------------------------------- freshness
    def is_stale(self, max_age_seconds: float = 3600.0) -> bool:
        if self._last_indexed_at is None:
            return True
        return (time.monotonic() - self._last_indexed_at) > max_age_seconds

    # ----------------------------------------------------------------- helpers
    @staticmethod
    def _changed_files(root: Path, since: str) -> list[Path]:
        """Git-diff file list between `since` and HEAD. Returns absolute paths."""
        try:
            proc = subprocess.run(
                ["git", "-C", str(root), "diff", "--name-only", since, "HEAD"],
                check=True,
                capture_output=True,
                text=True,
            )
        except (subprocess.CalledProcessError, FileNotFoundError):
            return []
        return [
            root / line.strip()
            for line in proc.stdout.splitlines()
            if line.strip()
        ]
