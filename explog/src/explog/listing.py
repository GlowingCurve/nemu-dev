from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from explog.errors import LogError
from explog.log import read_nodes
from explog.model import ExperimentNode


def _utc_timestamp(node: ExperimentNode) -> datetime:
    try:
        timestamp = datetime.fromisoformat(node.timestamp)
        offset = timestamp.utcoffset()
        if timestamp.tzinfo is None or offset is None:
            raise LogError(f"log record {node.id} has timestamp without timezone")
        return timestamp.astimezone(UTC)
    except LogError:
        raise
    except (OverflowError, TypeError, ValueError) as error:
        raise LogError(
            f"log record {node.id} has invalid ISO 8601 timestamp: {node.timestamp}"
        ) from error


def list_nodes(path: Path) -> list[ExperimentNode]:
    """Read nodes from an existing log and order them chronologically."""
    nodes = read_nodes(path, missing_ok=False)
    return sorted(nodes, key=_utc_timestamp)


def _escape_message(message: str) -> str:
    return message.replace("\r", "\\r").replace("\n", "\\n").replace("\t", "\\t")


def format_nodes(nodes: list[ExperimentNode]) -> str:
    """Format nodes as a compact, human-readable table."""
    if not nodes:
        return ""

    rows = [
        (
            node.timestamp,
            node.id,
            "-" if node.parent_id is None else node.parent_id,
            _escape_message(node.message),
        )
        for node in nodes
    ]
    headers = ("TIMESTAMP", "ID", "PARENT", "MESSAGE")
    widths = [
        max(len(headers[index]), *(len(row[index]) for row in rows))
        for index in range(3)
    ]

    def format_row(row: tuple[str, str, str, str]) -> str:
        return "  ".join(
            (
                row[0].ljust(widths[0]),
                row[1].ljust(widths[1]),
                row[2].ljust(widths[2]),
                row[3],
            )
        )

    return "\n".join((format_row(headers), *(format_row(row) for row in rows)))
