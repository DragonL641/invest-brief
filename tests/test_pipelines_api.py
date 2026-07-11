"""Smoke for pipelines public API."""
from investbrief.pipelines.macro import run_macro_report
from investbrief.pipelines.holdings import run_holdings_report
from investbrief.pipelines.picks import run_picks_report
from investbrief.pipelines.scheduler import run_scheduler, first_enabled_cron
from investbrief.pipelines._send import send_report


def test_pipelines_callable():
    assert callable(run_macro_report)
    assert callable(run_holdings_report)
    assert callable(run_picks_report)
    assert callable(run_scheduler)
    assert callable(send_report)


def test_first_enabled_cron_fallback():
    assert first_enabled_cron({}) is None


def test_request_shutdown_sets_flag():
    import investbrief.pipelines.scheduler as sch
    sch._shutdown = False
    sch.request_shutdown()
    assert sch._shutdown is True
    sch._shutdown = False  # reset
