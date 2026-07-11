"""
Entry point for invest-brief.

Usage:
    uv run run.py --now                       # Run all pipelines once immediately
    uv run run.py --dry-run                   # Build macro report, output to stdout
    uv run run.py --skip-summary              # Skip Claude API summary
    uv run run.py                             # Scheduler mode (cron-based)
"""

import sys
import os
import signal
import argparse
import logging
from pathlib import Path

from dotenv import load_dotenv

PROJECT_DIR = Path(__file__).resolve().parent
ENV_FILE = PROJECT_DIR / ".env"

load_dotenv(ENV_FILE, override=False)

# 所有 API 都在国内(eastmoney/央行/统计/SGE/sina + Tavily/Claude 走国内兼容端点),
# 忽略系统/shell 代理,全部直连。原「自动检测 macOS 系统代理 + CN 域 NO_PROXY 打补丁」方式
# 既绕弯又漏 eastmoney 子域(子域断连 RemoteDisconnected),直接清空代理 + NO_PROXY=* 最干净。
for _k in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "ALL_PROXY", "all_proxy"):
    os.environ.pop(_k, None)
os.environ["NO_PROXY"] = "*"

# Ensure ANTHROPIC_AUTH_TOKEN is available as ANTHROPIC_API_KEY for anthropic SDK
if not os.environ.get("ANTHROPIC_API_KEY") and os.environ.get("ANTHROPIC_AUTH_TOKEN"):
    os.environ["ANTHROPIC_API_KEY"] = os.environ["ANTHROPIC_AUTH_TOKEN"]

# 配置层清洗 [1m] 等 context 标记（Claude Code runtime 会泄漏如 glm-5.2[1m]，
# 兼容端点不识别）。default_model() 仍保留同样过滤作防御深度。
_model = os.environ.get("ANTHROPIC_DEFAULT_SONNET_MODEL", "")
if _model and "[" in _model:
    import re
    _cleaned = re.sub(r"\[.*\]", "", _model).strip()
    if _cleaned and _cleaned != _model:
        os.environ["ANTHROPIC_DEFAULT_SONNET_MODEL"] = _cleaned

logger = logging.getLogger("run")


def run_once(args):
    """Execute pipeline(s) once. --only controls which; default runs all enabled."""
    from investbrief.pipelines.macro import run_macro_report
    from investbrief.pipelines.holdings import run_holdings_report
    from investbrief.pipelines.picks import run_picks_report
    only = getattr(args, "only", None)
    if only in (None, "macro"):
        run_macro_report(args)
    # Holdings pipeline has no update-only mode; skip under --update
    if only in (None, "holdings") and not getattr(args, "update", False):
        run_holdings_report(args)
    if only in (None, "picks") and not getattr(args, "update", False):
        run_picks_report(args)


def build_parser():
    """Construct the CLI argparse parser. Extracted from main() for testability
    (routing/choices tests call this directly instead of spawning a subprocess)."""
    parser = argparse.ArgumentParser(description="invest-brief - Personalized Investment Briefing")
    parser.add_argument(
        "--market",
        required=False,
        choices=["cn", "all"],
        help="(Deprecated, no-op) cn-pivot 后报告恒为 A 股+外围卡+黄金;保留仅为 CLI 兼容",
    )
    parser.add_argument("--now", action="store_true", help="Run once immediately (default: scheduler mode)")
    parser.add_argument("--dry-run", action="store_true", help="Build report, output to stdout, do not send email")
    parser.add_argument("--skip-summary", action="store_true", help="Skip Claude API summary, use placeholder")
    parser.add_argument("--force", action="store_true",
                        help="跳过邮件日级缓存，强制重新生成 macro/picks/holdings")
    parser.add_argument("--update", action="store_true",
                        help="Only refresh macro data into SQLite, no render/email")
    parser.add_argument("--only", choices=["macro", "holdings", "picks"], default=None,
                        help="Run only one pipeline (default: all)")
    parser.add_argument("--log-level", default="INFO", help="Log level (DEBUG, INFO, WARNING, ERROR)")
    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()

    # Setup logging (centralized: format + third-party noise suppression)
    from investbrief.core.logging import setup_logging
    setup_logging(level=getattr(logging, args.log_level.upper(), logging.INFO))

    # Friendly check: config.json must exist before any pipeline runs.
    # Without this, load_config() raises a raw FileNotFoundError traceback.
    from investbrief.core.config import CONFIG_FILE
    if not CONFIG_FILE.exists():
        logger.error(
            "缺少 config.json — 请从 config.example.json 复制:\n"
            "  cp config.example.json config.json"
        )
        sys.exit(1)

    if args.now or args.dry_run or args.update:
        run_once(args)
    else:
        # Scheduler mode
        from investbrief.core.config import load_config
        from investbrief.pipelines import scheduler

        config = load_config()
        schedule_cfg = config.get("schedule", {})
        enabled = schedule_cfg.get("enabled", False)

        # Also check new-style markets config
        markets_cfg = config.get("markets", {})
        has_enabled_market = any(m.get("enabled", False) for m in markets_cfg.values())

        if not enabled and not has_enabled_market:
            logger.error("Scheduler mode is not enabled. Use --now for immediate execution or enable schedule in config.json")
            sys.exit(1)

        signal.signal(signal.SIGTERM, scheduler.request_shutdown)
        signal.signal(signal.SIGINT, scheduler.request_shutdown)

        scheduler.run_scheduler(config)


if __name__ == "__main__":
    main()
