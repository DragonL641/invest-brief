from unittest.mock import patch, MagicMock

from investbrief.datasources import multpl

# multpl 返回的 HTML 表格片段（含 %、千位逗号、内部 en-space U+2002）
# 注意："1\u200234.5" 在 Python 字符串里 \u2002 解析为 en-space，
# 模拟 multpl 真实响应里数值内部的 en-space——ASCII 空格 replace 会漏，必须 regex 清。
_HTML = """
<table><thead><tr><th>Date</th><th>Value</th></tr></thead><tbody>
<tr><td>Jan 1, 2024</td><td>31.5%</td></tr>
<tr><td>Feb 1, 2024</td><td> 32.1%</td></tr>
<tr><td>Mar 1, 2024</td><td>1,234.5</td></tr>
<tr><td>Apr 1, 2024</td><td>1\u200234.5</td></tr>
</tbody></table>
"""


def test_fetch_multpl_series_parses_cleans_sorts():
    resp = MagicMock(status_code=200, text=_HTML)
    with patch("investbrief.datasources.multpl.requests.get", return_value=resp) as g:
        df = multpl.fetch_multpl_series("/shiller-pe")
    assert list(df.columns) == ["date", "value"]
    assert len(df) == 4
    # 清洗：% / 前导空格 / 千位逗号 / 内部 en-space 去除，转 float
    # 最后一项 1<ensp>34.5 -> 134.5（验证 en-space 内部清洗，不是丢行）
    assert df["value"].tolist() == [31.5, 32.1, 1234.5, 134.5]
    # 升序
    assert df["date"].iloc[0] < df["date"].iloc[-1]
    # 传 path 进 URL
    assert "/shiller-pe/table/by-month" in g.call_args[0][0]


def test_fetch_multpl_series_raises_on_http_error():
    resp = MagicMock(status_code=403, text="")
    resp.raise_for_status = MagicMock(side_effect=Exception("403"))
    with patch("investbrief.datasources.multpl.requests.get", return_value=resp):
        try:
            multpl.fetch_multpl_series("/shiller-pe")
            assert False, "should raise"
        except Exception:
            pass

_GARBAGE_HTML = """
<table><thead><tr><th>Date</th><th>Value</th></tr></thead><tbody>
<tr><td>Jan 1, 2024</td><td>N/A</td></tr>
<tr><td>not-a-date</td><td>---</td></tr>
</tbody></table>
"""


def test_fetch_multpl_series_empty_on_all_garbage():
    """所有 Value 都无法解析 -> dropna 后空 DataFrame（不抛异常）。"""
    resp = MagicMock(status_code=200, text=_GARBAGE_HTML)
    with patch("investbrief.datasources.multpl.requests.get", return_value=resp):
        df = multpl.fetch_multpl_series("/shiller-pe")
    assert list(df.columns) == ["date", "value"]
    assert len(df) == 0
