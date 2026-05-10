# Data Refresh Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Refactor data refresh from all-or-nothing bundle to per-section isolation with independent caching, error handling, and frontend per-card status/retry.

**Architecture:** Backend splits `fetch_all()` into per-section fetches with independent Redis cache keys and TTLs. New `refresh/{section}` endpoint enables single-section retry. Frontend replaces monolithic loading state with per-section status (loading/ok/error) and inline retry buttons.

**Tech Stack:** Python 3 / FastAPI / Redis, React 19 / TypeScript / Ant Design 6

---

## Task 1: Define section registry and cache helpers

**Files:**
- Modify: `investbrief/web/services/cache.py`
- Modify: `investbrief/web/services/data_fetcher.py` (lines 42-49: replace `_public_keys`/`_private_keys`)

- [ ] **Step 1: Add section-level cache helpers to cache.py**

Append these functions after the existing `set_refresh_lock` function:

```python
# --- Section-level cache operations ---

def get_section_cached(redis_client, market: str, section: str, uid: str | None = None) -> dict | None:
    """Get cached data for a single section."""
    key = _section_key(market, section, uid)
    return get_cached(redis_client, key)


def set_section_cached(redis_client, market: str, section: str, value: dict,
                       ttl: int, uid: str | None = None):
    """Cache data for a single section with its TTL."""
    key = _section_key(market, section, uid)
    set_cached(redis_client, key, value, ttl_seconds=ttl)


def invalidate_section(redis_client, market: str, section: str, uid: str | None = None):
    """Invalidate a single section's cache."""
    key = _section_key(market, section, uid)
    invalidate(redis_client, key)


def can_section_refresh(redis_client, market: str, section: str, uid: str | None = None) -> bool:
    """Check if a per-section refresh lock is free."""
    key = _section_refresh_lock_key(market, section, uid)
    return redis_client.get(key) is None


def set_section_refresh_lock(redis_client, market: str, section: str,
                             uid: str | None = None, ttl: int = 30):
    """Set a per-section refresh lock."""
    key = _section_refresh_lock_key(market, section, uid)
    redis_client.setex(key, ttl, "1")


def _section_key(market: str, section: str, uid: str | None) -> str:
    """Build cache key for a section. News uses language suffix."""
    if uid:
        return f"market:{market}:user:{uid}:section:{section}"
    return f"market:{market}:section:{section}"


def _section_refresh_lock_key(market: str, section: str, uid: str | None) -> str:
    if uid:
        return f"market:{market}:user:{uid}:section:{section}:refresh_lock"
    return f"market:{market}:section:{section}:refresh_lock"
```

- [ ] **Step 2: Add section registry to data_fetcher.py**

Replace `_public_keys()` and `_private_keys()` (lines 42-49) with:

```python
import time as _time

SECTION_CONFIG = {
    "us": {
        "public": {
            "indices":              {"ttl": 300,   "method": "get_indices"},
            "economic_calendar":    {"ttl": 14400, "method": "get_economic_calendar"},
            "premarket_movers":     {"ttl": 300,   "method": "get_premarket_movers"},
            "earnings_calendar":    {"ttl": 14400, "method": "get_earnings_calendar"},
            "congressional_trades": {"ttl": 14400, "method": "get_congressional_trades"},
        },
        "private": {
            "holdings":             {"ttl": 600,   "method": "get_holdings_data"},
            "recommendations":      {"ttl": 1800,  "method": "get_recommendations"},
        },
    },
    "cn": {
        "public": {
            "indices":              {"ttl": 300,   "method": "get_indices"},
            "economic_calendar":    {"ttl": 14400, "method": "get_economic_calendar"},
            "dragon_tiger":         {"ttl": 3600,  "method": "get_dragon_tiger"},
            "sector_performance":   {"ttl": 1800,  "method": "get_sector_performance"},
        },
        "private": {
            "holdings":             {"ttl": 600,   "method": "get_holdings_data"},
            "recommendations":      {"ttl": 1800,  "method": "get_recommendations"},
        },
    },
}
```

- [ ] **Step 3: Commit**

```bash
git add investbrief/web/services/cache.py investbrief/web/services/data_fetcher.py
git commit -m "refactor: add section registry and per-section cache helpers"
```

---

## Task 2: Refactor providers to expose per-section fetch methods

**Files:**
- Modify: `investbrief/us/provider.py` (add `get_section_data()`, refactor `fetch_all()`)
- Modify: `investbrief/cn/provider.py` (same pattern)

- [ ] **Step 1: Add `get_section_data()` and refactor `fetch_all()` in US provider**

Add this method to `USMarketProvider` (after `__init__`):

