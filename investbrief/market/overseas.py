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
    """从 akshare 组装外围卡数据(6 项)。任一接口失败该键为 None(渲染降级)。

    fed_rate: 联邦基金利率目标区间上限(%),默认 FED_FUNDS_RATE 常量;
              可由 config.json 的 fed_funds_rate 字段覆盖(FOMC 调整时改配置即可)。
    """
    data: dict[str, Any] = {"fed_rate": fed_rate}

    def _safe(key: str, fn):
        try:
            data[key] = fn()
        except Exception as e:
            logger.warning(f"overseas {key} failed: {e}")
            data[key] = None

    _safe("us_10y", ak_client.get_us_10y_quote)
    _safe("sp500", ak_client.get_sp500_quote)
    _safe("nasdaq", ak_client.get_nasdaq_quote)
    _safe("usdcny", ak_client.get_usdcny_quote)
    _safe("wti", ak_client.get_wti_quote)
    return data


def _fmt_pct(change: float | None) -> tuple[str, str]:
    """百分比涨跌 → (显示文本, css class)。class 命中 styles.py 的 .pos/.neg/.neutral。"""
    if change is None:
        return ("", "")
    sign = "+" if change > 0 else ""
    cls = "pos" if change > 0 else "neg" if change < 0 else "neutral"
    return (f"{sign}{change:.2f}%", cls)


def _fmt_bp(change: float | None) -> tuple[str, str]:
    """收益率变动(百分点差)→ bp → (显示文本, css class)。"""
    if change is None:
        return ("", "")
    bps = round(change * 100)
    sign = "+" if bps > 0 else ""
    cls = "pos" if bps > 0 else "neg" if bps < 0 else "neutral"
    return (f"{sign}{bps}bp", cls)


def render_overseas_card(data: dict[str, Any]) -> str:
    """渲染外围环境紧凑卡片(6 项 3×2)。缺失指标降级为 '-'。布局用 table(Outlook 兼容)。"""
    fed = data.get("fed_rate")
    us_10y = data.get("us_10y") or {}
    sp = data.get("sp500") or {}
    nsdq = data.get("nasdaq") or {}
    usdcny = data.get("usdcny") or {}
    wti = data.get("wti") or {}

    def _cell(label: str, value, *, value_suffix: str = "",
              delta_text: str = "", delta_cls: str = "", sub: str = "") -> str:
        if isinstance(value, (int, float)):
            val_str = f"{value:.2f}{value_suffix}"
        elif value is not None:
            val_str = str(value)
        else:
            val_str = "-"
        delta_html = f'<div class="stat-delta {delta_cls}">{delta_text}</div>' if delta_text else ""
        sub_html = f'<div class="stat-sub">{sub}</div>' if sub else ""
        return (
            f'<td class="stat" valign="top">'
            f'<div class="stat-label">{label}</div>'
            f'<div class="stat-value">{val_str}</div>'
            f'{delta_html}{sub_html}</td>'
        )

    u10_txt, u10_cls = _fmt_bp(us_10y.get("change") if isinstance(us_10y, dict) else None)
    sp_txt, sp_cls = _fmt_pct(sp.get("change") if isinstance(sp, dict) else None)
    ns_txt, ns_cls = _fmt_pct(nsdq.get("change") if isinstance(nsdq, dict) else None)
    wti_txt, wti_cls = _fmt_pct(wti.get("change") if isinstance(wti, dict) else None)

    cells = [
        _cell("美联储利率", fed, value_suffix="%", sub="目标区间上限"),
        _cell("美债10Y", us_10y.get("value") if isinstance(us_10y, dict) else None,
              value_suffix="%", delta_text=u10_txt, delta_cls=u10_cls),
        _cell("标普500", sp.get("point") if isinstance(sp, dict) else None,
              delta_text=sp_txt, delta_cls=sp_cls),
        _cell("纳斯达克", nsdq.get("point") if isinstance(nsdq, dict) else None,
              delta_text=ns_txt, delta_cls=ns_cls),
        _cell("美元/人民币", usdcny.get("value") if isinstance(usdcny, dict) else None,
              sub="在岸即期"),
        _cell("WTI原油", wti.get("point") if isinstance(wti, dict) else None,
              delta_text=wti_txt, delta_cls=wti_cls),
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
