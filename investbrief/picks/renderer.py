# investbrief/picks/renderer.py
"""picks 卡片/段落 HTML(注入 email_picks.j2 的 sections_html,同 holdings 模式)。"""
from __future__ import annotations

_PROFILE_TITLE = {"swing": "波段(2周~3个月)", "medium": "中长线(3个月~1年)", "long": "长线(1年~5年+)"}


def render_pick_card(pick: dict | None, profile: str = "", market: str = "") -> str:
    if pick is None:
        mkt = "A股" if market == "cn" else ("美股" if market == "us" else "")
        return f'<div class="pick-card empty"><em>{mkt}本期无符合条件标的</em></div>'
    fs = pick.get("factor_scores", {})
    factor_rows = "".join(
        f'<tr><td>{k}</td><td>{_fmt(sc.get("raw"))}</td>'
        f'<td>{_fmt(sc.get("pct"))}</td><td>{_fmt(sc.get("weighted"))}</td></tr>'
        for k, sc in fs.items()
    )
    triggers = "".join(f"<li>{t}</li>" for t in pick.get("triggers", []))
    mas = pick.get("key_mas") or {}
    return f'''
<div class="pick-card" style="border:1px solid #e0e0e0;border-radius:8px;padding:14px;margin:8px 0;">
  <div style="font-weight:600;font-size:15px;color:#2c3e50;">
    {pick.get("name","")} <span style="color:#888;font-weight:normal;">({pick.get("symbol","")}) · {_market_label(pick.get("market"))}</span>
    <span style="float:right;color:#e67e22;font-weight:700;">综合 {pick.get("composite",0)}</span>
  </div>
  <table style="width:100%;font-size:12px;margin-top:8px;border-collapse:collapse;">
    <thead><tr style="color:#999;"><td>因子</td><td>原始</td><td>分位</td><td>贡献</td></tr></thead>
    <tbody>{factor_rows}</tbody>
  </table>
  <div style="font-size:12px;color:#555;margin-top:8px;">
    <strong>买入逻辑:</strong>{("".join(['<ul style="margin:4px 0;padding-left:18px;">', triggers, "</ul>"]) if triggers else " —")}
    <strong>当前价:</strong>{_fmt(pick.get("price"))} ·
    <strong>MA20/60/120:</strong>{_fmt(mas.get("ma20"))}/{_fmt(mas.get("ma60"))}/{_fmt(mas.get("ma120"))} ·
    <strong>止损:</strong>{_fmt(pick.get("stop_level"))}
  </div>
</div>'''


def render_pick_section(profile: str, cn_pick: dict | None, us_pick: dict | None) -> str:
    title = _PROFILE_TITLE.get(profile, profile)
    return f'''
<div class="pick-section" style="margin:16px 0;">
  <h2 style="margin:0 0 8px 0;font-size:17px;color:#2c3e50;">📈 {title}</h2>
  <div style="display:flex;gap:8px;">
    <div style="flex:1;">{render_pick_card(cn_pick, profile, "cn")}</div>
    <div style="flex:1;">{render_pick_card(us_pick, profile, "us")}</div>
  </div>
</div>'''


def _fmt(v):
    if v is None:
        return "—"
    if isinstance(v, float):
        return f"{v:.2f}"
    return str(v)


def _market_label(m):
    return {"cn": "A股", "us": "美股"}.get(m, "")
