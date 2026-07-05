"""strategy_loader: YAML load + cache + validation."""
import pytest

from investbrief.core import strategy_loader


def test_load_strategy_returns_dict(tmp_path, monkeypatch):
    """load_strategy reads <name>.yaml from STRATEGIES_DIR and returns a dict."""
    fake_dir = tmp_path
    (fake_dir / "demo.yaml").write_text("foo: bar\nlist: [1, 2]\n", encoding="utf-8")
    monkeypatch.setattr(strategy_loader, "STRATEGIES_DIR", fake_dir)
    strategy_loader.load_strategy.cache_clear()
    data = strategy_loader.load_strategy("demo")
    assert data == {"foo": "bar", "list": [1, 2]}


def test_load_strategy_caches(tmp_path, monkeypatch):
    """Second call returns cached (no re-read even if file changes)."""
    fake_dir = tmp_path
    (fake_dir / "demo.yaml").write_text("v: 1\n", encoding="utf-8")
    monkeypatch.setattr(strategy_loader, "STRATEGIES_DIR", fake_dir)
    strategy_loader.load_strategy.cache_clear()
    assert strategy_loader.load_strategy("demo")["v"] == 1
    # Overwrite file — cache should still return old value
    (fake_dir / "demo.yaml").write_text("v: 2\n", encoding="utf-8")
    assert strategy_loader.load_strategy("demo")["v"] == 1
    strategy_loader.load_strategy.cache_clear()
    assert strategy_loader.load_strategy("demo")["v"] == 2


def test_load_strategy_missing_file_raises(tmp_path, monkeypatch):
    monkeypatch.setattr(strategy_loader, "STRATEGIES_DIR", tmp_path)
    strategy_loader.load_strategy.cache_clear()
    with pytest.raises(FileNotFoundError):
        strategy_loader.load_strategy("nonexistent")


def test_load_strategy_empty_file_raises(tmp_path, monkeypatch):
    (tmp_path / "empty.yaml").write_text("", encoding="utf-8")
    monkeypatch.setattr(strategy_loader, "STRATEGIES_DIR", tmp_path)
    strategy_loader.load_strategy.cache_clear()
    with pytest.raises(ValueError):
        strategy_loader.load_strategy("empty")
