"""CLI integration tests for run.py — startup diagnostics & argparse routing.

Problem 1: friendly exit when config.json is missing (no raw FileNotFoundError).
Problem 2: --only routing, --update skip, --market choices rejection.

Approach: routing is tested by calling run.run_once() with an argparse Namespace
and monkeypatching the three pipeline entry points at their source modules. The
parser itself is tested via run.build_parser() (no subprocess needed). This keeps
the tests fast and hermetic — no real data fetch / Claude call / process spawn.
"""
import sys
from unittest.mock import MagicMock

import pytest


def _ns(**kwargs):
    """Build an argparse Namespace with CLI defaults, overridden by kwargs."""
    from argparse import Namespace
    defaults = dict(
        market="cn", now=False, dry_run=True, skip_summary=False,
        force=False, update=False, only=None, log_level="INFO",
    )
    defaults.update(kwargs)
    return Namespace(**defaults)


# ---------------------------------------------------------------------------
# Problem 1: missing config.json
# ---------------------------------------------------------------------------
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


# ---------------------------------------------------------------------------
# Problem 2: --only routing
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("only,expected", [
    ("macro", ["macro"]),
    ("holdings", ["holdings"]),
    ("picks", ["picks"]),
])
def test_only_routes_to_single_pipeline(monkeypatch, only, expected):
    """--only X dispatches to exactly run_X_report and skips the other two."""
    calls = []
    for name in ("macro", "holdings", "picks"):
        mod = f"investbrief.pipelines.{name}"
        fn = f"run_{name}_report"
        m = MagicMock(side_effect=lambda *a, n=name: calls.append(n))
        monkeypatch.setattr(f"{mod}.{fn}", m)
    import run

    run.run_once(_ns(only=only))

    assert calls == expected


def test_only_none_runs_all_three(monkeypatch):
    """No --only (default) dispatches to all three pipelines in macro→holdings→picks order."""
    calls = []
    for name in ("macro", "holdings", "picks"):
        monkeypatch.setattr(
            f"investbrief.pipelines.{name}.run_{name}_report",
            MagicMock(side_effect=lambda *a, n=name: calls.append(n)),
        )
    import run

    run.run_once(_ns(only=None))

    assert calls == ["macro", "holdings", "picks"]


# ---------------------------------------------------------------------------
# Problem 2: --update skips holdings/picks
# ---------------------------------------------------------------------------
def test_update_runs_only_macro(monkeypatch):
    """--update refreshes macro data only; holdings/picks must be skipped."""
    calls = []
    for name in ("macro", "holdings", "picks"):
        monkeypatch.setattr(
            f"investbrief.pipelines.{name}.run_{name}_report",
            MagicMock(side_effect=lambda *a, n=name: calls.append(n)),
        )
    import run

    run.run_once(_ns(update=True))

    assert calls == ["macro"]


# ---------------------------------------------------------------------------
# Problem 2: --market choices reject 'us' (and other invalid values)
# ---------------------------------------------------------------------------
def test_market_rejects_us():
    """--market us must be rejected by argparse (cn-pivot removed us)."""
    from run import build_parser

    parser = build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["--market", "us"])


def test_market_accepts_cn_and_all():
    """cn and all remain valid (accepted) choices."""
    from run import build_parser

    parser = build_parser()
    assert parser.parse_args(["--market", "cn"]).market == "cn"
    assert parser.parse_args(["--market", "all"]).market == "all"
