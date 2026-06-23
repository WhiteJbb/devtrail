"""print-schedule 명령 테스트."""

from typer.testing import CliRunner
from app import cli

runner = CliRunner()


def test_print_schedule_windows():
    result = runner.invoke(cli.app, ["print-schedule", "--windows"])
    assert result.exit_code == 0
    assert "schtasks" in result.output
    assert "nightly-distill" in result.output
    assert "push-digest" in result.output


def test_print_schedule_cron():
    result = runner.invoke(cli.app, ["print-schedule", "--cron"])
    assert result.exit_code == 0
    assert "nightly-distill" in result.output
    assert "push-digest" in result.output
    assert "23" in result.output  # 23:30 시간


def test_print_schedule_no_flag_fails():
    result = runner.invoke(cli.app, ["print-schedule"])
    assert result.exit_code != 0
