"""外围环境卡:对 A 股有直接影响的外围信号(美联储利率/美债10Y/标普500/USDCNY)。

全 akshare 数据源,零 yfinance 依赖。由 pipelines/macro.py 调算后插入报告。
联邦基金利率为静态常量(FOMC 调整时手动更新)。
"""
import logging
from typing import Any

from investbrief.market.base import stat_grid_html

logger = logging.getLogger(__name__)

# 联邦基金利率目标区间上限(FOMC 调整时更新)
FED_FUNDS_RATE = 5.25


def fetch_overseas_data(ak_client, fed_rate: float = FED_FUNDS_RATE) -> dict[str, Any]:
    """从 akshare 组装外围卡数据。任一接口失败该键为 None(渲染降级)。

    fed_rate: 联邦基金利率目标区间上限(%),默认 FED_FUNDS_RATE 常量;
              可由 config.json 的 fed_funds_rate 字段覆盖(FOMC 调整时改配置即可)。
    """
    data: dict[str, Any] = {"fed_rate": fed_rate}
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
    """涨跌幅 → (显示文本, css class)。class 命中 styles.py 的 .pos/.neg/.neutral。"""
    if change is None:
        return ("-", "neutral")
    sign = "+" if change > 0 else ""
    cls = "pos" if change > 0 else "neg" if change < 0 else "neutral"
    return (f"{sign}{change:.2f}%", cls)


def render_overseas_card(data: dict[str, Any]) -> str:
    """渲染外围环境紧凑卡片。缺失指标降级为 '-'。布局用 table(Outlook 兼容)。"""
    fed = data.get("fed_rate")
    us_10y = data.get("us_10y")
    sp = data.get("sp500") or {}
    usdcny = data.get("usdcny")

    sp_point = sp.get("point") if isinstance(sp, dict) else None
    sp_chg_txt, sp_cls = _fmt_change(sp.get("change") if isinstance(sp, dict) else None)

    def _cell(label: str, value, suffix: str = "", value_class: str = "") -> str:
        if isinstance(value, (int, float)):
            val_str = f"{value:.2f}{suffix}"
        else:
            val_str = str(value) if value is not None else "-"
        cls = f" {value_class}" if value_class else ""
        return (
            f'<td class="stat" valign="top"><div class="stat-label">{label}</div>'
            f'<div class="stat-value{cls}">{val_str}</div></td>'
        )

    cells = [
        _cell("美联储利率", fed, "%"),
        _cell("美债10Y", us_10y, "%"),
        _cell("标普500", sp_point),
        _cell("标普涨跌", sp_chg_txt, value_class=sp_cls),
        _cell("美元/人民币", usdcny),
    ]
    grid = stat_grid_html(cells, per_row=3)

    return f'''
    <div class="section">
      <div class="section-head">
        <span class="kicker">OVERSEAS</span>
        <h2 class="section-title">外围环境</h2>
      </div>
      <div class="card">
        <div class="card-head">影响 A 股的外围信号</div>
        <div class="card-body">
          {grid}
        </div>
      </div>
    </div>'''
