"""无 Claude/无邮件:跑 picks 引擎 → 渲染预览到 reports/preview_picks.html。

用法: uv run python scripts/preview_picks.py [--skip-summary]
触网(akshare);失败标的降级,不阻塞。preview=True → 渲染存盘但不发送。
"""
import argparse
import logging
from types import SimpleNamespace

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")


def main():
    parser = argparse.ArgumentParser(description="Preview picks report (no Claude/email)")
    parser.add_argument("--skip-summary", action="store_true",
                        help="Skip Claude综合研判, structure-only preview")
    args = parser.parse_args()

    from investbrief.pipelines.picks import run_picks_report
    ns = SimpleNamespace(dry_run=False, preview=True, skip_summary=args.skip_summary)
    run_picks_report(ns)
    print("Preview saved to reports/preview_picks.html")


if __name__ == "__main__":
    main()
