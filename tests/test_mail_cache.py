# tests/test_mail_cache.py
"""邮件日级缓存层单测：make_key / get_cache / set_cache。无网络。"""
from investbrief.core import mail_cache


def test_make_key_macro_picks_用户无关():
    assert mail_cache.make_key("macro", "2026-07-10") == "macro_2026-07-10"
    assert mail_cache.make_key("picks", "2026-07-10") == "picks_2026-07-10"


def test_make_key_holdings_含持仓指纹且顺序无关():
    h1 = [{"symbol": "AMD", "market": "us"}, {"symbol": "002371", "market": "cn"}]
    h2 = [{"symbol": "002371", "market": "cn"}, {"symbol": "AMD", "market": "us"}]  # 顺序不同
    k1 = mail_cache.make_key("holdings", "2026-07-10", "a@b.com", h1)
    k2 = mail_cache.make_key("holdings", "2026-07-10", "a@b.com", h2)
    assert k1 == k2  # sorted(symbol)，顺序无关
    assert k1.startswith("holdings_2026-07-10_a@b.com_")


def test_make_key_holdings_持仓变则指纹变():
    base = [{"symbol": "AMD"}, {"symbol": "NVDA"}]
    k_base = mail_cache.make_key("holdings", "2026-07-10", "a@b.com", base)
    # 加一只
    k_add = mail_cache.make_key("holdings", "2026-07-10", "a@b.com", base + [{"symbol": "TSLA"}])
    # 换一只
    k_swap = mail_cache.make_key("holdings", "2026-07-10", "a@b.com", [{"symbol": "AMD"}, {"symbol": "MU"}])
    assert k_add != k_base
    assert k_swap != k_base


def test_make_key_holdings_含market_type():
    """同 symbol 不同 market/type → 指纹变（market/type 入指纹）。"""
    h_us = [{"symbol": "AMD", "market": "us", "type": "stock"}]
    h_cn = [{"symbol": "AMD", "market": "cn", "type": "stock"}]
    h_etf = [{"symbol": "AMD", "market": "us", "type": "etf"}]
    k_us = mail_cache.make_key("holdings", "2026-07-10", "a@b.com", h_us)
    assert mail_cache.make_key("holdings", "2026-07-10", "a@b.com", h_cn) != k_us
    assert mail_cache.make_key("holdings", "2026-07-10", "a@b.com", h_etf) != k_us


def test_make_key_holdings_缺email抛错():
    import pytest
    with pytest.raises(ValueError):
        mail_cache.make_key("holdings", "2026-07-10", None, [{"symbol": "AMD"}])
    with pytest.raises(ValueError):
        mail_cache.make_key("holdings", "2026-07-10", "", [{"symbol": "AMD"}])


def test_get_set_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(mail_cache, "CACHE_DIR", tmp_path)
    assert mail_cache.get_cache("missing_key") is None  # miss
    mail_cache.set_cache("k1", "<html>hello</html>")
    assert mail_cache.get_cache("k1") == "<html>hello</html>"


def test_get_cache_读失败回退none(tmp_path, monkeypatch):
    """缓存文件不可读 → 返回 None（不抛）。"""
    monkeypatch.setattr(mail_cache, "CACHE_DIR", tmp_path)
    p = tmp_path / "bad.html"
    p.write_text("ok")
    p.chmod(0o000)  # 不可读
    try:
        assert mail_cache.get_cache("bad") is None
    finally:
        p.chmod(0o644)  # 恢复，免影响后续