```python
def get_section_data(self, section_name: str, **kwargs) -> list[dict]:
    """Fetch a single section's data independently."""
    from .calendar import get_upcoming_events
    from .congress import get_recent_congressional_trades

    dispatch = {
        "indices": lambda: self.get_indices(),
        "economic_calendar": lambda: get_upcoming_events(),
        "premarket_movers": lambda: self.get_premarket_movers(
            kwargs.get("holdings_symbols", [])
        ),
        "earnings_calendar": lambda: self.get_earnings_calendar(
            kwargs.get("holdings", []),
            kwargs.get("recommendations", []),
        ),
        "congressional_trades": lambda: get_recent_congressional_trades(
            tickers=kwargs.get("holdings_symbols", [])
        ),
        "holdings": lambda: self.get_holdings_data(kwargs.get("holdings", [])),
        "recommendations": lambda: self.get_recommendations_from_industries(
            kwargs.get("industries", []),
            kwargs.get("holdings_symbols", []),
        ),
    }
    fn = dispatch.get(section_name)
    if fn is None:
        raise ValueError(f"Unknown section: {section_name}")
    return fn()
```

Then replace `fetch_all()` (lines 268-292) to use it internally:

```python
def fetch_all(self, holdings: list[dict], industries: list[str],
             max_recommendations: int = 3) -> dict[str, Any]:
    """获取美股全部数据。"""
    holdings_symbols = [h["symbol"] for h in holdings]

    ctx = {
        "holdings": holdings,
        "holdings_symbols": holdings_symbols,
        "industries": industries,
    }

    # Pre-fetch recommendations and earnings which need cross-data
    recommendations = self.get_section_data("recommendations", **ctx)
    ctx["recommendations"] = recommendations

    results = {}
    for section_name in ["indices", "economic_calendar", "premarket_movers",
                         "earnings_calendar", "congressional_trades",
                         "holdings", "recommendations"]:
        if section_name == "recommendations":
            results[section_name] = recommendations
        else:
            results[section_name] = self.get_section_data(section_name, **ctx)

    return results
```

- [ ] **Step 2: Add `get_section_data()` and refactor `fetch_all()` in CN provider**

Add to `CNMarketProvider` (after `__init__`):

```python
def get_section_data(self, section_name: str, **kwargs) -> list[dict]:
    """Fetch a single section's data independently."""
    from investbrief.cn.calendar import get_upcoming_events
    from investbrief.cn.watchlist import INDUSTRY_SECTOR_NAMES

    dispatch = {
        "indices": lambda: self.get_indices(),
        "economic_calendar": lambda: get_upcoming_events(),
        "dragon_tiger": lambda: self.client.get_dragon_tiger_list(days=3),
        "sector_performance": lambda: (
            self.client.get_sector_performance(
                [INDUSTRY_SECTOR_NAMES[i] for i in kwargs.get("industries", [])
                 if i in INDUSTRY_SECTOR_NAMES]
            ) if kwargs.get("industries") else []
        ),
        "holdings": lambda: self.get_holdings_data(kwargs.get("holdings", [])),
        "recommendations": lambda: self.get_recommendations(
            kwargs.get("industries", []),
            kwargs.get("holdings_symbols", []),
            max_recommendations=kwargs.get("max_recommendations", 3),
        ),
    }
    fn = dispatch.get(section_name)
    if fn is None:
        raise ValueError(f"Unknown section: {section_name}")
    return fn()
```

Replace `fetch_all()` (lines 295-319):

```python
def fetch_all(self, holdings: list[dict], industries: list[str],
             max_recommendations: int = 3) -> dict[str, Any]:
    """获取 A 股全部数据。"""
    holdings_symbols = [h["symbol"] for h in holdings]

    ctx = {
        "holdings": holdings,
        "holdings_symbols": holdings_symbols,
        "industries": industries,
        "max_recommendations": max_recommendations,
    }

    results = {}
    for section_name in ["indices", "economic_calendar", "dragon_tiger",
                         "sector_performance", "holdings", "recommendations"]:
        results[section_name] = self.get_section_data(section_name, **ctx)

    return results
```

- [ ] **Step 3: Commit**

```bash
git add investbrief/us/provider.py investbrief/cn/provider.py
git commit -m "refactor: add get_section_data() to providers, fetch_all uses it internally"
```

---

## Task 3: Rewrite data_fetcher.py with per-section isolation

**Files:**
- Modify: `investbrief/web/services/data_fetcher.py` (major rewrite of `get_market_data`, `refresh_market`, remove `_fetch_and_cache_public`/`_fetch_and_cache_user`)

- [ ] **Step 1: Add `_fetch_section()` helper**

Add after `SECTION_CONFIG`:

```python
def _fetch_section(redis_client, market: str, section_name: str,
                   provider, uid: str | None = None, **kwargs) -> dict:
    """Fetch one section: check cache -> fetch -> cache result. Returns section result dict."""
    config = SECTION_CONFIG[market]
    is_private = section_name in config.get("private", {})
    section_cfg = config["private" if is_private else "public"][section_name]
    ttl = section_cfg["ttl"]

    # Check cache
    cached = get_section_cached(redis_client, market, section_name, uid)
    if cached is not None:
        return {"data": cached["data"], "status": "cached",
                "updated_at": cached["updated_at"]}

    # Fetch
    try:
        data = provider.get_section_data(section_name, **kwargs)
        data = _sanitize_floats(data)
        now = _time.strftime("%Y-%m-%dT%H:%M:%S%z")
        result = {"data": data, "updated_at": now}
        set_section_cached(redis_client, market, section_name, result, ttl, uid)
        return {"data": data, "status": "ok", "updated_at": now}
    except Exception as e:
        logger.warning(f"Section {section_name} failed for {market}: {e}", exc_info=True)
        err = _classify_error(e)
        err["section"] = section_name
        err["retryable"] = err["reason"] not in ("auth",)
        err["suggestion_key"] = f"error.suggestion.{err['reason']}"
        return {"data": None, "status": "error", "error": err, "updated_at": None}
```

