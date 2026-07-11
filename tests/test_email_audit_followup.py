"""邮件体检 followup 回归测试(CPI 数据源切换 etc.)。"""
import pandas as pd


def test_update_cpi_uses_nbs_monthly(monkeypatch, tmp_path):
    """CPI 改用国家统计局月度接口(macro_china_cpi),数据到 2026-06 而非 yearly 的 2025-08。

    月份「2026年06月份」解析为「2026-06」;同比取「全国-同比增长」。
    """
    from investbrief.data import cn_data as cn_mod
    from investbrief.data.cn_data import CNData

    fake = pd.DataFrame([
        {"月份": "2026年06月份", "全国-同比增长": 1.0},
        {"月份": "2026年05月份", "全国-同比增长": 1.2},
        {"月份": "2025年08月份", "全国-同比增长": 0.0},
    ])
    monkeypatch.setattr(cn_mod.ak, "macro_china_cpi", lambda: fake)

    d = CNData(db_path=str(tmp_path / "t.db"))
    d._update_cpi()
    rows = d.query(
        "SELECT date, value FROM macro_data WHERE indicator='CPI' AND country='cn' "
        "ORDER BY date DESC LIMIT 3")
    assert rows.iloc[0]["date"] == "2026-06"           # "2026年06月份" → "2026-06"
    assert abs(rows.iloc[0]["value"] - 1.0) < 1e-6
    dates = rows["date"].tolist()
    assert all("年" not in x for x in dates)            # 全部规范化为 YYYY-MM
    assert "2026-05" in dates
