"""离线建行业映射 → investbrief/strategies/industry_map.json。

em 板块→成分股反查(symbol→行业, 唯一归属, 实测板块间无重叠)。resilient 增量补全:
已有板块跳过, 空返回重试 3 次, 漏建的下次 em 健康时补。
运行时 picks/holdings 读 JSON 注入 industry, 零 em 依赖, industry_neutralize 生效。

行业分类稳定(新板块罕见), 季度刷新一次即可。em IP 级限流下首次可能建不全,
靠增量多次跑补全(meta.json 记已建板块, 下次跳过)。

用法:
    uv run python scripts/build_industry_map.py            # 增量补全(跳过已建板块)
    uv run python scripts/build_industry_map.py --force    # 全量重建
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import akshare as ak

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "investbrief" / "strategies" / "industry_map.json"
META = ROOT / "investbrief" / "strategies" / "industry_map.meta.json"
RETRIES = 3


def fetch_boards() -> list[str]:
    df = ak.stock_board_industry_name_em()
    col = "板块名称" if "板块名称" in df.columns else df.columns[1]
    return [str(x) for x in df[col].tolist()]


def fetch_cons(board: str) -> set[str] | None:
    """返回成分股代码集合; 重试全败返回 None(记漏建, 下次补)。"""
    for i in range(RETRIES):
        try:
            c = ak.stock_board_industry_cons_em(symbol=board)
            code_col = "代码" if "代码" in c.columns else c.columns[1]
            return set(c[code_col].astype(str))
        except Exception:
            if i < RETRIES - 1:
                time.sleep(2 * (i + 1))
    return None


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--force", action="store_true", help="全量重建(忽略已建板块)")
    args = ap.parse_args()

    # 增量: 读已有映射 + 已建板块集
    sym2board: dict[str, str] = {}
    built: set[str] = set()
    if OUT.exists() and not args.force:
        sym2board = json.loads(OUT.read_text(encoding="utf-8"))
    if META.exists() and not args.force:
        built = set(json.loads(META.read_text(encoding="utf-8")).get("built", []))
    mode = "force 全量" if args.force else "增量"
    print(f"已有: {len(sym2board)} 只股票, {len(built)} 板块已建 ({mode})")

    boards = fetch_boards()
    print(f"板块总数: {len(boards)}")

    missing: list[str] = []
    for i, b in enumerate(boards, 1):
        if b in built and not args.force:
            continue
        cons = fetch_cons(b)
        if cons is None:
            missing.append(b)
            print(f"  [{i}/{len(boards)}] {b}: FAILED(漏建,下次补)")
            continue
        for sym in cons:
            sym2board[sym] = b  # 唯一归属; 实测板块间无重叠
        built.add(b)
        print(f"  [{i}/{len(boards)}] {b}: {len(cons)}只")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(sym2board, ensure_ascii=False, indent=2), encoding="utf-8")
    META.write_text(json.dumps({"built": sorted(built)}, ensure_ascii=False), encoding="utf-8")
    print(f"\n完成: {len(sym2board)} 只股票, {len(built)}/{len(boards)} 板块建成, {len(missing)} 漏建")
    if missing:
        print(f"漏建板块(再跑一次补全): {missing}")


if __name__ == "__main__":
    main()
