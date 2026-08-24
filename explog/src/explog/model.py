from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ExperimentNode:
    id: str
    parent_id: str | None
    timestamp: str
    message: str
    git_commit: str
    git_diff_path: str
    data_dir: str