- [ ] **Step 2: Rewrite `get_market_data()`**

Replace the existing `get_market_data()` (lines 129-172):

```python
def get_market_data(redis_client, market: str, user: dict) -> dict:
    provider = _create_provider(market)
    config = SECTION_CONFIG[market]
    uid = str(user["id"])
    market_cfg = user.get("markets", {}).get(market, {})
    holdings = market_cfg.get("holdings", [])
    industries = market_cfg.get("industries", [])
    holdings_symbols = [h["symbol"] if isinstance(h, dict) else h for h in holdings]

    section_kwargs = {
        "holdings": holdings,
        "holdings_symbols": holdings_symbols,
        "industries": industries,
        "recommendations": [],  # filled below if needed
    }

    sections = {}

    # Public sections
    for name in config["public"]:
        sections[name] = _fetch_section(redis_client, market, name, provider, uid=None, **section_kwargs)

    # Private sections
    for name in config["private"]:
        sections[name] = _fetch_section(redis_client, market, name, provider, uid=uid, **section_kwargs)

    # News (special: per-language cache, uses separate fetch path)
    language = user.get("language", "zh-CN")
    news_cache_key = f"market:{market}:section:news:{language}"
    news_cached = get_cached(redis_client, news_cache_key)
    if news_cached is not None:
        sections["news"] = {"data": news_cached["data"], "status": "cached",
                            "updated_at": news_cached["updated_at"]}
    else:
        sections["news"] = _fetch_news_section(redis_client, market, language,
                                                holdings_symbols, industries)

    return {"sections": sections}
```

- [ ] **Step 3: Add `_fetch_news_section()` helper**

```python
def _fetch_news_section(redis_client, market: str, language: str,
                        symbols: list[str], industries: list[str]) -> dict:
    """Fetch, translate, and cache news for a section."""
    try:
        news_items, news_errors = _fetch_news(market, symbols, industries)
        if news_items:
            translated = _translate_news(news_items[:5], language, market)
            now = _time.strftime("%Y-%m-%dT%H:%M:%S%z")
            cache_data = {"data": _sanitize_floats(translated), "updated_at": now}
            news_cache_key = f"market:{market}:section:news:{language}"
            set_cached(redis_client, news_cache_key, cache_data, ttl_seconds=3600)
            if news_errors:
                return {"data": _sanitize_floats(translated), "status": "ok",
                        "updated_at": now, "warnings": news_errors}
            return {"data": _sanitize_floats(translated), "status": "ok",
                    "updated_at": now}
        else:
            now = _time.strftime("%Y-%m-%dT%H:%M:%S%z")
            return {"data": [], "status": "ok", "updated_at": now}
    except Exception as e:
        logger.warning(f"News section failed for {market}: {e}", exc_info=True)
        err = _classify_error(e)
        err["section"] = "news"
        err["retryable"] = True
        err["suggestion_key"] = f"error.suggestion.{err['reason']}"
        return {"data": None, "status": "error", "error": err, "updated_at": None}
```

- [ ] **Step 4: Rewrite `refresh_market()` and add `refresh_section()`**

Replace `refresh_market()` (lines 218-232):

```python
def refresh_market(redis_client, market: str, user: dict) -> dict:
    if not can_refresh(redis_client, market):
        return {"status": "rate_limited"}

    set_refresh_lock(redis_client, market)

    uid = str(user["id"])
    config = SECTION_CONFIG[market]

    # Invalidate only current user's private caches + public caches + news
    for name in config["public"]:
        invalidate_section(redis_client, market, name)
    for name in config["private"]:
        invalidate_section(redis_client, market, name, uid=uid)
    for key in redis_client.scan_iter(f"market:{market}:section:news:*"):
        invalidate(redis_client, key)

    return get_market_data(redis_client, market, user)


def refresh_section(redis_client, market: str, section_name: str, user: dict) -> dict:
    """Refresh a single section and return its result."""
    config = SECTION_CONFIG[market]
    is_private = section_name in config.get("private", {})
    is_public = section_name in config.get("public", {})
    is_news = section_name == "news"

    if not is_private and not is_public and not is_news:
        return {"status": "error", "error": {"reason": "invalid_section", "detail": f"Unknown section: {section_name}"}}

    uid = str(user["id"]) if is_private else None

    if not can_section_refresh(redis_client, market, section_name, uid):
        return {"status": "rate_limited"}

    set_section_refresh_lock(redis_client, market, section_name, uid)

    # Invalidate
    if is_news:
        language = user.get("language", "zh-CN")
        news_cache_key = f"market:{market}:section:news:{language}"
        invalidate(redis_client, news_cache_key)
    else:
        invalidate_section(redis_client, market, section_name, uid)

    # Re-fetch via get_market_data and extract the section
    full = get_market_data(redis_client, market, user)
    section_result = full.get("sections", {}).get(section_name, {
        "data": None, "status": "error",
        "error": {"reason": "unknown", "detail": "Section not found in response"},
        "updated_at": None,
    })
    return {"section": section_name, **section_result}
```

