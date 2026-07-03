"""Shared helpers for datasources API key resolution."""
import os
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

# Load credentials from project root .env (project root = 3 levels up from this file)
load_dotenv(Path(__file__).resolve().parent.parent.parent / ".env", override=False)

# Environment variable names for API keys
ENV_KEYS = {
    "finnhub": "FINNHUB_KEY",
    "alphavantage": "ALPHAVANTAGE_KEY",
    "tavily": "TAVILY_KEY",
}


def _resolve_api_key(config_key: Optional[str], env_name: str) -> Optional[str]:
    """Resolve API key: env var takes priority over config value."""
    return os.environ.get(env_name) or config_key
