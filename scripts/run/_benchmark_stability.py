"""Shared convergence rules for MicroBench runner scripts."""

from __future__ import annotations

import math
import re
import statistics
import sys
from dataclasses import dataclass
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
# Runner helpers can also be imported or checked directly; expose shared helpers.
sys.path.insert(0, str(SCRIPT_DIR.parent))

from _common import ScriptError  # noqa: E402

MIN_RUNS = 15
MAX_RUNS = 125
WARMUP_RUNS = 5
RMOE_THRESHOLD_PERCENT = 1.0

NUMBER = r"[+-]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?"
SCORED_TIME_RE = re.compile(
    rf"(?im)^\s*Scored\s+time\s*[:=]\s*({NUMBER})\s*(ms|us|µs|s)\b"
)


@dataclass(frozen=True)
class RmoeStatistics:
    sample_count: int
    mean_ms: float
    rmoe99_percent: float


def extract_scored_time_ms(log_file: Path) -> float:
    """Extract one positive, finite Scored time value and convert it to ms."""
    try:
        text = log_file.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        raise ValueError(f"cannot read the log: {exc}") from exc

    matches = SCORED_TIME_RE.findall(text)
    if not matches:
        raise ValueError("Scored time was not found in the log")
    if len(matches) > 1:
        raise ValueError("multiple Scored time values were found in the log")

    value_text, unit = matches[0]
    value = float(value_text.replace(",", ""))
    factors = {"s": 1000.0, "ms": 1.0, "us": 0.001, "µs": 0.001}
    scored_time_ms = value * factors[unit.lower()]
    if not math.isfinite(scored_time_ms) or scored_time_ms <= 0:
        raise ValueError("Scored time must be a positive finite value")
    return scored_time_ms


def student_t_critical_99(sample_count: int) -> float:
    """Return the two-sided 99% Student's t critical value."""
    try:
        from scipy.stats import t
    except ImportError as exc:
        raise ScriptError(
            "Error: scipy is required for the 99% Student's t confidence interval.",
            2,
        ) from exc

    return float(t.ppf(0.995, sample_count - 1))


def calculate_rmoe99(values_ms: list[float]) -> RmoeStatistics:
    """Calculate two-sided 99% relative margin of error as a percentage."""
    sample_count = len(values_ms)
    if sample_count < 2:
        raise ValueError("at least two samples are required")

    mean_ms = statistics.fmean(values_ms)
    sample_stddev = statistics.stdev(values_ms)
    if mean_ms == 0:
        rmoe99 = math.inf
    else:
        rmoe99 = (
            student_t_critical_99(sample_count)
            * sample_stddev
            / math.sqrt(sample_count)
            / abs(mean_ms)
            * 100.0
        )

    return RmoeStatistics(
        sample_count=sample_count,
        mean_ms=mean_ms,
        rmoe99_percent=rmoe99,
    )


def calculate_after_warmup(scored_times_ms: list[float]) -> RmoeStatistics:
    if len(scored_times_ms) < MIN_RUNS:
        raise ValueError(f"at least {MIN_RUNS} valid runs are required")
    return calculate_rmoe99(scored_times_ms[WARMUP_RUNS:])


def rmoe_is_below_threshold(result: RmoeStatistics) -> bool:
    return result.rmoe99_percent < RMOE_THRESHOLD_PERCENT
