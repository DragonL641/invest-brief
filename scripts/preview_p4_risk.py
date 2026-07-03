"""P4 验证：用真实 DB 渲染三市场风险卡到完整邮件 HTML，存 preview。

不走 refresh（DB 已被 P1-P3 回填），只验证渲染路径 + 风险卡 + 模板组装。
用法：uv run python scripts/preview_p4_risk.py  → reports/preview_p4_risk.html
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd  # noqa: F401  (some imports need pandas in ns)

from investbrief.data.us_data import USData
from investbrief.data.cn_data import CNData
from investbrief.data.gold_data import GoldData
from investbrief.us.provider import USMarketProvider
from investbrief.cn.provider import CNMarketProvider
from investbrief.risk.models import RiskModel
from investbrief.risk.render import render_risk_card, render_gold_section
from investbrief.report import load_template, render_template


def main():
    rc = {"color_up": "#e74c3c", "color_down": "#27ae60"}
    us = USMarketProvider(data=USData())
    cn = CNMarketProvider(data=CNData())
    gold_ds = GoldData()

    # Risk scores (real DB; RiskModel reads the shared SQLite via us.data)
    model = RiskModel(us.data)
    risk = {m: model.calculate_score(m) for m in ("us", "cn", "gold")}

    print("=== 风险分 ===")
    for m, name in (("us", "美股"), ("cn", "A股"), ("gold", "黄金")):
        r = risk[m]
        print(f"  {name}: {r['total_score']} ({r['state']}) — {r['action']}")
        print(f"       dimensions={r['dimensions']}")

    # Render sections WITH risk cards inline
    us_data = us.fetch_all()
    cn_data = cn.fetch_all()
    us_html = us.render_section(us_data, rc, risk_html=render_risk_card(risk["us"]))
    cn_html = cn.render_section(cn_data, rc, risk_html=render_risk_card(risk["cn"]))
    gold_html = render_gold_section(risk["gold"])
    market_section_html = us_html + cn_html + gold_html

    # Build a minimal report_data and render the full template
    from datetime import datetime
    report_data = {
        "subject": "【P4 风险板块预览】",
        "data_time": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "date": datetime.now().strftime("%Y-%m-%d"),
        "market": "all",
        "macro_summary": "<p>（预览：跳过 Claude 核心观点）</p>",
        "risk_outlook": "<p>—</p>",
        "market_section_html": market_section_html,
        "research_views": "",
        "news": [],
    }
    html = render_template(load_template(), report_data, "zh-CN")

    out = Path(__file__).resolve().parent.parent / "reports" / "preview_p4_risk.html"
    out.parent.mkdir(exist_ok=True)
    out.write_text(html, encoding="utf-8")
    print(f"\nPreview saved: {out}  ({len(html)} chars)")

    # Self-check: all 3 cards present
    for m, name in (("us", "美股"), ("cn", "A股"), ("gold", "黄金")):
        score = str(risk[m]["total_score"])
        state = risk[m]["state"]
        assert score in html, f"{name} score {score} not in HTML"
        assert state in html, f"{name} state {state} not in HTML"
    print("Self-check OK: 三市场风险卡均出现在渲染 HTML 中")

    us.data.close()
    cn.data.close()
    gold_ds.close()


if __name__ == "__main__":
    main()
