# Avatar Dropdown & Preferences Feature Design

Date: 2026-05-10

## Overview

Add interactive functionality to the static user avatar in the dashboard header. Clicking the avatar opens a dropdown with user info, email sending, preferences management, and logout.

## Part 1: Avatar Dropdown

**File:** `frontend/src/components/Header.tsx`

Current avatar is a static `<div>` with `<UserOutlined />` icon, no click handler.

### Changes

1. Import and call `useAuth()` inside Header to get user data
2. Replace static icon with user name initial (first character of `user.name`)
3. Wrap avatar with Ant Design `<Dropdown>` containing a menu:
   - **User info** (disabled menu item, read-only): displays `name` + `email`
   - **Send Email** (menu item): calls `POST /api/email/send`
   - **Preferences** (menu item): opens PreferencesModal
   - **Divider**
   - **Logout** (menu item): calls `POST /api/auth/logout`, clears localStorage token, redirects to `/login`

### Header Props Update

Add optional `onOpenPreferences` callback to Header props, managed by DashboardPage state.

## Part 2: Send Email API

**New file:** `investbrief/web/routers/email.py`

### Endpoint

`POST /api/email/send`

- **Auth:** required (JWT)
- **Request body:** `{ "market": "us" | "cn" | "all" }` (optional, defaults to user's active markets)
- **Response:** `{ "status": "started", "task_id": "..." }`

### Behavior

1. Validate user has the requested market in their `markets` config
2. Check rate limit (max 1 request per 5 minutes per user, stored in Redis with TTL)
3. Launch background task using FastAPI `BackgroundTasks`
4. Background task calls the email pipeline for this specific user
5. Return immediately with status

### Backend Refactoring

Extract a callable function from `run.py`'s `_run_single_market()`:

```python
# investbrief/web/services/email_sender.py
async def send_email_for_user(market: str, user_config: dict, config: dict):
    """Run the email pipeline for a single user and market."""
```

This function reuses the existing provider pipeline (fetch data -> fetch news -> summarize -> render -> send) but scoped to one user.

### Rate Limiting

Redis key: `email_lock:{user_id}:{market}`, TTL 300s (5 minutes).

## Part 3: Preferences Modal

**New file:** `frontend/src/components/PreferencesModal.tsx`

Ant Design `<Modal>` with `<Tabs>`, three tabs.

### Tab 1: Holdings / Watchlist

- Table listing current holdings (columns: symbol, name, market)
- "Add" button: opens inline form with symbol, name, market inputs
- "Delete" button per row
- Bottom hint text: "Changes will take effect after refreshing data on the dashboard"

### Tab 2: Industries

- Predefined industry list grouped by market (US / CN)
- Checkbox multi-select per market
- Bottom hint text: same as above

Available industries (from config):

**US:** semiconductor_ai, aerospace_defense, e_commerce, software_cloud, ev_automotive
**CN:** semiconductor, new_energy, consumer_electronics, pharmaceuticals, ai_concept

### Tab 3: Email Delivery Config

New `delivery` field in user config:

```json
{
  "email": "user@example.com",
  "delivery": [
    {
      "email": "user@example.com",
      "language": "zh-CN",
      "schedule": {
        "us": ["09:00"],
        "cn": ["15:30"]
      }
    }
  ],
  "markets": { ... }
}
```

UI: each delivery entry is an expandable card with:
- Email input
- Language dropdown (zh-CN / ko-KR)
- Schedule section: per-market list of time inputs (Ant Design TimePicker), with add/remove buttons

### Preferences API

**New file:** `investbrief/web/routers/preferences.py`

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/preferences` | Returns current user's holdings, industries, delivery config |
| PUT | `/api/preferences` | Updates user config in config.json |

**PUT request body:**

```json
{
  "markets": {
    "us": {
      "holdings": [{"symbol": "AMD", "name": "AMD"}],
      "industries": ["semiconductor_ai"]
    },
    "cn": {
      "holdings": [{"symbol": "300750", "name": "宁德时代"}],
      "industries": ["new_energy"]
    }
  },
  "delivery": [
    {
      "email": "user@example.com",
      "language": "zh-CN",
      "schedule": {"us": ["09:00"], "cn": ["15:30"]}
    }
  ]
}
```

### Config.json Write Strategy

- Use `filelock` library for cross-process file locking
- Read -> modify user entry -> write atomically (write to temp file, rename)
- Reload config cache after write via `reload_config()`

## File Changes Summary

### Frontend (New)
- `frontend/src/components/PreferencesModal.tsx`

### Frontend (Modified)
- `frontend/src/components/Header.tsx` — avatar dropdown + useAuth integration
- `frontend/src/pages/DashboardPage.tsx` — preferences modal state management
- `frontend/src/api/client.ts` — add preferences and email API calls
- `frontend/src/i18n/zh-CN.json` — new translation keys
- `frontend/src/i18n/ko-KR.json` — new translation keys

### Backend (New)
- `investbrief/web/routers/email.py` — email sending endpoint
- `investbrief/web/routers/preferences.py` — preferences CRUD endpoint
- `investbrief/web/services/email_sender.py` — extracted email pipeline logic

### Backend (Modified)
- `investbrief/web/app.py` — register new routers
- `investbrief/web/config.py` — add write config with file locking
- `investbrief/web/models/schemas.py` — add preference request/response models
- `pyproject.toml` — add `filelock` dependency

### Data
- `config.json` — new `delivery` field per recipient (migration: existing users get a default delivery entry from their current email + language)

## Migration

On first load of preferences API, if a user has no `delivery` field, auto-generate one:

```python
default_delivery = [{
    "email": user["email"],
    "language": user.get("language", "zh-CN"),
    "schedule": {market: [] for market in user.get("markets", {})}
}]
```

This ensures backward compatibility without requiring a one-time migration script.
