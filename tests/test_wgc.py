from unittest.mock import patch, MagicMock

from investbrief.datasources import wgc

_OK = {
    "chartData": {
        "categories": ["Q1 2012", "Q2 2012", "Q4 2025"],
        "data": [926.78, 1012.53, 1706.23],
        "asOfDate": "2025-12-31",
    }
}


def test_fetch_gold_aisc_parses_series():
    resp = MagicMock(status_code=200)
    resp.json.return_value = _OK
    resp.raise_for_status = MagicMock()
    with patch("investbrief.datasources.wgc.requests.get", return_value=resp):
        series = wgc.fetch_gold_aisc()
    assert series == [("Q1 2012", 926.78), ("Q2 2012", 1012.53), ("Q4 2025", 1706.23)]


def test_fetch_gold_aisc_returns_none_on_http_error():
    resp = MagicMock(status_code=500)
    resp.raise_for_status = MagicMock(side_effect=Exception("500"))
    with patch("investbrief.datasources.wgc.requests.get", return_value=resp):
        assert wgc.fetch_gold_aisc() is None


def test_fetch_gold_aisc_returns_none_on_malformed_json():
    resp = MagicMock(status_code=200)
    resp.json.return_value = {"nope": {}}
    resp.raise_for_status = MagicMock()
    with patch("investbrief.datasources.wgc.requests.get", return_value=resp):
        assert wgc.fetch_gold_aisc() is None
