"""一次性全历史回填：拉取 CN 指数日线 + 宏观序列 + 黄金进 SQLite。

用法：
    uv run python scripts/backfill_macro_data.py             # 回填 CN+Gold
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
from investbrief.data.gold_data import GoldData

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler()],
)
logger = logging.getLogger("backfill")


def main():
    parser = argparse.ArgumentParser(description="Backfill macro SQLite with full history")
    parser.add_argument("--market", choices=["cn", "gold", "all"], default="all")
    args = parser.parse_args()

    logger.info(f"DB_PATH = {DB_PATH}")
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)

    if args.market in ("all", "cn"):
        ds = CNData()
        try:
            logger.info("Backfilling cn (update_all)...")
            ds.update_all()
            logger.info("cn backfill done")
            # 红利低波100 股息率（akshare 当日值，历史接口不存在；update_all 已含一次，显式再跑一次以独立日志确认）
            try:
                ds._update_dividend_yield()
                logger.info("红利低波100 股息率 (当日) backfilled")
            except Exception as e:
                logger.error(f"红利低波 backfill failed: {e}")
        except Exception as e:
            logger.error(f"cn backfill failed: {e}")
        finally:
            ds.close()

    if args.market in ("all", "gold"):
        ds = GoldData()
        try:
            logger.info("Backfilling gold (update_all)...")
            ds.update_all()
            logger.info("gold backfill done")
            # AISC（WGC，全量季度 2012-至今；update_all 已含一次，显式再跑一次以独立日志确认）
            try:
                ds.update_gold_aisc()
                logger.info("Gold AISC (WGC) backfilled")
            except Exception as e:
                logger.error(f"AISC backfill failed: {e}")
        except Exception as e:
            logger.error(f"gold backfill failed: {e}")
        finally:
            ds.close()

    # ERP（multpl，全量月度历史；不依赖 market 分支，cn/gold/all 均回填）
    try:
        from investbrief.data.valuation_data import ValuationData
        vd = ValuationData()
        try:
            logger.info("Backfilling ERP (multpl Shiller PE + US 10Y)...")
            vd.update_erp()
            logger.info("ERP backfill done")
        finally:
            vd.close()
    except Exception as e:
        logger.error(f"ERP backfill failed: {e}")

    logger.info("Backfill complete")


if __name__ == "__main__":
    main()
