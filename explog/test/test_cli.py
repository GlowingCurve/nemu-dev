from explog.cli import build_init_parser, build_parser, main


def test_parser_has_only_the_fixed_options() -> None:
    option_strings = {
        option for action in build_parser()._actions for option in action.option_strings
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


def test_init_parser_has_defaults() -> None:
    arguments = build_init_parser().parse_args([])

    assert arguments.config.name == "explog.toml"
    assert arguments.log.name == "experiments.jsonl"


def test_cli_reports_expected_error(capsys) -> None:
    exit_code = main(
        [
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


def test_cli_initializes_with_defaults(
    git_repo, config_file, monkeypatch, capsys
) -> None:
    monkeypatch.chdir(git_repo)

    exit_code = main(["init"])

    assert exit_code == 0
    assert (git_repo / "experiments.jsonl").read_bytes() == b""
    assert (git_repo / "experiment-data").is_dir()
    output = capsys.readouterr().out
    assert "explog environment is ready" in output
    assert f"Config: {config_file}" in output
