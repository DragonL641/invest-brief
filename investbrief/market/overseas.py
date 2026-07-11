"""外围环境卡:对 A 股有直接影响的外围信号(美联储利率/美债10Y/标普500/USDCNY)。

全 akshare 数据源,零 yfinance 依赖。由 pipelines/macro.py 调算后插入报告。
联邦基金利率为静态常量(FOMC 调整时手动更新)。
"""
import logging
from typing import Any

logger = logging.getLogger(__name__)

# 联邦基金利率目标区间上限(FOMC 调整时更新)
FED_FUNDS_RATE = 5.25

# A 股配色:红涨绿跌
_COLOR_UP = "#e74c3c"
_COLOR_DOWN = "#27ae60"


def fetch_overseas_data(ak_client) -> dict[str, Any]:
    """从 akshare 组装外围卡数据。任一接口失败该键为 None(渲染降级)。"""
    data: dict[str, Any] = {"fed_rate": FED_FUNDS_RATE}
    try:
        data["us_10y"] = ak_client.get_us_treasury_10y()
    except Exception as e:
        logger.warning(f"overseas us_10y failed: {e}")
        data["us_10y"] = None
    try:
        data["sp500"] = ak_client.get_sp500_quote()
    except Exception as e:
        logger.warning(f"overseas sp500 failed: {e}")
        data["sp500"] = None
    try:
        data["usdcny"] = ak_client.get_fx_usdcny_realtime()
    except Exception as e:
        logger.warning(f"overseas usdcny failed: {e}")
        data["usdcny"] = None
    return data


def _fmt_change(change: float | None) -> tuple[str, str]:
    """涨跌幅 → (显示文本, 颜色)。"""
    if change is None:
        return ("-", "#7f8c8d")
    sign = "+" if change > 0 else ""
    color = _COLOR_UP if change > 0 else _COLOR_DOWN if change < 0 else "#7f8c8d"
    return (f"{sign}{change:.2f}%", color)


def render_overseas_card(data: dict[str, Any]) -> str:
    """渲染外围环境紧凑卡片。缺失指标降级为 '-'。"""
    fed = data.get("fed_rate")
    us_10y = data.get("us_10y")
    sp = data.get("sp500") or {}
    usdcny = data.get("usdcny")

    sp_point = sp.get("point") if isinstance(sp, dict) else None
    sp_chg_txt, sp_color = _fmt_change(sp.get("change") if isinstance(sp, dict) else None)

    def _cell(label: str, value, suffix: str = "", color: str = "#2c3e50") -> str:
        val_str = f"{value:.2f}{suffix}" if isinstance(value, (int, float)) else "-"
        return (f'<div class="asset-card" style="background:#f8f9fa;border-radius:8px;'
                f'padding:12px 10px;text-align:center;margin:4px;">'
                f'<div style="font-size:12px;color:#7f8c8d;margin-bottom:4px;">{label}</div>'
                f'<div style="font-size:18px;font-weight:bold;color:{color};">{val_str}</div></div>')

    cells = "".join([
        _cell("美联储利率", fed, "%"),
        _cell("美债10Y", us_10y, "%"),
        _cell("标普500", sp_point),
        # 标普涨跌单独一格
        f'<div class="asset-card" style="background:#f8f9fa;border-radius:8px;padding:12px 10px;'
        f'text-align:center;margin:4px;"><div style="font-size:12px;color:#7f8c8d;margin-bottom:4px;">标普涨跌</div>'
        f'<div style="font-size:18px;font-weight:bold;color:{sp_color};">{sp_chg_txt}</div></div>',
        _cell("美元/人民币", usdcny),
    ])

    return f'''
    <div class="section">
      <div class="country-header" style="background-color:#2c3e50; color:#ffffff; padding:15px 20px; margin-bottom:15px;">
        <h3 style="margin:0; font-size:16px; color:#ffffff;">🌐 外围环境</h3>
      </div>
      <div class="card">
        <div class="card-header" style="padding:12px 15px; background:#f8f9fa; border-bottom:1px solid #e9ecef; font-weight:600;">影响 A 股的外围信号</div>
        <div class="card-body">
          <div class="asset-grid" style="display:flex;flex-wrap:wrap;">{cells.strip()}</div>
        </div>
      </div>
    </div>'''
