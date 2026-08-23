from explog.cli import build_parser, main


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
