"""Scheduler: long-running cron-based process driving macro + holdings pipelines."""
import argparse
import logging
import threading
import time
from datetime import datetime
from zoneinfo import ZoneInfo

from croniter import croniter

logger = logging.getLogger(__name__)

# Graceful shutdown flag (module global — toggled by request_shutdown)
_shutdown = False


def request_shutdown(signum=None, frame=None):
    """Signal handler: flip the global _shutdown flag so the scheduler loop exits."""
    global _shutdown
    import signal as _signal
    if signum is not None:
        try:
            name = _signal.Signals(signum).name
        except Exception:
            name = str(signum)
        logger.info(f"Received {name}, shutting down gracefully...")
    _shutdown = True


def first_enabled_cron(config: dict) -> str | None:
    """Return the cron expression of the first enabled market (us preferred), else None."""
    markets_cfg = config.get("markets", {})
    for market in ("us", "cn"):
        cfg = markets_cfg.get(market, {})
        if not cfg.get("enabled", False):
            continue
        raw = cfg.get("schedule")
        if isinstance(raw, list):
            if raw:
                return raw[0].get("cron", "0 23 * * 1-5")
        elif isinstance(raw, dict):
            return raw.get("cron", "0 23 * * 1-5")
    # Fallback: old-style top-level schedule
    schedule_cfg = config.get("schedule", {})
    if schedule_cfg.get("enabled", False):
        return schedule_cfg.get("cron", "0 23 * * 1-5")
    return None


def run_scheduler(config):
    """Run as a long-lived process, executing ONE merged macro report at cron-scheduled times.

    The macro pipeline always merges US+CN, so only a single scheduler thread is started
    using the first enabled market's cron expression to avoid double-sending.
    """
    cron_expr = first_enabled_cron(config)
    if cron_expr is None:
        logger.error("No enabled markets found in config; nothing to schedule")
        return

    t = threading.Thread(
        target=_run_scheduled_macro,
        args=(cron_expr,),
        name="scheduler-macro",
        daemon=True,
    )
    t.start()

    while not _shutdown:
        time.sleep(1)


def _run_scheduled_macro(cron_expr: str):
    """Run the merged macro report loop on a single cron schedule."""
    if not croniter.is_valid(cron_expr):
        logger.error(f"Invalid cron expression: {cron_expr}")
        return

    tz = ZoneInfo("Asia/Shanghai")
    now = datetime.now(tz)
    cron = croniter(cron_expr, now)
    next_run = cron.get_next(datetime)

    logger.info(f"Scheduler started with cron: '{cron_expr}'")
    logger.info(f"Next run scheduled at: {next_run.strftime('%Y-%m-%d %H:%M:%S')}")

    while not _shutdown:
        now = datetime.now(tz)

        if now >= next_run:
            logger.info("=" * 60)
            logger.info("Scheduled macro report run triggered")

            args = argparse.Namespace(
                market="all",
                dry_run=False,
                skip_summary=False,
                only=None,
                log_level=logging.getLevelName(logger.getEffectiveLevel()),
            )

            try:
                from investbrief.pipelines.macro import run_macro_report
                run_macro_report(args)
            except Exception as e:
                logger.error(f"Scheduled macro run failed: {e}", exc_info=True)
            try:
                from investbrief.pipelines.holdings import run_holdings_report
                run_holdings_report(args)
            except Exception as e:
                logger.error(f"Scheduled holdings run failed: {e}", exc_info=True)

            cron = croniter(cron_expr, now)
            next_run = cron.get_next(datetime)
            logger.info(f"Next run scheduled at: {next_run.strftime('%Y-%m-%d %H:%M:%S')}")

        time.sleep(30)

    logger.info("Scheduler stopped")
