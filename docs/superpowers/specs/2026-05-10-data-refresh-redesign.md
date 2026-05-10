# Data Refresh Redesign — Per-Section Isolation, Caching, and User Feedback

Date: 2026-05-10

## Problem Statement

Current data refresh mechanism has critical flaws:

1. **All-or-nothing failure**: `fetch_all()` makes 7 sequential calls with zero try/except. Any single sub-call failure kills the entire public or private data bucket.
2. **No error visibility**: Users see a generic retry button on failure, no indication of which sections failed or why.
3. **Refresh too coarse**: One refresh invalidates all cache keys including other users' private data.
4. **Misleading timestamps**: `updated_at` is written before data is fetched; failure shows current time.
5. **Timeout mismatch**: Frontend 60s timeout vs backend 90s timeout wastes resources.
6. **Incomplete error responses**: `_empty_result()` key list doesn't match actual section keys.

## Design Overview

Approach: **Batch fetch with per-section isolation and independent caching**.

- Keep single `GET /api/data/{market}` endpoint for efficient initial load
- Backend internally isolates each section's execution and caching
- Each section gets independent cache key, TTL, updated_at, and error state
- New `POST /api/data/{market}/refresh/{section}` for per-section refresh/retry
- Frontend shows per-section loading/error/success status with per-section retry

---

## 1. Backend: Per-Section Cache Architecture

### Cache Key Structure

```
market:{market}:section:{section_name}                    # public sections
market:{market}:user:{uid}:section:{section_name}         # private sections
market:{market}:section:news:{language}                   # news (per-language)
```

Replace current:
- `market:{market}:public` (bundle)
- `market:{market}:user:{uid}:private` (bundle)
- `market:{market}:news:{language}` (already per-language, keep)

### Section-to-Cache Mapping

| Section | Type | Cache Key Pattern | TTL |
|---------|------|-------------------|-----|
| indices | public | `market:{m}:section:indices` | 300s (5min) |
| economic_calendar | public | `market:{m}:section:economic_calendar` | 14400s (4h) |
| premarket_movers | public | `market:{m}:section:premarket_movers` | 300s |
| earnings_calendar | public | `market:{m}:section:earnings_calendar` | 14400s |
| congressional_trades | public | `market:{m}:section:congressional_trades` | 14400s |
| dragon_tiger | public | `market:{m}:section:dragon_tiger` | 3600s |
| sector_performance | public | `market:{m}:section:sector_performance` | 1800s |
| news | public | `market:{m}:section:news:{lang}` | 3600s |
| holdings | private | `market:{m}:user:{uid}:section:holdings` | 600s (10min) |
| recommendations | private | `market:{m}:user:{uid}:section:recommendations` | 1800s (30min) |

### Section Registry

Define a centralized section registry in `data_fetcher.py`:

```python
SECTION_CONFIG = {
    "us": {
        "public": {
            "indices":             {"ttl": 300,   "fetch": "get_indices"},
            "economic_calendar":   {"ttl": 14400, "fetch": "get_upcoming_events"},
            "premarket_movers":    {"ttl": 300,   "fetch": "get_premarket_movers"},
            "earnings_calendar":   {"ttl": 14400, "fetch": "get_earnings_calendar"},
            "congressional_trades":{"ttl": 14400, "fetch": "get_congressional_trades"},
            "news":                {"ttl": 3600,  "fetch": "get_news", "note": "routed to DataProvider in us/news.py, not provider method"},
        },
        "private": {
            "holdings":            {"ttl": 600,   "fetch": "get_holdings_data"},
            "recommendations":     {"ttl": 1800,  "fetch": "get_recommendations"},
        },
    },
    "cn": {
        "public": {
            "indices":             {"ttl": 300,   "fetch": "get_indices"},
            "economic_calendar":   {"ttl": 14400, "fetch": "get_economic_calendar"},
            "dragon_tiger":        {"ttl": 3600,  "fetch": "get_dragon_tiger"},
            "sector_performance":  {"ttl": 1800,  "fetch": "get_sector_performance"},
            "news":                {"ttl": 3600,  "fetch": "get_news"},
        },
        "private": {
            "holdings":            {"ttl": 600,   "fetch": "get_holdings_data"},
            "recommendations":     {"ttl": 1800,  "fetch": "get_recommendations"},
        },
    },
}
```

This replaces the current `_public_keys()` / `_private_keys()` functions.

---

## 2. Backend: Per-Section Isolated Execution

### `fetch_all_sections()` New Implementation

Each section is fetched independently with its own try/except:

```python
def fetch_section(self, market: str, section_name: str, user, **kwargs):
    """Fetch a single section, cache result, return data + status."""
    config = SECTION_CONFIG[market][...][section_name]
    cache_key = build_cache_key(market, section_name, user)

    # Check cache first
    cached = get_cached(redis, cache_key)
    if cached is not None:
        return {"data": cached["data"], "status": "cached",
                "updated_at": cached["updated_at"]}

    # Fetch
    try:
        fetch_method = getattr(provider, config["fetch"])
        data = fetch_method(**kwargs)
        result = {"data": data, "updated_at": now_iso()}
        set_cached(redis, cache_key, result, ttl=config["ttl"])
        return {"data": data, "status": "ok", "updated_at": result["updated_at"]}
    except Exception as e:
        error = classify_error(e)
        logger.warning(f"Section {section_name} failed: {error}")
        return {"data": None, "status": "error", "error": error, "updated_at": None}
```

