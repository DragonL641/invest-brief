# Persistent Error Banner Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a persistent, closable error banner to the dashboard that shows which data sections failed, why, and what the user can do about it.

**Architecture:** Backend `data_fetcher.py` accumulates structured error objects per sub-fetch. Router passes them through in the response. Frontend renders them in an Ant Design `Alert` banner at the top of `DashboardPage`.

**Tech Stack:** Python / FastAPI (backend), React / TypeScript / Ant Design 6 / i18next (frontend)

---

### Task 1: Add error accumulation to `data_fetcher.py`

**Files:**
- Modify: `investbrief/web/services/data_fetcher.py`

- [ ] **Step 1: Add `_classify_error` helper and modify `_fetch_and_cache_public` to catch and return errors**

Replace `_fetch_and_cache_public` (lines 101-106) with error-aware version. Add a helper to classify exceptions:

```python
def _classify_error(exc: Exception) -> dict:
    """Map an exception to a structured error reason."""
    import asyncio
    if isinstance(exc, asyncio.TimeoutError):
        return {"reason": "timeout", "detail": str(exc)[:200]}
    if isinstance(exc, (ConnectionError, OSError)):
        return {"reason": "network", "detail": str(exc)[:200]}
    msg = str(exc).lower()
    if "rate" in msg and "limit" in msg:
        return {"reason": "rate_limited", "detail": str(exc)[:200]}
    if "401" in msg or "403" in msg or "api key" in msg:
        return {"reason": "auth", "detail": str(exc)[:200]}
    if "429" in msg or "limit" in msg:
        return {"reason": "rate_limited", "detail": str(exc)[:200]}
    return {"reason": "api_error", "detail": str(exc)[:200]}
```

Replace `_fetch_and_cache_public`:

```python
def _fetch_and_cache_public(redis_client, market: str) -> tuple[dict, list]:
    provider = _create_provider(market)
    try:
        all_data = provider.fetch_all([], [], 3)
        public = {k: all_data.get(k, []) for k in _public_keys(market)}
        set_cached(redis_client, f"market:{market}:public", public)
        return public, []
    except Exception as e:
        logger.warning(f"Public data fetch failed for {market}: {e}", exc_info=True)
        err = _classify_error(e)
        errors = [{"section": k, **err} for k in _public_keys(market)]
        return {k: [] for k in _public_keys(market)}, errors
```

Replace `_fetch_and_cache_user`:

```python
def _fetch_and_cache_user(redis_client, market: str, user: dict) -> tuple[dict, list]:
    market_cfg = user.get("markets", {}).get(market, {})
    holdings = market_cfg.get("holdings", [])
    industries = market_cfg.get("industries", [])
    max_recs = market_cfg.get("max_recommendations", 3)

    provider = _create_provider(market)
    try:
        all_data = provider.fetch_all(holdings, industries, max_recs)
        private = {k: all_data.get(k, []) for k in _private_keys(market)}
        set_cached(redis_client, f"market:{market}:user:{user['id']}:private", private)
        return private, []
    except Exception as e:
        logger.warning(f"User data fetch failed for {market}: {e}", exc_info=True)
        err = _classify_error(e)
        errors = [{"section": k, **err} for k in _private_keys(market)]
        return {k: [] for k in _private_keys(market)}, errors
```

Replace `_fetch_news` to also return errors:

```python
def _fetch_news(market: str, symbols: list[str], industries: list[str]) -> tuple[list, list]:
    """Fetch news for the given market. Returns (items, errors)."""
    try:
        if market == "cn":
            from investbrief.cn.news import fetch_cn_news
            items = fetch_cn_news(symbols, industries, limit=20)
            for item in items:
                if "date" in item and "time" not in item:
                    item["time"] = item["date"]
            return items, []
        elif market == "us":
            from investbrief.web.config import get_config
            from investbrief.us.news import DataProvider
            config = get_config()
            dp = DataProvider(config)
            items = dp.get_financial_news(
                tickers=symbols, limit=20,
                user_tickers=symbols, industries=industries,
            )
            return items, []
    except Exception as e:
        logger.warning(f"News fetch failed for {market}: {e}", exc_info=True)
        return [], [{"section": "news", **_classify_error(e)}]
```

Update `get_market_data` to aggregate errors from all sub-fetches:

