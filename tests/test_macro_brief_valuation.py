from investbrief.market.macro_brief import serialize_macro_context


def test_serialize_includes_erp_in_overseas():
    overseas = {"美联储利率": 5.25, "ERP": -1.07, "Shiller PE": 32.0, "ERP近10年分位": 35.0}
    txt = serialize_macro_context(overseas, {}, [])
    assert "ERP" in txt
    assert "Shiller PE" in txt


def test_serialize_includes_gold_valuation_section():
    overseas = {"美联储利率": 5.25}
    gold_v = {"tips_yield": 2.35, "aisc": 1706.23, "premium_pct": 105.1}
    txt = serialize_macro_context(overseas, {}, [], gold_valuation=gold_v)
    assert "黄金估值" in txt
    assert "2.35" in txt
    assert "1706" in txt


def test_serialize_omits_gold_section_when_empty():
    txt = serialize_macro_context({"美联储利率": 5.25}, {}, [], gold_valuation=None)
    assert "黄金估值" not in txt


def test_serialize_includes_dividend_in_cn():
    cn = {"monetary_policy": {"DIVIDEND_YIELD_930955": 4.94, "股息率-CNBOND spread": 3.2}}
    txt = serialize_macro_context({}, cn, [])
    assert "4.94" in txt
