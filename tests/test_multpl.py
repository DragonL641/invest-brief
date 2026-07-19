from unittest.mock import patch, MagicMock

from investbrief.datasources import multpl


# multpl 返回的 HTML 表格片段（含 %、en-space  、千位逗号）
_HTML = """
<table><thead><tr><th>Date</th><th>Value</th></tr></thead><tbody>
<tr><td>Jan 1, 2024</td><td>31.5%</td></tr>
<tr><td>Feb 1, 2024</td><td> 32.1%</td></tr>
<tr><td>Mar 1, 2024</td><td>1,234.5</td></tr>
</tbody></table>
"""


def test_fetch_multpl_series_parses_cleans_sorts():
    resp = MagicMock(status_code=200, text=_HTML)
    with patch("investbrief.datasources.multpl.requests.get", return_value=resp) as g:
        df = multpl.fetch_multpl_series("/shiller-pe")
    assert list(df.columns) == ["date", "value"]
    assert len(df) == 3
    # 清洗：% / en-space / 逗号 去除，转 float
    assert df["value"].tolist() == [31.5, 32.1, 1234.5]
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