```python
def get_market_data(redis_client, market: str, user: dict) -> dict:
    result = {}
    errors = []

    # Public data (shared across users)
    public_cache = get_cached(redis_client, f"market:{market}:public")
    if public_cache is None:
        public_cache, pub_errors = _fetch_and_cache_public(redis_client, market)
        errors.extend(pub_errors)
    for k in _public_keys(market):
        result[k] = public_cache.get(k, [])

    # User private data
    uid = user["id"]
    user_cache = get_cached(redis_client, f"market:{market}:user:{uid}:private")
    if user_cache is None:
        user_cache, usr_errors = _fetch_and_cache_user(redis_client, market, user)
        errors.extend(usr_errors)
    for k in _private_keys(market):
        result[k] = user_cache.get(k, [])

    # News (cached per market, fetched on cache miss)
    news_cache = get_cached(redis_client, f"market:{market}:news")
    if news_cache is None:
        market_cfg = user.get("markets", {}).get(market, {})
        symbols = [h.get("symbol", h) if isinstance(h, dict) else h
                   for h in market_cfg.get("holdings", [])]
        industries = market_cfg.get("industries", [])
        news_items, news_errors = _fetch_news(market, symbols, industries)
        errors.extend(news_errors)
        if news_items:
            set_cached(redis_client, f"market:{market}:news", news_items)
        news_cache = news_items
    result["news"] = news_cache or []
    result["updated_at"] = get_last_updated(redis_client, market) or ""
    if errors:
        result["errors"] = errors

    return _sanitize_floats(result)
```

- [ ] **Step 2: Verify backend starts without import errors**

Run: `cd /Users/liuziyi/Projects/invest-brief && uv run python -c "from investbrief.web.services.data_fetcher import get_market_data; print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add investbrief/web/services/data_fetcher.py
git commit -m "feat(data-fetcher): accumulate structured errors per sub-fetch"
```

---

### Task 2: Pass errors through the router response

**Files:**
- Modify: `investbrief/web/routers/data.py`

- [ ] **Step 1: Update `_empty_result` and router handlers to include `errors` field**

Replace `_empty_result` (lines 26-28):

```python
def _empty_result(market: str, reason: str = "timeout") -> dict:
    keys = ["indices", "holdings", "recommendations", "news", "economic_calendar"]
    errors = [{"section": k, "reason": reason, "detail": ""} for k in keys]
    return {k: [] for k in keys} | {"updated_at": "", "error": "data_fetch_timeout", "errors": errors}
```

Update `get_data` timeout handler (line 42-43) to use `reason="timeout"`:

```python
    except asyncio.TimeoutError:
        logger.warning(f"Data fetch timeout for market={market}")
        return _empty_result(market, reason="timeout")
    except Exception as e:
        logger.error(f"Data fetch error for market={market}: {e}")
        return _empty_result(market, reason="unknown")
```

Update `refresh_data` timeout handler the same way (lines 59-63):

```python
    except asyncio.TimeoutError:
        logger.warning(f"Data refresh timeout for market={market}")
        return _empty_result(market, reason="timeout")
    except Exception as e:
        logger.error(f"Data refresh error for market={market}: {e}")
        return _empty_result(market, reason="unknown")
```

- [ ] **Step 2: Verify router imports cleanly**

Run: `cd /Users/liuziyi/Projects/invest-brief && uv run python -c "from investbrief.web.routers.data import router; print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add investbrief/web/routers/data.py
git commit -m "feat(data-router): include structured errors in response"
```

---

### Task 3: Add i18n keys for error banner

**Files:**
- Modify: `frontend/src/i18n/zh-CN.json`
- Modify: `frontend/src/i18n/ko-KR.json`

- [ ] **Step 1: Add error banner keys to `zh-CN.json`**

Append after `"error.retry": "重试"` (line 79):

```json
  "error.retry": "重试",
  "error.bannerTitle": "部分数据获取失败 · {{time}}",
  "error.bannerTitleFull": "数据获取失败 · {{time}}",
  "error.sectionIndices": "指数数据",
  "error.sectionHoldings": "持仓数据",
  "error.sectionNews": "新闻数据",
  "error.sectionRecommendations": "推荐数据",
  "error.sectionCalendar": "经济日历",
  "error.sectionEconomic_calendar": "经济日历",
  "error.sectionPremarket_movers": "盘前动态",
  "error.sectionEarnings_calendar": "财报日历",
  "error.sectionCongressional_trades": "国会交易",
  "error.sectionDragon_tiger": "龙虎榜",
  "error.sectionSector_performance": "板块表现",
  "error.solutionTimeout": "数据源响应较慢，请稍后重试",
  "error.solutionNetwork": "网络连接异常，请检查网络后重试",
  "error.solutionApi_error": "数据服务暂时不可用，请稍后重试",
  "error.solutionAuth": "API 配置异常，请联系管理员",
  "error.solutionRate_limited": "请求过于频繁，请稍后再试",
  "error.solutionUnknown": "数据加载异常，请稍后重试"
```

