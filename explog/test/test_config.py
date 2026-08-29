from pathlib import Path

import pytest

from explog.config import Config, load_config
from explog.errors import ConfigError


def test_load_config(tmp_path: Path) -> None:
    config_path = tmp_path / "explog.toml"
    config_path.write_text(
        "\n".join(
            [
                'log = "experiments.jsonl"',
                'data_root = "data"',
                'experiment_scripts = [["python3", "run.py"]]',
                'data_processing_scripts = [["python3", "process.py", "--fast"]]',
            ]
        ),
        encoding="utf-8",
    )

    assert load_config(config_path) == Config(
        log=Path("experiments.jsonl"),
        data_root=Path("data"),
        experiment_scripts=(("python3", "run.py"),),
        data_processing_scripts=(("python3", "process.py", "--fast"),),
    )


@pytest.mark.parametrize(
    "content,match",
    [
        (
            'data_root = "data"\nexperiment_scripts = []\n',
            "missing config key",
        ),
        (
            'log = "experiments.jsonl"\ndata_root = "data"\n'
            "experiment_scripts = []\n",
            "missing config key",
        ),
        (
            'log = "experiments.jsonl"\ndata_root = "data"\n'
            'experiment_scripts = []\ndata_processing_scripts = []\nextra = true\n',
            "unknown config key",
        ),
        (
            'log = ""\ndata_root = "data"\n'
            "experiment_scripts = []\ndata_processing_scripts = []\n",
            "log must be a non-empty string",
        ),
        (
            'log = "experiments.jsonl"\ndata_root = "data"\n'
            'experiment_scripts = ["python3"]\ndata_processing_scripts = []\n',
            "non-empty argv array",
        ),
        (
            'log = "experiments.jsonl"\ndata_root = "data"\n'
            "experiment_scripts = [[1]]\ndata_processing_scripts = []\n",
            "arguments must all be strings",
        ),
    ],
)
def test_reject_invalid_config(tmp_path: Path, content: str, match: str) -> None:
    config_path = tmp_path / "explog.toml"
    config_path.write_text(content, encoding="utf-8")

    with pytest.raises(ConfigError, match=match):
        load_config(config_path)
