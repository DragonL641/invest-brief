"""一次性全历史回填：拉取 CN/US 指数日线 + 宏观序列 + 黄金进 SQLite。

用法：
    uv run python scripts/backfill_macro_data.py             # 回填 CN+US+Gold
    uv run python scripts/backfill_macro_data.py --market cn
    uv run python scripts/backfill_macro_data.py --market gold

首次部署执行一次（约 10-30 分钟，取决于网络）。之后日常管线靠增量。
"""
import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from investbrief.core.config import DB_PATH
from investbrief.data.cn_data import CNData
from investbrief.data.us_data import USData
from investbrief.data.gold_data import GoldData

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler()],
)
logger = logging.getLogger("backfill")


def main():
    parser = argparse.ArgumentParser(description="Backfill macro SQLite with full history")
    parser.add_argument("--market", choices=["cn", "us", "gold", "all"], default="all")
    args = parser.parse_args()

    logger.info(f"DB_PATH = {DB_PATH}")
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)

    # cn/us loop handles only cn/us; gold has its own step below (separate data class)
    markets = ["cn", "us"] if args.market == "all" else ([args.market] if args.market in ("cn", "us") else [])
    for m in markets:
        ds = CNData() if m == "cn" else USData()
        try:
            logger.info(f"Backfilling {m} (update_all)...")
            ds.update_all()
            logger.info(f"{m} backfill done")
        except Exception as e:
            logger.error(f"{m} backfill failed: {e}")
        finally:
            ds.close()

    # Gold (separate data class, not a cn/us market)
    if args.market in ("all", "gold"):
        ds = GoldData()
        try:
            logger.info("Backfilling gold (update_all)...")
            ds.update_all()
            logger.info("gold backfill done")
        except Exception as e:
            logger.error(f"gold backfill failed: {e}")
        finally:
            ds.close()

    logger.info("Backfill complete")


if __name__ == "__main__":
    main()
