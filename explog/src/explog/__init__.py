"""Git-aware experiment logging."""

from explog.model import ExperimentNode
from explog.workflow import run_experiment

__all__ = ["ExperimentNode", "run_experiment"]
__version__ = "0.2.0"
