"""invest-brief 配置加载/校验 + 全局常量。"""
import json
import os
from pathlib import Path

from croniter import croniter

BASE_DIR = Path(__file__).resolve().parent.parent.parent  # 项目根 (core/config.py → 上三级)
DB_PATH = os.environ.get(
    "INVESTBRIEF_DB_PATH",
    str(BASE_DIR / "data" / "macro_data.db"),
)
CONFIG_FILE = BASE_DIR / "config.json"
REPORTS_DIR = BASE_DIR / "reports"

# === API Settings（供 BaseData._retry_api 使用）===
API_RETRY_COUNT = 3
API_RETRY_DELAY = 5  # seconds

# === US GDP 基期（USData._update_gdp 用）===
US_GDP_BASE_YEAR = 2023
US_GDP_BASE_VALUE = 27.36  # 万亿美元

_VALID_HOLDING_MARKETS = {"us", "cn"}
_VALID_HOLDING_TYPES = {"stock", "etf", "fund"}


def load_config() -> dict:
    with open(CONFIG_FILE, encoding="utf-8") as f:
        config = json.load(f)
    validate_config(config)
    return config


def validate_config(config: dict):
    """Validate required config fields with clear error messages."""
    if "email_service" not in config:
        raise ValueError("config.json missing 'email_service' section")
    email_cfg = config["email_service"]
    for key in ("smtp_server", "smtp_port", "sender_email", "sender_name"):
        if not email_cfg.get(key):
            raise ValueError(f"config.json email_service missing or empty '{key}'")
    if not isinstance(email_cfg["smtp_port"], int):
        raise ValueError("config.json email_service smtp_port must be an integer")
    if "recipients" not in config or not config["recipients"]:
        raise ValueError("config.json missing or empty 'recipients' list")

    # Recipients must each have a non-empty email; optional holdings validated if present
    for r in config["recipients"]:
        if not isinstance(r, dict) or not r.get("email"):
            raise ValueError(f"config.json recipient missing 'email': {r}")
        validate_holdings(r.get("holdings"), r["email"])

    # Validate cron expressions for every enabled market
    markets_cfg = config.get("markets", {})
    for market, cfg in markets_cfg.items():
        if not isinstance(cfg, dict) or not cfg.get("enabled", False):
            continue
        raw = cfg.get("schedule")
        crons = []
        if isinstance(raw, list):
            crons = [s.get("cron") for s in raw if isinstance(s, dict)]
        elif isinstance(raw, dict):
            crons = [raw.get("cron")]
        for cron in crons:
            if not cron or not croniter.is_valid(cron):
                raise ValueError(f"Invalid cron '{cron}' for market {market}")

    # Old-style top-level schedule
    schedule_cfg = config.get("schedule", {})
    if schedule_cfg.get("enabled", False):
        cron = schedule_cfg.get("cron")
        if not cron or not croniter.is_valid(cron):
            raise ValueError(f"Invalid cron '{cron}' for top-level schedule")


def validate_holdings(holdings, email: str):
    """Validate a recipient's optional holdings list (drives the per-recipient holdings email)."""
    if holdings is None:
        return
    if not isinstance(holdings, list) or not holdings:
        raise ValueError(f"config.json recipient {email} 'holdings' must be a non-empty list")
    for h in holdings:
        if not isinstance(h, dict):
            raise ValueError(f"config.json recipient {email} holding must be an object: {h}")
        for field in ("symbol", "market", "type"):
            if not str(h.get(field, "")).strip():
                raise ValueError(f"config.json recipient {email} holding missing '{field}': {h}")
        if h["market"] not in _VALID_HOLDING_MARKETS:
            raise ValueError(
                f"config.json recipient {email} holding market must be one of "
                f"{sorted(_VALID_HOLDING_MARKETS)}: {h}"
            )
        if h["type"] not in _VALID_HOLDING_TYPES:
            raise ValueError(
                f"config.json recipient {email} holding type must be one of "
                f"{sorted(_VALID_HOLDING_TYPES)}: {h}"
            )
        # P1 market-type constraints: US supports stock only; fund is CN-only
        if h["market"] == "us" and h["type"] != "stock":
            raise ValueError(
                f"config.json recipient {email} US market only supports type=stock (P1): {h}"
            )
        if h["type"] == "fund" and h["market"] != "cn":
            raise ValueError(
                f"config.json recipient {email} fund type only supported for cn market: {h}"
            )
