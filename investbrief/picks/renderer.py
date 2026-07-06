# investbrief/picks/renderer.py
"""picks 卡片/段落 HTML(注入 email_picks.j2 的 sections_html,同 holdings 模式)。"""
from __future__ import annotations

from investbrief.picks.factors import FACTOR_LABELS

_PROFILE_TITLE = {"swing": "波段 · 2周~3个月", "medium": "中长线 · 3个月~1年", "long": "长线 · 1年~5年+"}

_MARKET_ACCENT = {"cn": "#e74c3c", "us": "#3498db"}   # A股红 / 美股蓝
_MARKET_LABEL = {"cn": "A股", "us": "美股"}


def _score_color(v) -> str:
    """综合分配色:高=绿,中=橙,低=灰。"""
    if not isinstance(v, (int, float)):
        return "#95a5a6"
    if v >= 60:
        return "#27ae60"
    if v >= 35:
        return "#e67e22"
    return "#95a5a6"


def _bar_color(pct) -> str:
    if not isinstance(pct, (int, float)):
        return "#d5dbdb"
    if pct >= 70:
        return "#27ae60"
    if pct >= 40:
        return "#f39c12"
    return "#d5dbdb"


def _fmt(v) -> str:
    if v is None:
        return "—"
    if isinstance(v, float):
        return f"{v:.2f}"
    return str(v)


def render_pick_card(pick: dict | None, profile: str = "", market: str = "") -> str:
    if pick is None:
        mkt = _MARKET_LABEL.get(market, "")
        return (f'<div class="pick-card" style="background:#fafbfc;border:1px dashed #d5dbdb;'
                f'border-radius:10px;padding:20px;margin:6px 0;text-align:center;'
                f'color:#b0b8bf;font-size:13px;">{mkt}本期无符合条件标的</div>')
    accent = _MARKET_ACCENT.get(pick.get("market"), "#95a5a6")
    mkt_label = _MARKET_LABEL.get(pick.get("market"), "")
    comp = pick.get("composite", 0)

    # 因子行(中文标签 + 分位进度条 + 分位 + 贡献)
    rows = "".join(_factor_row(k, sc) for k, sc in (pick.get("factor_scores") or {}).items())

    # 买入逻辑(triggers)
    triggers = pick.get("triggers") or []
    trig_html = ""
    if triggers:
        items = "".join(f"<li>{t}</li>" for t in triggers)
        trig_html = (f'<div style="margin-top:10px;padding:8px 10px;background:#fef9e7;'
                     f'border-left:3px solid #f1c40f;border-radius:4px;font-size:12px;color:#7d6608;">'
                     f'<b>买入逻辑</b><ul style="margin:4px 0 0;padding-left:18px;">{items}</ul></div>')

    mas = pick.get("key_mas") or {}
    return f'''<div class="pick-card" style="background:#fff;border-radius:10px;padding:14px 16px;margin:6px 0;border-left:4px solid {accent};box-shadow:0 1px 3px rgba(0,0,0,0.05);">
  <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px;">
    <div>
      <span style="font-size:16px;font-weight:700;color:#2c3e50;">{pick.get("name","")}</span>
      <span style="color:#95a5a6;font-size:12px;margin-left:5px;">{pick.get("symbol","")}</span>
      <span style="background:{accent};color:#fff;font-size:10px;padding:1px 7px;border-radius:9px;margin-left:6px;">{mkt_label}</span>
    </div>
    <div style="text-align:right;line-height:1;">
      <div style="font-size:24px;font-weight:800;color:{_score_color(comp)};">{comp}</div>
      <div style="font-size:10px;color:#bdc3c7;margin-top:2px;">综合分</div>
    </div>
  </div>
  <table style="width:100%;font-size:12px;border-collapse:collapse;">{rows}</table>
  <div style="display:flex;gap:10px;margin-top:10px;padding-top:8px;border-top:1px solid #f0f0f0;">
    <div style="flex:1;"><div style="color:#bdc3c7;font-size:10px;">现价</div><div style="font-weight:700;color:#2c3e50;font-size:14px;">{_fmt(pick.get("price"))}</div></div>
    <div style="flex:1;"><div style="color:#bdc3c7;font-size:10px;">MA20</div><div style="color:#34495e;">{_fmt(mas.get("ma20"))}</div></div>
    <div style="flex:1;"><div style="color:#bdc3c7;font-size:10px;">MA60</div><div style="color:#34495e;">{_fmt(mas.get("ma60"))}</div></div>
    <div style="flex:1;"><div style="color:#bdc3c7;font-size:10px;">止损</div><div style="color:#e74c3c;font-weight:600;">{_fmt(pick.get("stop_level"))}</div></div>
  </div>
  {trig_html}
</div>'''


def _factor_row(key: str, sc: dict) -> str:
    label = FACTOR_LABELS.get(key, key)
    pct = sc.get("pct")
    weighted = sc.get("weighted")
    pct_disp = f"{pct:.0f}" if isinstance(pct, (int, float)) else "—"
    bar_w = pct if isinstance(pct, (int, float)) else 0
    if isinstance(weighted, (int, float)) and weighted > 0:
        w_disp = f"+{weighted:.1f}"
        w_color = "#27ae60"
    elif isinstance(weighted, (int, float)):
        w_disp = f"{weighted:.1f}"
        w_color = "#bdc3c7"
    else:
        w_disp = "—"
        w_color = "#d5dbdb"
    return f'''<tr>
  <td style="padding:4px 0;color:#566573;width:74px;">{label}</td>
  <td style="width:90px;padding:0 8px;"><div style="background:#eef0f2;border-radius:3px;height:7px;"><div style="background:{_bar_color(pct)};height:7px;border-radius:3px;width:{bar_w:.0f}%;"></div></div></td>
  <td style="color:#95a5a6;text-align:right;width:32px;font-size:11px;">{pct_disp}</td>
  <td style="text-align:right;width:42px;color:{w_color};font-weight:600;font-size:11px;">{w_disp}</td>
</tr>'''


def render_pick_section(profile: str, cn_pick: dict | None, us_pick: dict | None) -> str:
    title = _PROFILE_TITLE.get(profile, profile)
    return f'''
<div class="pick-section" style="margin:18px 0;">
  <div style="font-size:15px;font-weight:700;color:#2c3e50;border-left:3px solid #2c3e50;padding-left:8px;margin-bottom:8px;">{title}</div>
  <div style="display:flex;gap:10px;">
    <div style="flex:1;min-width:0;">{render_pick_card(cn_pick, profile, "cn")}</div>
    <div style="flex:1;min-width:0;">{render_pick_card(us_pick, profile, "us")}</div>
  </div>
</div>'''
