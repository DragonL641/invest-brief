import json
import tempfile
from pathlib import Path

from filelock import FileLock

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


def update_recipient(user_id: int, updates: dict) -> dict | None:
    """Update a recipient's config in config.json with file locking."""
    config_path = Path(__file__).resolve().parent.parent.parent / "config.json"
    lock_path = config_path.with_suffix(".json.lock")
    lock = FileLock(str(lock_path))

    with lock:
        with open(config_path, "r", encoding="utf-8") as f:
            config = json.load(f)

        recipients = config.get("recipients", [])
        updated = None
        for r in recipients:
            if r.get("id") == user_id:
                r.update(updates)
                updated = r
                break

        if updated is None:
            return None

        tmp = tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=str(config_path.parent),
            prefix=".config_", suffix=".tmp", delete=False,
        )
        try:
            json.dump(config, tmp, ensure_ascii=False, indent=2)
            tmp.close()
            Path(tmp.name).rename(config_path)
        except Exception:
            Path(tmp.name).unlink(missing_ok=True)
            raise

    reload_config()
    return updated


def get_recipient_by_id(user_id: int) -> dict | None:
    for r in get_recipients():
        if r.get("id") == user_id:
            return r
    return None
