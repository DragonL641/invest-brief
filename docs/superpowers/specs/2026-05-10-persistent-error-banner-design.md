# Persistent Error Banner Design

## Problem

When data fetching fails (full or partial), the dashboard shows no persistent feedback. Initial load failure shows only an inline retry button, and refresh failures use auto-dismiss toasts that disappear in seconds. Users have no way to know which sections failed or what to do about it.

## Scope

- **Backend**: Enhance error reporting in data fetcher and router to return structured error details per section
- **Frontend**: Add a sticky Alert banner at the top of the dashboard showing failure time, reason, and suggested solution

## Design

### Backend Changes

#### `investbrief/web/services/data_fetcher.py`

- Add `errors` list accumulation during `get_market_data`
- Each sub-fetch failure (public data, private data) appends an error object: `{section, reason, detail}`
- Return `errors` in the result dict alongside existing data fields

#### `investbrief/web/routers/data.py`

- Include `errors` array in the 200 response body
- Keep existing `error` string field for backward compatibility
- Map caught exceptions to structured error reasons

#### Error Reason Taxonomy

| reason | meaning | solution copy (zh-CN) |
|--------|---------|----------------------|
| `timeout` | Data source timeout | "数据源响应较慢，请稍后重试" |
| `network` | Network failure | "网络连接异常，请检查网络后重试" |
| `api_error` | Third-party API error | "数据服务暂时不可用，请稍后重试" |
| `auth` | API key invalid/expired | "API 配置异常，请联系管理员" |
| `rate_limited` | Rate limit exceeded | "请求过于频繁，请稍后再试" |
| `unknown` | Unknown error | "数据加载异常，请稍后重试" |

### Frontend Changes

#### New Component: `DataErrorBanner`

- Ant Design `Alert` component, `type="error"`, `closable`
- Positioned as first element in DashboardPage (sticky at top)
- Content: title with timestamp + list of failed sections with reasons and solutions

**Example rendering:**

> 部分数据获取失败 · 14:32
> - 指数数据：数据源响应较慢，请稍后重试
> - 新闻数据：数据服务暂时不可用，请稍后重试

#### State Management (in DashboardPage)

- New state: `fetchErrors` (array of error objects) — populated from API response `errors` field
- New state: `bannerDismissed` (boolean) — set to `true` when user closes banner

**Lifecycle:**

| Event | `fetchErrors` | `bannerDismissed` |
|-------|---------------|-------------------|
| Initial load success | `[]` | `false` |
| Initial load failure | errors from response | `false` |
| Refresh success | `[]` | `false` |
| Refresh failure | errors from response | `false` |
| User closes banner | unchanged | `true` |
| Next successful fetch | `[]` | `false` |

Banner visible when: `fetchErrors.length > 0 && !bannerDismissed`

#### i18n Keys

New keys in `zh-CN.json` and `ko-KR.json`:

```
error.bannerTitle: "部分数据获取失败 · {{time}}"
error.bannerTitleFull: "数据获取失败 · {{time}}"
error.sectionIndices: "指数数据"
error.sectionHoldings: "持仓数据"
error.sectionNews: "新闻数据"
error.sectionRecommendations: "推荐数据"
error.sectionCalendar: "经济日历"
error.solutionTimeout: "数据源响应较慢，请稍后重试"
error.solutionNetwork: "网络连接异常，请检查网络后重试"
error.solutionApiError: "数据服务暂时不可用，请稍后重试"
error.solutionAuth: "API 配置异常，请联系管理员"
error.solutionRateLimited: "请求过于频繁，请稍后再试"
error.solutionUnknown: "数据加载异常，请稍后重试"
```

### Error Response Schema

```json
{
  "indices": [],
  "holdings": [],
  "news": [],
  "recommendations": [],
  "calendar": [],
  "error": "data_fetch_timeout",
  "errors": [
    {
      "section": "indices",
      "reason": "timeout",
      "detail": "yfinance request exceeded 30s"
    },
    {
      "section": "news",
      "reason": "api_error",
      "detail": "Finnhub returned 503"
    }
  ]
}
```

### Files to Modify

| File | Change |
|------|--------|
| `investbrief/web/services/data_fetcher.py` | Accumulate errors per sub-fetch, include in result |
| `investbrief/web/routers/data.py` | Pass `errors` to response, map exceptions |
| `frontend/src/components/DataErrorBanner.tsx` | New component |
| `frontend/src/pages/DashboardPage.tsx` | Integrate banner, manage error state |
| `frontend/src/i18n/zh-CN.json` | Add error banner keys |
| `frontend/src/i18n/ko-KR.json` | Add error banner keys |
