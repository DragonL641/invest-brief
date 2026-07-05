"""Smoke test for the merged core.config module."""
import pytest

from investbrief.core.config import (
    validate_config, DB_PATH, API_RETRY_COUNT, API_RETRY_DELAY,
    US_GDP_BASE_YEAR, US_GDP_BASE_VALUE,
)


def test_constants_present():
    assert DB_PATH.endswith("macro_data.db")
    assert API_RETRY_COUNT == 3
    assert API_RETRY_DELAY == 5
    assert US_GDP_BASE_YEAR == 2023
    assert US_GDP_BASE_VALUE == 27.36


def test_validate_config_rejects_missing_email_service():
    with pytest.raises(ValueError, match="email_service"):
        validate_config({"recipients": [{"email": "a@b.c"}]})
