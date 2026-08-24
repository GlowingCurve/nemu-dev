from __future__ import annotations

import argparse
from pathlib import Path

import pytest

from explog.cli import build_parser, main


def _subcommands(parser: argparse.ArgumentParser) -> dict[str, argparse.ArgumentParser]:
    action = next(
        action
        for action in parser._actions
        if isinstance(action, argparse._SubParsersAction)
    )
    return action.choices


def test_parser_has_required_fixed_subcommands() -> None:
    parser = build_parser()

    assert set(_subcommands(parser)) == {"run", "init", "list"}
    with pytest.raises(SystemExit) as error:
        parser.parse_args([])
    assert error.value.code == 2


def test_help_lists_all_subcommands(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as error:
        main(["--help"])

    assert error.value.code == 0
    output = capsys.readouterr().out
    assert "run" in output
    assert "init" in output
    assert "list" in output


def test_run_parser_preserves_fixed_options() -> None:
    run_parser = _subcommands(build_parser())["run"]
    option_strings = {
        option for action in run_parser._actions for option in action.option_strings
    }

    assert option_strings == {
        "-h",
        "--help",
        "--config",
        "--log",
        "--message",
        "--parent-id",
        "--id",
    }


def test_init_and_list_parsers_have_defaults() -> None:
    subcommands = _subcommands(build_parser())

    init_arguments = subcommands["init"].parse_args([])
    list_arguments = subcommands["list"].parse_args([])
    assert init_arguments.config == Path("explog.toml")
    assert init_arguments.log == Path("experiments.jsonl")
    assert list_arguments.log == Path("experiments.jsonl")


def test_legacy_run_invocation_is_rejected(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as error:
        main(
            [
                "--config",
                "explog.toml",
                "--log",
                "experiments.jsonl",
                "--message",
                "legacy",
            ]
        )

    assert error.value.code == 2
    assert "invalid choice" in capsys.readouterr().err


def test_cli_reports_expected_run_error(
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = main(
        [
            "run",
            "--config",
            "missing.toml",
            "--log",
            "log.jsonl",
            "--message",
            "test",
        ]
    )

    assert exit_code == 1
    assert "explog: error:" in capsys.readouterr().err


def test_cli_run_prints_only_node_id(
    git_repo: Path,
    config_file: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(git_repo)

    exit_code = main(
        [
            "run",
            "--config",
            str(config_file),
            "--log",
            "experiments.jsonl",
            "--message",
            "test",
            "--id",
            "chosen-id",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert captured.out == "chosen-id\n"
    assert captured.err == ""


def test_cli_initializes_with_defaults(
    git_repo: Path,
    config_file: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(git_repo)

    exit_code = main(["init"])

    assert exit_code == 0
    assert (git_repo / "experiments.jsonl").read_bytes() == b""
    assert (git_repo / "experiment-data").is_dir()
    output = capsys.readouterr().out
    assert "explog environment is ready" in output
    assert f"Config: {config_file}" in output