Note: ensure the last key before the new ones (`"error.retry"`) does NOT have a trailing comma removed — the new keys follow after it. The closing `}` stays at the end.

- [ ] **Step 2: Add corresponding keys to `ko-KR.json`**

Append after `"error.retry": "재시도"` (line 79):

```json
  "error.retry": "재시도",
  "error.bannerTitle": "일부 데이터 로드 실패 · {{time}}",
  "error.bannerTitleFull": "데이터 로드 실패 · {{time}}",
  "error.sectionIndices": "지수 데이터",
  "error.sectionHoldings": "보유 데이터",
  "error.sectionNews": "뉴스 데이터",
  "error.sectionRecommendations": "추천 데이터",
  "error.sectionCalendar": "경제 캘린더",
  "error.sectionEconomic_calendar": "경제 캘린더",
  "error.sectionPremarket_movers": "프리마켓",
  "error.sectionEarnings_calendar": "실적 캘린더",
  "error.sectionCongressional_trades": "의원 거래",
  "error.sectionDragon_tiger": "룡호방",
  "error.sectionSector_performance": "섹터 성과",
  "error.solutionTimeout": "데이터 소스 응답이 느립니다, 잠시 후 다시 시도하세요",
  "error.solutionNetwork": "네트워크 연결 오류, 네트워크를 확인 후 다시 시도하세요",
  "error.solutionApi_error": "데이터 서비스를 일시적으로 사용할 수 없습니다, 잠시 후 다시 시도하세요",
  "error.solutionAuth": "API 설정 오류, 관리자에게 문의하세요",
  "error.solutionRate_limited": "요청이 너무 잦습니다, 잠시 후 다시 시도하세요",
  "error.solutionUnknown": "데이터 로드 오류, 잠시 후 다시 시도하세요"
```

- [ ] **Step 3: Commit**

```bash
git add frontend/src/i18n/zh-CN.json frontend/src/i18n/ko-KR.json
git commit -m "feat(i18n): add error banner translation keys"
```

---

### Task 4: Create `DataErrorBanner` component

**Files:**
- Create: `frontend/src/components/DataErrorBanner.tsx`

- [ ] **Step 1: Write the component**

Create `frontend/src/components/DataErrorBanner.tsx`:

```tsx
import { Alert } from "antd";
import { useTranslation } from "react-i18next";

export interface FetchError {
  section: string;
  reason: string;
  detail?: string;
}

interface Props {
  errors: FetchError[];
  onClose: () => void;
}

const sectionKeyMap: Record<string, string> = {
  indices: "error.sectionIndices",
  holdings: "error.sectionHoldings",
  news: "error.sectionNews",
  recommendations: "error.sectionRecommendations",
  economic_calendar: "error.sectionEconomic_calendar",
  calendar: "error.sectionCalendar",
  premarket_movers: "error.sectionPremarket_movers",
  earnings_calendar: "error.sectionEarnings_calendar",
  congressional_trades: "error.sectionCongressional_trades",
  dragon_tiger: "error.sectionDragon_tiger",
  sector_performance: "error.sectionSector_performance",
};

const solutionKeyMap: Record<string, string> = {
  timeout: "error.solutionTimeout",
  network: "error.solutionNetwork",
  api_error: "error.solutionApi_error",
  auth: "error.solutionAuth",
  rate_limited: "error.solutionRate_limited",
  unknown: "error.solutionUnknown",
};

export default function DataErrorBanner({ errors, onClose }: Props) {
  const { t } = useTranslation();
  if (errors.length === 0) return null;

  const now = new Date();
  const time = `${String(now.getHours()).padStart(2, "0")}:${String(now.getMinutes()).padStart(2, "0")}`;
  const titleKey = errors.length >= 5 ? "error.bannerTitleFull" : "error.bannerTitle";

  const items = errors.map((e, i) => {
    const sectionName = t(sectionKeyMap[e.section] ?? e.section);
    const solutionText = t(solutionKeyMap[e.reason] ?? solutionKeyMap.unknown);
    return `${sectionName}：${solutionText}`;
  });

  return (
    <Alert
      type="error"
      closable
      onClose={onClose}
      showIcon
      message={t(titleKey, { time })}
      description={
        <ul style={{ margin: 0, paddingLeft: 16 }}>
          {items.map((text, i) => (
            <li key={i} style={{ fontSize: 13, lineHeight: "22px" }}>{text}</li>
          ))}
        </ul>
      }
      style={{ marginBottom: 16, borderRadius: 12 }}
    />
  );
}
```

