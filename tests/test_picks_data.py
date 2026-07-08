# tests/test_picks_data.py
"""picks.data: 归一化纯函数 normalize_fundamentals / normalize_valuation(不触网)。"""
from investbrief.picks import data


def test_normalize_fundamentals_maps_fields():
    raw = {"净资产收益率(加权)": "20.5", "销售毛利率": "40.1",
           "营业总收入同比增长率": "15.0", "净利润同比增长率": "18.0",
           "资产负债率": "35.0"}
    out = data.normalize_fundamentals(raw)
    assert out["roe"] == 0.205
    assert out["gross_margin"] == 0.401
    assert out["revenue_yoy"] == 0.15
    assert out["profit_yoy"] == 0.18
    assert out["debt_ratio"] == 0.35


def test_normalize_fundamentals_missing_keys_safe():
    out = data.normalize_fundamentals({})
    assert out.get("roe") is None


def test_normalize_fundamentals_fcf_positive_from_cashflow():
    """TODO C: 每股经营现金流 > 0 → fcf_positive True;负值 → False;缺失 → 不设。"""
    out_pos = data.normalize_fundamentals({"每股经营现金流": "0.5"})
    assert out_pos.get("fcf_positive") is True

    out_neg = data.normalize_fundamentals({"每股经营现金流": "-0.27"})
    assert out_neg.get("fcf_positive") is False

    out_absent = data.normalize_fundamentals({"roe": "10"})
    assert "fcf_positive" not in out_absent

    # 空字符串/破折号视同缺失
    out_dash = data.normalize_fundamentals({"每股经营现金流": "-"})
    assert "fcf_positive" not in out_dash


def test_normalize_fundamentals_fcf_from_english_alias():
    """get_financial_indicators 已把 cashflow 转为 operating_cashflow_per_share
    (英文 key),normalize 应能识别。"""
    out = data.normalize_fundamentals({"operating_cashflow_per_share": 1.2})
    assert out.get("fcf_positive") is True


def test_count_profitable_years_basic():
    """TODO B 纯函数: > 0 的年数。None/NaN/0/负值不计入。"""
    assert data.count_profitable_years({}) == 0
    assert data.count_profitable_years({"2020": 1.0, "2021": 2.0, "2022": 0.5}) == 3
    assert data.count_profitable_years({"2020": 1.0, "2021": -0.5, "2022": 0.0}) == 1
    # None / NaN / 非数 都不计入
    assert data.count_profitable_years({"2020": None, "2021": float("nan")}) == 0
    assert data.count_profitable_years({"2020": "abc"}) == 0
    # 全负
    assert data.count_profitable_years({"2020": -1.0, "2021": -2.0}) == 0


def test_cn_amount_to_float_parses_suffixes():
    """TODO B 辅助: CN 金额简写(亿/万/纯数字/负值/破折号)。"""
    assert data._cn_amount_to_float("1.47亿") == 1.47e8
    assert data._cn_amount_to_float("5000万") == 5e7
    assert data._cn_amount_to_float("123.45") == 123.45
    assert data._cn_amount_to_float("-0.5亿") == -5e7
    # 缺失值
    import math
    assert math.isnan(data._cn_amount_to_float("-"))
    assert math.isnan(data._cn_amount_to_float(""))
    assert math.isnan(data._cn_amount_to_float(None))


# ---- C3: 主力资金流因子数据层 ----

def test_fetch_flow_us_returns_none():
    """C3: US 无等价免费源,直接返回 None(不触网)。"""
    assert data.fetch_flow("AAPL", "us", days=5) is None


def test_fetch_flow_cn_averages_main_pct(monkeypatch):
    """C3: CN 用 akshare 近 N 日「主力净流入-净占比」均值。"""
    import pandas as pd
    fake_df = pd.DataFrame({
        "日期": ["2026-07-01", "2026-07-02", "2026-07-03"],
        "主力净流入-净占比": [10.0, -5.0, 8.0],
    })

    class _FakeAK:
        def get_stock_fund_flow_history(self, symbol, days=5):
            return fake_df

    monkeypatch.setattr(
        "investbrief.datasources.akshare.AKShareClient", lambda: _FakeAK())
    # 跳过缓存(测试环境无 init_cache)
    monkeypatch.setattr(data, "cache", lambda: None)

    v = data.fetch_flow("600519", "cn", days=3)
    assert v is not None
    assert abs(v - (10.0 - 5.0 + 8.0) / 3) < 0.01


def test_fetch_flow_cn_empty_df_returns_none(monkeypatch):
    class _FakeAK:
        def get_stock_fund_flow_history(self, symbol, days=5):
            return None

    monkeypatch.setattr(
        "investbrief.datasources.akshare.AKShareClient", lambda: _FakeAK())
    monkeypatch.setattr(data, "cache", lambda: None)
    assert data.fetch_flow("600519", "cn", days=5) is None


# ---- 跨日历史缓存(FactorCache TTL=1 天) ----

def test_fetch_history_cache_hit_skips_network(monkeypatch, tmp_path):
    """跨日缓存命中(TTL=1 天,且已含今天 bar)→ 不调 _do_fetch_history。"""
    import pandas as pd
    data._hist_mem.clear()
    data.init_cache(str(tmp_path / "picks.db"))
    today = pd.Timestamp.now().normalize()
    cached = pd.DataFrame(
        {"close": [10.0, 11.0], "volume": [1e6, 2e6]},
        index=pd.to_datetime(["2024-01-01", today]),
    )
    data.cache().set_history("hist:cn:600519", cached, ttl_days=1)

    network_calls: list = []
    monkeypatch.setattr(data, "_do_fetch_history",
                        lambda *a, **k: network_calls.append(a) or pd.DataFrame())
    got = data.fetch_history("600519", "cn", days=250)
    assert network_calls == []          # 命中缓存,零网络
    assert len(got) == 2
    assert float(got["close"].iloc[-1]) == 11.0
    data._hist_mem.clear()


def test_fetch_history_miss_falls_back_to_network(monkeypatch, tmp_path):
    """缓存未命中(无 fresh 条目)→ 调 _do_fetch_history 全量拉 + 写缓存。"""
    import pandas as pd
    data._hist_mem.clear()
    data.init_cache(str(tmp_path / "picks.db"))
    fetched = pd.DataFrame(
        {"close": [10.0, 11.0, 12.0]},
        index=pd.to_datetime(["2024-01-01", "2024-01-02", "2024-01-03"]),
    )
    monkeypatch.setattr(data, "_do_fetch_history", lambda s, m, days: fetched)
    got = data.fetch_history("600519", "cn", days=250)
    assert len(got) == 3
    # 写入跨日缓存(后续运行命中)
    assert data.cache().get_history("hist:cn:600519") is not None
    data._hist_mem.clear()


def test_fetch_history_mem_cache_short_circuits(monkeypatch, tmp_path):
    """_hist_mem(进程内)优先:命中则不查 FactorCache 也不触网。"""
    import pandas as pd
    data.init_cache(str(tmp_path / "picks.db"))
    data._hist_mem.clear()
    data._hist_mem["hist:cn:X"] = pd.DataFrame(
        {"close": [42.0]}, index=pd.to_datetime(["2024-01-01"]))
    network_calls: list = []
    monkeypatch.setattr(data, "_do_fetch_history",
                        lambda *a, **k: network_calls.append(a) or pd.DataFrame())
    got = data.fetch_history("X", "cn", days=250)
    assert network_calls == []
    assert float(got["close"].iloc[0]) == 42.0
    data._hist_mem.clear()
