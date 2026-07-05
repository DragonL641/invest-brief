"""Centralized logging setup: third-party noise suppression."""
import logging

from investbrief.core.logging import setup_logging


def test_setup_logging_suppresses_noisy_libs():
    setup_logging(level=logging.INFO)
    for name in ("anthropic", "urllib3", "akshare", "yfinance", "httpx", "openai"):
        assert logging.getLogger(name).level == logging.WARNING, (
            f"{name} should be suppressed to WARNING"
        )


def test_setup_logging_is_idempotent():
    # Calling twice must not crash (force=True re-applies config)
    setup_logging(level=logging.INFO)
    setup_logging(level=logging.DEBUG)
    assert logging.getLogger("anthropic").level == logging.WARNING
