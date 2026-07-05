# tests/test_picks_profiles.py
"""picks.profiles: 加载 pick_profiles.yaml + 校验三 profile 必填结构。"""
import pytest

from investbrief.picks import profiles


def test_loads_three_profiles():
    data = profiles.load_profiles()
    assert set(data) >= {"swing", "medium", "long"}


def test_each_profile_has_required_keys():
    for name, p in profiles.load_profiles().items():
        assert "universe" in p, f"{name} missing universe"
        assert "factors" in p and p["factors"], f"{name} missing factors"
        assert "top_n" in p, f"{name} missing top_n"
        assert abs(sum(f["weight"] for f in p["factors"].values()) - 1.0) < 1e-6, \
            f"{name} factor weights must sum to 1.0"


def test_unknown_standardize_rejected(tmp_path, monkeypatch):
    """非 rank_percentile 的 standardize 当前不支持,应明确报错。"""
    import yaml
    bad = {"profiles": {"swing": {"universe": {}, "factors": {"x": {"weight": 1.0}},
                                  "top_n": 1, "standardize": "zscore",
                                  "industry_neutralize": False}}}
    fake = tmp_path / "bad.yaml"
    fake.write_text(yaml.safe_dump(bad), encoding="utf-8")

    class _FakeLoader:
        @staticmethod
        def load_strategy(name):
            if name == "pick_profiles":
                return yaml.safe_load(fake.read_text(encoding="utf-8"))
            raise FileNotFoundError
    monkeypatch.setattr(profiles, "_strategy", _FakeLoader)
    profiles.load_profiles.cache_clear()
    with pytest.raises(ValueError):
        profiles.load_profiles()


def test_missing_profile_rejected(tmp_path, monkeypatch):
    """缺一个必需 profile → ValueError。"""
    import yaml
    raw = yaml.safe_load(__import__("pathlib").Path(
        "investbrief/strategies/pick_profiles.yaml").read_text(encoding="utf-8"))
    del raw["profiles"]["long"]   # 删一个
    bad = tmp_path / "bad.yaml"
    bad.write_text(yaml.safe_dump(raw), encoding="utf-8")

    class _FakeLoader:
        @staticmethod
        def load_strategy(name):
            return yaml.safe_load(bad.read_text(encoding="utf-8"))
    monkeypatch.setattr(profiles, "_strategy", _FakeLoader)
    profiles.load_profiles.cache_clear()
    with pytest.raises(ValueError):
        profiles.load_profiles()


def test_universe_numeric_thresholds_are_not_strings():
    """Regression: PyYAML parses bare exponent notation like `1.0e8` as a str
    (not float), which crashes coarse_filter's `>=` comparison. Universe
    thresholds must load as int/float — use plain integers in the YAML."""
    import yaml
    from pathlib import Path
    raw = yaml.safe_load(
        Path("investbrief/strategies/pick_profiles.yaml").read_text(encoding="utf-8"))
    swing_u = raw["profiles"]["swing"]["universe"]
    medium_u = raw["profiles"]["medium"]["universe"]
    assert isinstance(swing_u["min_turnover_cn"], (int, float)), \
        f"min_turnover_cn must be numeric, got {type(swing_u['min_turnover_cn']).__name__}"
    assert isinstance(swing_u["min_turnover_us"], (int, float)), \
        f"min_turnover_us must be numeric, got {type(swing_u['min_turnover_us']).__name__}"
    band = medium_u["market_cap_cn"]
    assert all(isinstance(x, (int, float)) for x in band), \
        f"market_cap_cn entries must be numeric, got {band!r}"
