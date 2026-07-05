"""Centralized logging setup: format, handlers, third-party noise suppression.

Business logs (investbrief.*) stay at the configured level; noisy third-party
libs (anthropic SDK, urllib3, akshare, yfinance) are pinned to WARNING so their
INFO output does not drown pipeline logs in logs/run.log.
"""
import logging
from pathlib import Path

# Third-party libs that spam INFO and add no signal to daily pipeline logs.
_NOISY_LOGGERS = ("anthropic", "urllib3", "akshare", "yfinance", "httpx", "openai")


def setup_logging(level: int = logging.INFO, log_dir: Path | None = None) -> None:
    """Configure root logger with file+stream handlers and suppress noisy libs.

    Uses force=True so repeated calls (e.g. tests, re-entry) re-apply cleanly
    instead of no-oping on the first basicConfig.
    """
    if log_dir is None:
        # Default: <repo>/logs/run.log (repo root = parent of investbrief/)
        log_dir = Path(__file__).parent.parent.parent / "logs"
    log_dir.mkdir(exist_ok=True)

    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    handlers = [
        logging.FileHandler(log_dir / "run.log", encoding="utf-8"),
        logging.StreamHandler(),
    ]
    for h in handlers:
        h.setFormatter(fmt)
    logging.basicConfig(level=level, handlers=handlers, force=True)

    for name in _NOISY_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)