- [ ] **Step 5: Remove old `_fetch_and_cache_public()` and `_fetch_and_cache_user()`**

Delete the functions `_fetch_and_cache_public` (lines 185-196) and `_fetch_and_cache_user` (lines 199-215) as they are replaced by `_fetch_section()`.

- [ ] **Step 6: Commit**

```bash
git add investbrief/web/services/data_fetcher.py
git commit -m "refactor: rewrite data_fetcher with per-section isolation and caching"
```

---

## Task 4: Update data router with new endpoints and response format

**Files:**
- Modify: `investbrief/web/routers/data.py`

- [ ] **Step 1: Update imports**

Change line 7 to also import `refresh_section`:

```python
from investbrief.web.services.data_fetcher import get_market_data, refresh_market, refresh_section
```

Remove the `get_last_updated` import (no longer used directly in router):

```python
from investbrief.web.services.cache import can_refresh
```

- [ ] **Step 2: Replace `_empty_result()` with per-section empty result**

Remove `_empty_result()` (lines 26-29). Replace with:

```python
def _error_sections(market: str, reason: str = "timeout") -> dict:
    """Return all sections in error state (used on timeout/unhandled error)."""
    from investbrief.web.services.data_fetcher import SECTION_CONFIG
    sections = {}
    all_sections = (
        list(SECTION_CONFIG.get(market, {}).get("public", {}).keys())
        + list(SECTION_CONFIG.get(market, {}).get("private", {}).keys())
        + ["news"]
    )
    for name in all_sections:
        sections[name] = {
            "data": None, "status": "error",
            "error": {"reason": reason, "detail": "", "section": name,
                      "retryable": True, "suggestion_key": f"error.suggestion.{reason}"},
            "updated_at": None,
        }
    return {"sections": sections}
```

- [ ] **Step 3: Update `get_data()` endpoint**

Replace `get_data()` (lines 32-47):

```python
@router.get("/{market}")
async def get_data(market: str, user: dict = Depends(get_current_user), redis=Depends(get_redis)):
    if market not in ("us", "cn"):
        return {"error": "invalid market"}
    loop = asyncio.get_event_loop()
    try:
        return await asyncio.wait_for(
            loop.run_in_executor(_pool, get_market_data, redis, market, user),
            timeout=FETCH_TIMEOUT,
        )
    except asyncio.TimeoutError:
        logger.warning(f"Data fetch timeout for market={market}")
        return _error_sections(market, reason="timeout")
    except Exception as e:
        logger.error(f"Data fetch error for market={market}: {e}")
        return _error_sections(market, reason="unknown")
```

- [ ] **Step 4: Update `refresh_data()` endpoint**

Replace `refresh_data()` (lines 50-65):

```python
@router.post("/{market}/refresh")
async def refresh_data(market: str, user: dict = Depends(get_current_user), redis=Depends(get_redis)):
    if market not in ("us", "cn"):
        return {"error": "invalid market"}
    loop = asyncio.get_event_loop()
    try:
        result = await asyncio.wait_for(
            loop.run_in_executor(_pool, refresh_market, redis, market, user),
            timeout=FETCH_TIMEOUT,
        )
        if result.get("status") == "rate_limited":
            from fastapi.responses import JSONResponse
            return JSONResponse(status_code=429, content={"status": "rate_limited"})
        return result
    except asyncio.TimeoutError:
        logger.warning(f"Data refresh timeout for market={market}")
        return _error_sections(market, reason="timeout")
    except Exception as e:
        logger.error(f"Data refresh error for market={market}: {e}")
        return _error_sections(market, reason="unknown")
```

- [ ] **Step 5: Add single-section refresh endpoint**

Append after `refresh_data()`:

```python
@router.post("/{market}/refresh/{section}")
async def refresh_single_section(
    market: str, section: str,
    user: dict = Depends(get_current_user), redis=Depends(get_redis),
):
    if market not in ("us", "cn"):
        return {"error": "invalid market"}
    loop = asyncio.get_event_loop()
    try:
        result = await asyncio.wait_for(
            loop.run_in_executor(_pool, refresh_section, redis, market, section, user),
            timeout=FETCH_TIMEOUT,
        )
        if result.get("status") == "rate_limited":
            from fastapi.responses import JSONResponse
            return JSONResponse(status_code=429, content={"status": "rate_limited"})
        return result
    except asyncio.TimeoutError:
        logger.warning(f"Section refresh timeout for {market}/{section}")
        return {
            "section": section, "data": None, "status": "error",
            "error": {"reason": "timeout", "detail": "", "section": section,
                      "retryable": True, "suggestion_key": "error.suggestion.timeout"},
            "updated_at": None,
        }
    except Exception as e:
        logger.error(f"Section refresh error for {market}/{section}: {e}")
        return {
            "section": section, "data": None, "status": "error",
            "error": {"reason": "unknown", "detail": str(e)[:200], "section": section,
                      "retryable": True, "suggestion_key": "error.suggestion.unknown"},
            "updated_at": None,
        }
```