- [ ] **Step 2: Verify no TypeScript errors**

Run: `cd /Users/liuziyi/Projects/invest-brief/frontend && npx tsc --noEmit --pretty 2>&1 | head -20`
Expected: No errors referencing `DataErrorBanner`

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/DataErrorBanner.tsx
git commit -m "feat(ui): add DataErrorBanner component"
```

---

### Task 5: Integrate banner into DashboardPage

**Files:**
- Modify: `frontend/src/pages/DashboardPage.tsx`

- [ ] **Step 1: Add imports and state**

Add import after line 11 (`import SectionNav...`):

```tsx
import DataErrorBanner from "../components/DataErrorBanner";
import type { FetchError } from "../components/DataErrorBanner";
```

Add state after line 86 (`const [refreshError, setRefreshError] = useState(false);`):

```tsx
const [fetchErrors, setFetchErrors] = useState<FetchError[]>([]);
const [bannerDismissed, setBannerDismissed] = useState(false);
```

- [ ] **Step 2: Update `fetchData` to capture errors**

Replace `fetchData` (lines 93-105):

```tsx
  const fetchData = (m: string) => {
    setLoading(true);
    setError(false);
    setBannerDismissed(false);
    getMarketData(m)
      .then((r) => {
        setData(r.data);
        setError(false);
        setFetchErrors(r.data?.errors || []);
      })
      .catch(() => {
        setError(true);
        setFetchErrors([]);
      })
      .finally(() => setLoading(false));
  };
```

- [ ] **Step 3: Update `refreshData` to capture errors**

Replace `refreshData` (lines 107-131):

```tsx
  const refreshData = (m: string) => {
    setRefreshing(true);
    setRefreshError(false);
    setBannerDismissed(false);
    refreshMarket(m)
      .then((r) => {
        const d = r.data;
        if (d.status === "rate_limited") {
          message.warning(t("refresh.rateLimited"));
          return;
        }
        if (d.error) {
          message.error(t("refresh.failed"));
          setFetchErrors(d.errors || []);
          return;
        }
        setData(d);
        setError(false);
        setFetchErrors(d.errors || []);
        message.success(t("refresh.success"));
      })
      .catch(() => {
        setRefreshError(true);
        setFetchErrors([]);
        message.error(t("refresh.failed"));
        setTimeout(() => setRefreshError(false), 400);
      })
      .finally(() => setRefreshing(false));
  };
```

- [ ] **Step 4: Render the banner in the JSX**

In the main content `div` (the one with `className="dashboard-main"`), insert the banner right after the opening of the content area. Specifically, after line 211 (`gap: 32,` closing brace and `>`), add:

```tsx
          >
            {!loading && fetchErrors.length > 0 && !bannerDismissed && (
              <DataErrorBanner errors={fetchErrors} onClose={() => setBannerDismissed(true)} />
            )}
```

This should be placed right before the `{loading ? (` block (line 212).

- [ ] **Step 5: Verify TypeScript compiles**

Run: `cd /Users/liuziyi/Projects/invest-brief/frontend && npx tsc --noEmit --pretty 2>&1 | head -20`
Expected: No errors

- [ ] **Step 6: Commit**

```bash
git add frontend/src/pages/DashboardPage.tsx
git commit -m "feat(dashboard): integrate persistent error banner with fetch state"
```

---

### Task 6: Manual verification

- [ ] **Step 1: Start the backend**

Run: `cd /Users/liuziyi/Projects/invest-brief && uv run python run_web.py`

Verify it starts without errors.

- [ ] **Step 2: Start the frontend dev server**

Run: `cd /Users/liuziyi/Projects/invest-brief/frontend && npm run dev`

- [ ] **Step 3: Open the dashboard in a browser and verify**

1. Normal load (data available): No banner should appear
2. Simulate failure: temporarily add `raise Exception("test")` in `_fetch_and_cache_public` and reload — banner should appear showing the failed sections
3. Close the banner: it should disappear
4. Refresh again: banner should reappear since data still fails
5. Remove the test exception and refresh: banner should disappear on success
