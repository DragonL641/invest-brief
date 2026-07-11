"""Datasources layer: low-level API clients (akshare / tavily)."""
from typing import Dict


def get_available_apis(config: dict) -> dict[str, bool]:
    """
    Check which APIs are configured and available.

    Returns:
        {
            "tavily": bool
        }
    """
    api_keys = config.get("api_keys", {})

    return {
        "tavily": bool(api_keys.get("tavily")),
    }


__all__ = ["get_available_apis"]
