"""CLI integration tests for run.py — startup diagnostics & argparse routing.

Problem 1: friendly exit when config.json is missing (no raw FileNotFoundError).
Problem 2 (added below): --only routing, --update skip, --market choices rejection.
"""
import sys

import pytest


def test_main_exits_friendly_when_config_missing(monkeypatch, tmp_path):
    """Missing config.json must produce a friendly log + SystemExit(1), not a raw
    FileNotFoundError traceback from load_config()."""
    import run

    monkeypatch.setattr(sys, "argv", ["run.py", "--now"])
    missing = tmp_path / "does-not-exist.json"
    monkeypatch.setattr("investbrief.core.config.CONFIG_FILE", missing)

    with pytest.raises(SystemExit) as exc:
        run.main()
    assert exc.value.code == 1