- [ ] **Step 6: Update `/status` endpoint**

Replace `get_status()` (lines 18-23). Since we no longer have a single `updated_at` per market, return the most recent section's updated_at:

```python
@router.get("/status")
def get_status(redis=Depends(get_redis)):
    """Return last-updated timestamp per market (from the most recent public section)."""
    result = {}
    for market in ("us", "cn"):
        from investbrief.web.services.data_fetcher import SECTION_CONFIG
        latest = None
        for section_name in SECTION_CONFIG.get(market, {}).get("public", {}):
            cached = get_section_cached(redis, market, section_name)
            if cached and cached.get("updated_at"):
                ts = cached["updated_at"]
                if latest is None or ts > latest:
                    latest = ts
        result[market] = {"updated_at": latest}
    return result
```

Add `get_section_cached` to imports:

```python
from investbrief.web.services.cache import can_refresh, get_section_cached
```

- [ ] **Step 7: Commit**

```bash
git add investbrief/web/routers/data.py
git commit -m "feat: add per-section refresh endpoint, update response format"
```

---

## Task 5: Align frontend timeout with backend

**Files:**
- Modify: `frontend/src/api/client.ts` (line 3)

- [ ] **Step 1: Change timeout from 60s to 90s**

```typescript
const client = axios.create({ baseURL: "/api", timeout: 90000 });
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/api/client.ts
git commit -m "fix: align frontend API timeout with backend (90s)"
```

---

## Task 6: Add per-section refresh API call

**Files:**
- Modify: `frontend/src/api/data.ts`

- [ ] **Step 1: Add `refreshSection` function**

```typescript
import client from "./client";
export const getMarketData = (market: string) => client.get(`/data/${market}`);
export const refreshMarket = (market: string) => client.post(`/data/${market}/refresh`);
export const refreshSection = (market: string, section: string) => client.post(`/data/${market}/refresh/${section}`);
export const getStatus = () => client.get("/data/status");
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/api/data.ts
git commit -m "feat: add refreshSection API call"
```

---

## Task 7: Create SectionState type and SectionErrorCard component

**Files:**
- Create: `frontend/src/types/section.ts`
- Create: `frontend/src/components/SectionErrorCard.tsx`

- [ ] **Step 1: Create section types**

Create `frontend/src/types/section.ts`:

```typescript
export type SectionStatus = "idle" | "loading" | "ok" | "cached" | "error";

export interface SectionError {
  reason: string;
  detail: string;
  section: string;
  retryable: boolean;
  suggestion_key: string;
}

export interface SectionState<T = any> {
  status: SectionStatus;
  data: T | null;
  error?: SectionError;
  updatedAt?: string | null;
}
```

- [ ] **Step 2: Create SectionErrorCard component**

Create `frontend/src/components/SectionErrorCard.tsx`:

```tsx
import { useTranslation } from "react-i18next";
import { WarningFilled, ReloadOutlined, LoadingOutlined } from "@ant-design/icons";
import type { SectionError } from "../types/section";

interface Props {
  error: SectionError;
  onRetry: () => void;
  loading?: boolean;
}

export default function SectionErrorCard({ error, onRetry, loading }: Props) {
  const { t } = useTranslation();

  return (
    <div
      style={{
        background: "#111214",
        borderRadius: 16,
        padding: "32px 24px",
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        gap: 12,
        boxShadow: "0 1px 3px rgba(0,0,0,0.3)",
      }}
    >
      <WarningFilled style={{ fontSize: 24, color: "#ff4d4f" }} />
      <div style={{ color: "#8d969e", fontSize: 14, textAlign: "center" }}>
        {t(`error.suggestion.${error.reason}`, t("error.solutionUnknown"))}
      </div>
      {error.retryable && (
        <button
          onClick={onRetry}
          disabled={loading}
          style={{
            display: "flex",
            alignItems: "center",
            gap: 6,
            background: "rgba(255,255,255,0.08)",
            border: "1px solid rgba(255,255,255,0.12)",
            borderRadius: 8,
            padding: "6px 16px",
            color: "#fff",
            fontSize: 13,
            cursor: loading ? "not-allowed" : "pointer",
            opacity: loading ? 0.6 : 1,
          }}
        >
          {loading ? <LoadingOutlined /> : <ReloadOutlined />}
          {t("error.retry")}
        </button>
      )}
    </div>
  );
}
```

- [ ] **Step 3: Commit**

```bash
git add frontend/src/types/section.ts frontend/src/components/SectionErrorCard.tsx
git commit -m "feat: add SectionState types and SectionErrorCard component"
```

---

