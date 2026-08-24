from __future__ import annotations

import tomllib
from pathlib import Path

import explog
from explog.model import ExperimentNode as ModelExperimentNode
from explog.workflow import ExperimentNode as WorkflowExperimentNode


def test_package_and_project_versions_are_0_2_0() -> None:
    pyproject = Path(__file__).parents[1] / "pyproject.toml"
    metadata = tomllib.loads(pyproject.read_text(encoding="utf-8"))["project"]

    assert explog.__version__ == "0.2.0"
    assert metadata["version"] == "0.2.0"


def test_experiment_node_remains_available_from_public_locations() -> None:
    assert explog.ExperimentNode is ModelExperimentNode
    assert WorkflowExperimentNode is ModelExperimentNode
