import json
from pathlib import Path

_config_cache = None


def get_config() -> dict:
    global _config_cache
    if _config_cache is None:
        config_path = Path(__file__).resolve().parent.parent.parent / "config.json"
        with open(config_path) as f:
            _config_cache = json.load(f)
    return _config_cache


def get_web_config() -> dict:
    return get_config().get("web", {})


def get_recipients() -> list[dict]:
    return get_config().get("recipients", [])


def get_recipient_by_email(email: str) -> dict | None:
    for r in get_recipients():
        if r.get("email") == email:
            return r
    return None


def reload_config():
    global _config_cache
    _config_cache = None
