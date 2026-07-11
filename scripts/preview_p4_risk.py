"""P4 验证：用真实 DB 渲染 CN/黄金 风险卡到完整邮件 HTML，存 preview。

不走 refresh（DB 已被回填），只验证渲染路径 + 风险卡 + 模板组装。
用法：uv run python scripts/preview_p4_risk.py  → reports/preview_p4_risk.html
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from investbrief.data.cn_data import CNData
from investbrief.data.gold_data import GoldData
from investbrief.market.cn.provider import CNMarketProvider
from investbrief.risk.config import load_indicators
from investbrief.risk.models import RiskModel
from investbrief.risk.render import render_gold_section, render_risk_card
from investbrief.pipelines.macro import _build_indicators
from investbrief.mail.render import render_template


def main():
    rc = {"color_up": "#e74c3c", "color_down": "#27ae60"}
    cn = CNMarketProvider(data=CNData())
    gold_ds = GoldData()

    # Risk scores (real DB; 每市场用自己的 indicators 注入 RiskModel)
    risk = {}
    for code, ds, group in (("cn", cn.data, "cn"), ("gold", gold_ds, "gold")):
        ind_config = load_indicators(group)
        indicators = _build_indicators(code, ds, ind_config)
        model = RiskModel(ds, indicators=indicators)
        risk[code] = model.calculate_score(code)

    print("=== 风险分 ===")
    for code, name in (("cn", "A股"), ("gold", "黄金")):
        r = risk[code]
        print(f"  {name}: {r['total_score']} ({r['state']}) — {r['action']}")
        print(f"       dimensions={r['dimensions']}")

    # Render sections WITH risk cards inline
    cn_data = cn.fetch_all()
    cn_html = cn.render_section(cn_data, rc, risk_html=render_risk_card(risk["cn"]))
    gold_html = render_gold_section(risk["gold"])
    market_section_html = cn_html + gold_html

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
    html = render_template("email_base.j2", report_data, "zh-CN")

    out = Path(__file__).resolve().parent.parent / "reports" / "preview_p4_risk.html"
    out.parent.mkdir(exist_ok=True)
    out.write_text(html, encoding="utf-8")
    print(f"\nPreview saved: {out}  ({len(html)} chars)")

    # Self-check: both cards present
    for code, name in (("cn", "A股"), ("gold", "黄金")):
        score = str(risk[code]["total_score"])
        state = risk[code]["state"]
        assert score in html, f"{name} score {score} not in HTML"
        assert state in html, f"{name} state {state} not in HTML"
    print("Self-check OK: CN/黄金 风险卡均出现在渲染 HTML 中")

    cn.data.close()
    gold_ds.close()


if __name__ == "__main__":
    main()