## Task 8: Rewrite DashboardPage with per-section state

**Files:**
- Modify: `frontend/src/pages/DashboardPage.tsx` (major rewrite)

- [ ] **Step 1: Update imports**

Replace the top of the file. Remove `DataErrorBanner` import, add new types and API:

```typescript
import { useState, useEffect, useRef, useCallback } from "react";
import { useTranslation } from "react-i18next";
import { Skeleton, App } from "antd";
import Header from "../components/Header";
import MarketOverview from "../components/MarketOverview";
import WatchlistSection from "../components/WatchlistSection";
import RecommendationsSection from "../components/RecommendationsSection";
import NewsList from "../components/NewsList";
import EconomicCalendar from "../components/EconomicCalendar";
import MarketAnalysisPanel from "../components/MarketAnalysisPanel";
import ChatWidget from "../components/ChatWidget";
import SectionNav from "../components/SectionNav";
import PreferencesModal from "../components/PreferencesModal";
import SectionErrorCard from "../components/SectionErrorCard";
import type { SectionDef } from "../components/SectionNav";
import type { SectionState } from "../types/section";
import { getMarketData, refreshMarket, refreshSection } from "../api/data";
import { useAuth } from "../hooks/useAuth";
```

- [ ] **Step 2: Replace state declarations and helper functions**

Keep `SECTIONS`, `ProgressBar`, `formatUpdatedAt`, `SectionSkeleton` unchanged.

Replace state in `DashboardPage` function (lines 83-94):

```typescript
  const [market, setMarket] = useState<"us" | "cn">("us");
  const [sections, setSections] = useState<Record<string, SectionState>>({});
  const [globalRefreshing, setGlobalRefreshing] = useState(false);
  const [refreshingSection, setRefreshingSection] = useState<string | null>(null);
  const [initialLoading, setInitialLoading] = useState(true);
  const [initialError, setInitialError] = useState(false);
  const [activeId, setActiveId] = useState(SECTIONS[0].id);
  const spyDisabledRef = useRef(false);
  const [prefsOpen, setPrefsOpen] = useState(false);
  const sectionRefs = useRef<Map<string, HTMLElement>>(new Map());
  useAuth();
  const { t } = useTranslation();
  const { message } = App.useApp();
```

- [ ] **Step 3: Replace data fetching logic**

Replace `fetchData` and `refreshData` functions (lines 99-144):

```typescript
  const mapSectionsResponse = (data: any): Record<string, SectionState> => {
    const result: Record<string, SectionState> = {};
    const raw = data.sections || {};
    for (const [key, val] of Object.entries(raw)) {
      const s = val as any;
      result[key] = {
        status: s.status === "cached" ? "ok" : s.status,
        data: s.data,
        error: s.error,
        updatedAt: s.updated_at,
      };
    }
    return result;
  };

  const fetchData = (m: string) => {
    setInitialLoading(true);
    setInitialError(false);
    getMarketData(m)
      .then((r) => {
        setSections(mapSectionsResponse(r.data));
        setInitialError(false);
      })
      .catch(() => {
        setInitialError(true);
        setSections({});
      })
      .finally(() => setInitialLoading(false));
  };

  const refreshData = (m: string) => {
    setGlobalRefreshing(true);
    // Set all sections to loading
    setSections((prev) => {
      const next: Record<string, SectionState> = {};
      for (const [key, val] of Object.entries(prev)) {
        next[key] = { ...val, status: "loading" };
      }
      return next;
    });
    refreshMarket(m)
      .then((r) => {
        const d = r.data;
        if (d.status === "rate_limited") {
          message.warning(t("refresh.rateLimited"));
          return;
        }
        setSections(mapSectionsResponse(d));
        message.success(t("refresh.success"));
      })
      .catch(() => {
        message.error(t("refresh.failed"));
      })
      .finally(() => setGlobalRefreshing(false));
  };

  const retrySection = (m: string, sectionName: string) => {
    setRefreshingSection(sectionName);
    setSections((prev) => ({
      ...prev,
      [sectionName]: { ...prev[sectionName], status: "loading" },
    }));
    refreshSection(m, sectionName)
      .then((r) => {
        const d = r.data;
        if (d.status === "rate_limited") {
          message.warning(t("refresh.rateLimited"));
          // Restore previous state
          setSections((prev) => ({
            ...prev,
            [sectionName]: { ...prev[sectionName], status: "error" },
          }));
          return;
        }
        const sectionResult: SectionState = {
          status: d.status === "cached" ? "ok" : d.status,
          data: d.data,
          error: d.error,
          updatedAt: d.updated_at,
        };
        setSections((prev) => ({ ...prev, [sectionName]: sectionResult }));
        if (d.status === "error") {
          message.error(t("refresh.failed"));
        }
      })
      .catch(() => {
        setSections((prev) => ({
          ...prev,
          [sectionName]: { ...prev[sectionName], status: "error" },
        }));
        message.error(t("refresh.failed"));
      })
      .finally(() => setRefreshingSection(null));
  };
```

- [ ] **Step 4: Update useEffect and scroll spy**

