"""CN provider QVIX 情绪指标渲染。render_section 接收 sentiment 参数(渲染纯函数,network 由 pipeline 预取)。"""
from investbrief.market.cn.provider import CNMarketProvider


def test_render_section_includes_qvix_when_present():
    provider = CNMarketProvider()
    html = provider.render_section(
        {"asset_performance": [], "monetary_policy": {}, "economic_calendar": []},
        {"color_up": "#e74c3c", "color_down": "#27ae60"},
        sentiment={"qvix_50": 19.14, "qvix_300": 21.09},
    )
    assert "恐慌指数" in html or "QVIX" in html
    assert "19.14" in html and "21.09" in html


def test_render_section_omits_qvix_when_empty():
    """sentiment=None(默认)时不渲染 QVIX 卡,且不触发 network。"""
    provider = CNMarketProvider()
    html = provider.render_section(
        {"asset_performance": [], "monetary_policy": {}, "economic_calendar": []},
        {"color_up": "#e74c3c", "color_down": "#27ae60"},
    )
    assert "QVIX" not in html      # 无数据则不渲染该卡
