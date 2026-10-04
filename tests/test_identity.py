"""host / agent 식별자 해석 테스트."""

from __future__ import annotations

import socket

from app.services.identity import resolve_agent, resolve_host


# ── host ──────────────────────────────────────────────────────────────────────

def test_resolve_host_returns_machine_name():
    assert resolve_host() == socket.gethostname().strip()


def test_resolve_host_empty_when_lookup_fails(monkeypatch):
    def _boom():
        raise OSError("no hostname")

    monkeypatch.setattr(socket, "gethostname", _boom)
    assert resolve_host() == ""


# ── agent 우선순위 ────────────────────────────────────────────────────────────

def test_explicit_wins_over_env(monkeypatch):
    monkeypatch.setenv("DEVTRAIL_AGENT", "codex")
    monkeypatch.setenv("CLAUDECODE", "1")
    assert resolve_agent("cli") == "cli"


def test_env_override_wins_over_detection(monkeypatch):
    monkeypatch.setenv("DEVTRAIL_AGENT", "codex")
    monkeypatch.setenv("CLAUDECODE", "1")
    assert resolve_agent() == "codex"


def test_detects_claude_code_from_marker(monkeypatch):
    monkeypatch.delenv("DEVTRAIL_AGENT", raising=False)
    monkeypatch.delenv("CLAUDE_CODE_ENTRYPOINT", raising=False)
    monkeypatch.setenv("CLAUDECODE", "1")
    assert resolve_agent() == "claude-code"


def test_detects_claude_code_from_entrypoint(monkeypatch):
    monkeypatch.delenv("DEVTRAIL_AGENT", raising=False)
    monkeypatch.delenv("CLAUDECODE", raising=False)
    monkeypatch.setenv("CLAUDE_CODE_ENTRYPOINT", "cli")
    assert resolve_agent() == "claude-code"


def test_unknown_agent_stays_empty(monkeypatch):
    """추측해서 채우지 않는다 — 틀린 값은 집계 결론을 바꾼다."""
    for var in ("DEVTRAIL_AGENT", "CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT"):
        monkeypatch.delenv(var, raising=False)
    assert resolve_agent() == ""


def test_blank_values_are_not_treated_as_set(monkeypatch):
    for var in ("DEVTRAIL_AGENT", "CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT"):
        monkeypatch.setenv(var, "   ")
    assert resolve_agent("  ") == ""


# ── 정규화 ────────────────────────────────────────────────────────────────────

def test_normalizes_case_and_spaces(monkeypatch):
    monkeypatch.delenv("DEVTRAIL_AGENT", raising=False)
    assert resolve_agent("Claude Code") == "claude-code"
    assert resolve_agent("  CODEX  ") == "codex"