Keep the `useEffect` for initial fetch (line 146-148) unchanged.

Update the scroll spy useEffect (line 150-168) — change the dependency from `loading, data` to `initialLoading, sections`:

```typescript
  useEffect(() => {
    if (initialLoading) return;
    const handleScroll = () => {
      if (spyDisabledRef.current) return;
      const anchor = 120;
      for (const s of SECTIONS) {
        const el = sectionRefs.current.get(s.id);
        if (!el) continue;
        const rect = el.getBoundingClientRect();
        if (rect.top <= anchor && rect.bottom > anchor) {
          setActiveId(s.id);
          break;
        }
      }
    };
    window.addEventListener("scroll", handleScroll, { passive: true });
    handleScroll();
    return () => window.removeEventListener("scroll", handleScroll);
  }, [initialLoading, sections]);
```

Keep `sectionRef`, `handleNavigate` unchanged.

- [ ] **Step 5: Update render section**

Replace the data extraction and render (lines 186-266):

```typescript
  // Extract data from sections with fallbacks
  const indices = sections.indices?.data || [];
  const holdings = sections.holdings?.data || [];
  const news = sections.news?.data || [];
  const recommendations = sections.recommendations?.data || [];
  const calendar = sections.economic_calendar?.data || [];

  // Find most recent updated_at across all sections
  const latestUpdatedAt = Object.values(sections)
    .map((s) => s.updatedAt)
    .filter(Boolean)
    .sort()
    .pop();

  const visibleSections = SECTIONS.filter((s) => {
    if (s.id === "news") return news.length > 0;
    return true;
  });

  // Helper to render a section with loading/error states
  const renderSectionContent = (
    sectionName: string,
    content: React.ReactNode,
  ) => {
    const state = sections[sectionName];
    if (!state || state.status === "idle" || state.status === "loading") {
      return <SectionSkeleton />;
    }
    if (state.status === "error") {
      return (
        <SectionErrorCard
          error={state.error!}
          onRetry={() => retrySection(market, sectionName)}
          loading={refreshingSection === sectionName}
        />
      );
    }
    return content;
  };

  return (
    <div style={{ minHeight: "100vh", background: "#000" }}>
      <Header
        market={market}
        onMarketChange={setMarket}
        onRefresh={() => refreshData(market)}
        refreshing={globalRefreshing}
        updatedAt={formatUpdatedAt(latestUpdatedAt)}
        onOpenPreferences={() => setPrefsOpen(true)}
      />
      <ProgressBar active={globalRefreshing} />
      {!initialLoading && (
        <SectionNav sections={visibleSections} activeId={activeId} onNavigate={handleNavigate} />
      )}
      <main
        style={{
          maxWidth: 1280,
          margin: "0 auto",
          padding: "40px 40px 80px",
          display: "flex",
          flexDirection: "column",
          gap: 48,
        }}
      >
        {initialLoading ? (
          <>
            <SectionSkeleton />
            <SectionSkeleton />
            <SectionSkeleton />
            <SectionSkeleton />
            <SectionSkeleton />
          </>
        ) : initialError ? (
          <div style={{ textAlign: "center", padding: "80px 0" }}>
            <p style={{ color: "#8d969e", fontSize: 16, marginBottom: 16 }}>{t("error.loadFailed")}</p>
            <button
              onClick={() => fetchData(market)}
              style={{ background: "#494fdf", color: "#fff", border: "none", borderRadius: 8, padding: "8px 24px", cursor: "pointer", fontSize: 14 }}
            >
              {t("error.retry")}
            </button>
          </div>
        ) : (
          <>
            <section id="overview" ref={sectionRef("overview")}>
              {renderSectionContent("indices", (
                <>
                  <MarketOverview indices={indices} />
                  {calendar.length > 0 && (
                    <div style={{ marginTop: 32 }}>
                      {renderSectionContent("economic_calendar",
                        <EconomicCalendar calendar={calendar} />,
                      )}
                    </div>
                  )}
                  <div style={{ marginTop: 24 }}>
                    <MarketAnalysisPanel indices={indices} calendar={calendar} market={market} />
                  </div>
                </>
              ))}
            </section>
            {news.length > 0 && (
              <section id="news" ref={sectionRef("news")}>
                {renderSectionContent("news", <NewsList news={news} />)}
              </section>
            )}
            <section id="watchlist" ref={sectionRef("watchlist")}>
              {renderSectionContent("holdings",
                <WatchlistSection holdings={holdings} market={market} onRefresh={() => fetchData(market)} />,
              )}
            </section>
            <section id="recommendations" ref={sectionRef("recommendations")}>
              {renderSectionContent("recommendations",
                <RecommendationsSection recommendations={recommendations} market={market} />,
              )}
            </section>
          </>
        )}
      </main>
      <PreferencesModal open={prefsOpen} onClose={() => setPrefsOpen(false)} />
      {!initialLoading && !initialError && <ChatWidget market={market} data={{ indices, holdings, recommendations, news, economic_calendar: calendar }} />}
    </div>
  );
```