### `get_market_data()` New Flow

```python
def get_market_data(redis, market, user):
    sections = {}
    for section_name in SECTION_CONFIG[market]["public"]:
        sections[section_name] = fetch_section(market, section_name, user=None)

    for section_name in SECTION_CONFIG[market]["private"]:
        sections[section_name] = fetch_section(
            market, section_name, user=user,
            holdings=user["markets"][market].get("holdings", []),
            industries=user["markets"][market].get("industries", []),
        )

    # News needs language
    language = user.get("language", "zh-CN")
    sections["news"] = fetch_section(market, "news", user=None, language=language)

    return {"sections": sections}
```

### Response Format

```json
{
  "sections": {
    "indices": {
      "data": [...],
      "status": "ok",
      "updated_at": "2026-05-10T14:30:00Z"
    },
    "news": {
      "data": null,
      "status": "error",
      "error": {
        "reason": "timeout",
        "detail": "yfinance request timed out after 30s"
      },
      "updated_at": null
    },
    "holdings": {
      "data": [...],
      "status": "cached",
      "updated_at": "2026-05-10T14:00:00Z"
    }
  }
}
```

`status` values: `"ok"` (freshly fetched), `"cached"` (from cache), `"error"` (fetch failed).

---

## 3. Backend: Refresh Endpoints

### Endpoints

| Method | Path | Purpose |
|--------|------|---------|
| POST | `/api/data/{market}/refresh` | Full refresh (all sections) |
| POST | `/api/data/{market}/refresh/{section}` | Single section refresh |

### Refresh Lock Strategy

```
market:{market}:refresh_lock                        # 60s, full refresh
market:{market}:section:{section}:refresh_lock      # 30s, per-section refresh
market:{market}:user:{uid}:section:{section}:refresh_lock  # 30s, private section
```

- Full refresh: global lock per market, 60s TTL
- Public section refresh: section-level lock, 30s TTL
- Private section refresh: user+section lock, 30s TTL

### Full Refresh Flow

1. Acquire `market:{market}:refresh_lock` (return 429 if held)
2. For each section, invalidate cache key
3. Execute all section fetches (can be concurrent with ThreadPoolExecutor)
4. Each section independently caches or records error
5. Return aggregated result (same format as GET)

**Key change**: Only invalidate current user's private cache keys, not all users'.

### Single Section Refresh Flow

1. Acquire section-level refresh lock (return 429 if held)
2. Invalidate that section's cache key
3. Execute that section's fetch
4. Cache result or record error
5. Return single section result:
```json
{
  "section": "indices",
  "data": [...],
  "status": "ok",
  "updated_at": "2026-05-10T14:35:00Z"
}
```

### News Translation

News fetch and translation remain combined in one section fetch, but:
- Cache stores translated result per language
- If translation fails, cache original (untranslated) news + set a `translated: false` flag
- Frontend can show a subtle warning if news is untranslated

---

## 4. Frontend: Per-Section Status

### Section State Model

```typescript
type SectionStatus = "idle" | "loading" | "ok" | "error";

interface SectionState {
  status: SectionStatus;
  data: any;
  error?: { reason: string; detail: string };
  updatedAt?: string;
  isStale?: boolean;  // data is older than expected TTL
}
```

### DashboardPage State Change

Replace current monolithic `loading`/`error`/`refreshing` with:

```typescript
const [sections, setSections] = useState<Record<string, SectionState>>({});
const [globalRefreshing, setGlobalRefreshing] = useState(false);
const [refreshProgress, setRefreshProgress] = useState({ done: 0, total: 0 });
```

### Initial Load

1. Call `GET /api/data/{market}`
2. Response contains all sections with individual status
3. Map each section to its `SectionState`
4. Sections with `"ok"` or `"cached"` render immediately
5. Sections with `"error"` render error state with retry

### Global Refresh (Header Button)

1. Call `POST /api/data/{market}/refresh`
2. All section cards transition to `loading` (show skeleton)
3. Response arrives with all section results
4. Each card independently transitions to `ok` or `error`
5. Button shows progress: "3/7 sections updated"

### Per-Section Retry

1. User clicks retry on error card
2. That card transitions to `loading`
3. Call `POST /api/data/{market}/refresh/{section}`
4. On success: card transitions to `ok`
5. On failure: card stays in `error` with updated error info

### Remove DataErrorBanner

Replace the global error banner with per-card error states:
- Each section card shows its own error inline
- Error display: icon + localized error message + retry button
- No more dismissible global banner

### Error Display in Cards

```
+----------------------------------+
| Section Title        Updated 3m  |
|                                  |
|  [!] Data fetch failed           |
|  Reason: API timeout             |
|  [Retry]                         |
+----------------------------------+
```

### Stale Data Indicator

If `updated_at` is older than the section's expected TTL:
- Show a subtle indicator on the card (e.g., dimmed timestamp with tooltip)
- Auto-suggest refresh when user opens a stale section

---

## 5. Backend: Provider Layer Changes

### US Provider `fetch_all()` Refactor

Current `fetch_all()` calls 7 methods sequentially with no error handling.

New approach: expose individual section methods that can be called independently:

```python
def get_section_data(self, section_name: str, **kwargs):
    """Fetch a single section's data."""
    method_map = {
        "indices": self._fetch_indices,
        "holdings": self._fetch_holdings,
        "recommendations": self._fetch_recommendations,
        "premarket_movers": self._fetch_premarket,
        "earnings_calendar": self._fetch_earnings,
        "economic_calendar": self._fetch_economic_calendar,
        "congressional_trades": self._fetch_congressional,
    }
    return method_map[section_name](**kwargs)
```

Each `_fetch_*` method wraps the existing logic in its own try/except.
Keep existing `fetch_all()` for backward compatibility (email pipeline) but refactor internally to call `_fetch_*` methods.

### CN Provider: Same Pattern

Apply identical section-based refactoring to `CNMarketProvider`.

### Email Pipeline Compatibility

Email pipeline (`run.py`) still calls `provider.fetch_all()` with its own error handling. The refactored `fetch_all()` should:
- Internally call each `_fetch_*` method with try/except
- Aggregate results into the same dict format
- Not change the email pipeline's behavior

---

## 6. Error Classification Enhancement

Current `_classify_error()` categorizes: timeout, network, rate_limited, auth, api_error, unknown.

Enhancements:
- Add `provider_error` for errors within provider logic (data parsing, unexpected None)
- Add `cache_error` for Redis failures
- Include the section name in error context
- Store errors with more structured detail for frontend display

Error response format:
```json
{
  "reason": "api_error",
  "detail": "yfinance returned empty data for AAPL",
  "section": "holdings",
  "retryable": true,
  "suggestion_key": "error.retrySuggestion.api_error"
}
```

`retryable` field tells the frontend whether retry is worthwhile.
`suggestion_key` maps to i18n translation key for user-friendly suggestions.

---

## 7. Timeout Alignment

Align frontend and backend timeouts:
- Frontend: 90s (match backend)
- Backend ThreadPoolExecutor: 90s per section (not per entire request)
- For full refresh: backend executes sections concurrently, each with 90s limit

This ensures the frontend doesn't abort before the backend finishes.

---

## 8. i18n Updates

New translation keys needed (both zh-CN and ko-KR):

```
error.sectionFailed       — "Data load failed"
error.retry               — "Retry"
error.reason.timeout      — "Request timed out"
error.reason.network      — "Network error"
error.reason.rate_limited — "Rate limited"
error.reason.api_error    — "API error"
error.reason.provider_error — "Data processing error"
error.suggestion.timeout  — "Please try again in a moment"
error.suggestion.network  — "Check your network connection"
error.suggestion.rate_limited — "Please wait and try again"
error.suggestion.api_error — "Service temporarily unavailable"
error.suggestion.provider_error — "Data source may be temporarily down"
section.stale             — "Data may be outdated"
refresh.progress          — "{done}/{total} sections updated"
```

---

## Files to Modify

### Backend
| File | Changes |
|------|---------|
| `investbrief/web/services/data_fetcher.py` | Major rewrite: section registry, per-section fetch/cache, new refresh logic |
| `investbrief/web/services/cache.py` | Add section-level cache operations, section-level locks |
| `investbrief/web/routers/data.py` | Add `refresh/{section}` endpoint, update response format, fix `_empty_result()` |
| `investbrief/us/provider.py` | Add `get_section_data()`, refactor `fetch_all()` to use section methods |
| `investbrief/cn/provider.py` | Same refactoring pattern |

### Frontend
| File | Changes |
|------|---------|
| `frontend/src/api/data.ts` | Add `refreshSection(market, section)` API call |
| `frontend/src/pages/DashboardPage.tsx` | Replace monolithic state with per-section state |
| `frontend/src/components/Header.tsx` | Update refresh button to show progress |
| `frontend/src/components/MarketOverview.tsx` | Add section-level loading/error state |
| `frontend/src/components/StockCard.tsx` | Add error + retry UI |
| `frontend/src/components/StockChart.tsx` | Add section-level loading state |
| `frontend/src/components/WatchlistSection.tsx` | Add section-level loading/error/retry |
| `frontend/src/components/RecommendationsSection.tsx` | Add section-level loading/error/retry |
| `frontend/src/components/EconomicCalendar.tsx` | Add section-level loading/error/retry |
| `frontend/src/components/DataErrorBanner.tsx` | Remove (replaced by per-card error states) |
| `frontend/src/i18n/zh-CN.json` | Add error/retry i18n keys |
| `frontend/src/i18n/ko-KR.json` | Add error/retry i18n keys |