Note: Remove the `ProgressBar` error prop since we no longer flash errors — only show during active refresh. Remove the `DataErrorBanner` usage.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/pages/DashboardPage.tsx
git commit -m "feat: rewrite DashboardPage with per-section state management"
```

---

## Task 9: Update i18n translation files

**Files:**
- Modify: `frontend/src/i18n/zh-CN.json`
- Modify: `frontend/src/i18n/ko-KR.json`

- [ ] **Step 1: Add new i18n keys to zh-CN.json**

Add these keys (before `"error.separator"`):

```json
  "error.suggestion.timeout": "数据源响应较慢，请稍后重试",
  "error.suggestion.network": "网络连接异常，请检查网络后重试",
  "error.suggestion.api_error": "数据服务暂时不可用，请稍后重试",
  "error.suggestion.rate_limited": "请求过于频繁，请稍后再试",
  "error.suggestion.provider_error": "数据处理异常，数据源可能暂时不可用",
  "error.suggestion.auth": "API 配置异常，请联系管理员",
  "error.suggestion.unknown": "数据加载异常，请稍后重试",
```

- [ ] **Step 2: Add new i18n keys to ko-KR.json**

Add these keys (before `"error.separator"`):

```json
  "error.suggestion.timeout": "데이터 소스 응답이 느립니다, 잠시 후 다시 시도하세요",
  "error.suggestion.network": "네트워크 연결 오류, 네트워크를 확인 후 다시 시도하세요",
  "error.suggestion.api_error": "데이터 서비스를 일시적으로 사용할 수 없습니다, 잠시 후 다시 시도하세요",
  "error.suggestion.rate_limited": "요청이 너무 잦습니다, 잠시 후 다시 시도하세요",
  "error.suggestion.provider_error": "데이터 처리 오류, 데이터 소스를 일시적으로 사용할 수 없습니다",
  "error.suggestion.auth": "API 설정 오류, 관리자에게 문의하세요",
  "error.suggestion.unknown": "데이터 로드 오류, 잠시 후 다시 시도하세요",
```

- [ ] **Step 3: Commit**

```bash
git add frontend/src/i18n/zh-CN.json frontend/src/i18n/ko-KR.json
git commit -m "feat: add per-section error suggestion i18n keys"
```

---

## Task 10: Remove DataErrorBanner

**Files:**
- Delete: `frontend/src/components/DataErrorBanner.tsx`

- [ ] **Step 1: Delete DataErrorBanner.tsx**

```bash
rm frontend/src/components/DataErrorBanner.tsx
```

- [ ] **Step 2: Search for any remaining imports of DataErrorBanner**

Search the codebase for `DataErrorBanner` references and remove them. The DashboardPage rewrite in Task 8 already removed its import and usage. Check no other files import it.

```bash
grep -r "DataErrorBanner" frontend/src/ || echo "No remaining references"
```

- [ ] **Step 3: Commit**

```bash
git add -A
git commit -m "refactor: remove DataErrorBanner (replaced by per-card error states)"
```

---

## Task 11: Manual smoke test

- [ ] **Step 1: Start the backend**

```bash
uv run python run_web.py
```

- [ ] **Step 2: Start the frontend dev server**

```bash
cd frontend && npm run dev
```

- [ ] **Step 3: Test the following scenarios in the browser**

1. **Initial load**: All sections load and display data correctly
2. **Global refresh**: Click refresh button, all sections show loading, then transition to ok
3. **Section error**: If any section fails (e.g. disconnect network temporarily), it shows error card with retry button
4. **Section retry**: Click retry on error card, that section refreshes independently
5. **Rate limiting**: Rapidly click refresh twice, second should show rate limited warning
6. **Market switch**: Switch between US and CN markets, data loads correctly
7. **Chat widget**: Chat still receives correct data context
8. **Language switch**: Switch language, error messages translate correctly

- [ ] **Step 4: Fix any issues found during testing**

---

## File Structure Summary

```
investbrief/web/services/
├── cache.py                    # Added: per-section cache/lock helpers
├── data_fetcher.py             # Rewritten: section registry, _fetch_section, refresh_section

investbrief/web/routers/
├── data.py                     # Updated: new response format, refresh/{section} endpoint

investbrief/us/
├── provider.py                 # Added: get_section_data(), refactored fetch_all()

investbrief/cn/
├── provider.py                 # Added: get_section_data(), refactored fetch_all()

frontend/src/
├── api/
│   ├── client.ts               # Timeout 60s → 90s
│   └── data.ts                 # Added: refreshSection()
├── types/
│   └── section.ts              # New: SectionState, SectionError types
├── components/
│   ├── SectionErrorCard.tsx     # New: inline error + retry UI
│   ├── DataErrorBanner.tsx      # DELETED
│   └── ...                     # Unchanged (MarketOverview, WatchlistSection, etc.)
├── pages/
│   └── DashboardPage.tsx       # Rewritten: per-section state management
└── i18n/
    ├── zh-CN.json              # Added: error.suggestion.* keys
    └── ko-KR.json              # Added: error.suggestion.* keys
```
