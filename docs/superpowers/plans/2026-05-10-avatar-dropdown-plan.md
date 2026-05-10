# Avatar Dropdown & Preferences Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an interactive avatar dropdown with user info, email sending, preferences management, and logout to the dashboard header.

**Architecture:** Backend-first approach — add new API endpoints (preferences CRUD, email trigger) to existing FastAPI app, then build the frontend avatar dropdown + preferences modal that consumes them. Config.json persists user preferences with filelock for safe concurrent writes.

**Tech Stack:** FastAPI, Pydantic, filelock, Redis, React, Ant Design 6, i18next, Axios

---

## Task 1: Add filelock dependency

**Files:**
- Modify: `pyproject.toml:21`

- [ ] **Step 1: Add filelock to dependencies**

In `pyproject.toml`, add `"filelock>=3.12.0"` to the `dependencies` list (after the `bcrypt` line):

```toml
    "bcrypt==4.1.3",
    "filelock>=3.12.0",
```

- [ ] **Step 2: Install dependency**

Run: `uv sync`
Expected: dependency resolves and installs

- [ ] **Step 3: Commit**

```bash
git add pyproject.toml uv.lock
git commit -m "chore: add filelock dependency for config writing"
```

---

## Task 2: Add config.json write helpers with file locking

**Files:**
- Modify: `investbrief/web/config.py`

- [ ] **Step 1: Add update_recipient function**

Append to `investbrief/web/config.py`:

```python
import tempfile
from filelock import FileLock


def update_recipient(user_id: int, updates: dict) -> dict | None:
    """Update a recipient's config in config.json with file locking.

    Args:
        user_id: The recipient's id field.
        updates: Dict of fields to update on the recipient (e.g. {"markets": {...}, "delivery": [...]}).

    Returns:
        The updated recipient dict, or None if user not found.
    """
    config_path = Path(__file__).resolve().parent.parent.parent / "config.json"
    lock_path = config_path.with_suffix(".json.lock")
    lock = FileLock(str(lock_path))

    with lock:
        with open(config_path, "r", encoding="utf-8") as f:
            config = json.load(f)

        recipients = config.get("recipients", [])
        updated = None
        for r in recipients:
            if r.get("id") == user_id:
                r.update(updates)
                updated = r
                break

        if updated is None:
            return None

        tmp = tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=str(config_path.parent),
            prefix=".config_", suffix=".tmp", delete=False,
        )
        try:
            json.dump(config, tmp, ensure_ascii=False, indent=2)
            tmp.close()
            Path(tmp.name).rename(config_path)
        except Exception:
            Path(tmp.name).unlink(missing_ok=True)
            raise

    reload_config()
    return updated


def get_recipient_by_id(user_id: int) -> dict | None:
    for r in get_recipients():
        if r.get("id") == user_id:
            return r
    return None
```

- [ ] **Step 2: Verify syntax**

Run: `uv run python -c "from investbrief.web.config import update_recipient, get_recipient_by_id; print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add investbrief/web/config.py
git commit -m "feat(config): add file-locked config.json write and get by id"
```

---

## Task 3: Add Pydantic schemas for preferences and email

**Files:**
- Modify: `investbrief/web/models/schemas.py`

- [ ] **Step 1: Add new schemas**

Append to `investbrief/web/models/schemas.py`:

```python
from typing import Optional, List


class HoldingItem(BaseModel):
    symbol: str
    name: str


class MarketPreferences(BaseModel):
    holdings: List[HoldingItem] = []
    industries: List[str] = []


class DeliveryEntry(BaseModel):
    email: str
    language: str = "zh-CN"
    schedule: dict[str, List[str]] = {}


class PreferencesUpdate(BaseModel):
    markets: dict[str, MarketPreferences] = {}
    delivery: List[DeliveryEntry] = []


class PreferencesResponse(BaseModel):
    markets: dict = {}
    delivery: list = []
    language: str = "zh-CN"


class EmailSendRequest(BaseModel):
    market: Optional[str] = None  # "us" | "cn" | "all" | None (defaults to user's markets)


class EmailSendResponse(BaseModel):
    status: str
    message: str = ""
```

- [ ] **Step 2: Verify syntax**

Run: `uv run python -c "from investbrief.web.models.schemas import PreferencesUpdate, EmailSendRequest; print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add investbrief/web/models/schemas.py
git commit -m "feat(schemas): add preferences and email send request/response models"
```

---

## Task 4: Create preferences API router

**Files:**
- Create: `investbrief/web/routers/preferences.py`

- [ ] **Step 1: Create the router**

Create `investbrief/web/routers/preferences.py`:

```python
import logging
from fastapi import APIRouter, Depends
from investbrief.web.auth import get_current_user
from investbrief.web.config import get_recipient_by_id, update_recipient
from investbrief.web.models.schemas import PreferencesUpdate, PreferencesResponse

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/preferences", tags=["preferences"])


def _ensure_delivery(user: dict) -> list:
    """Auto-migrate users without delivery field."""
    delivery = user.get("delivery")
    if delivery is not None:
        return delivery
    markets = user.get("markets", {})
    return [{
        "email": user["email"],
        "language": user.get("language", "zh-CN"),
        "schedule": {m: [] for m in markets},
    }]


@router.get("", response_model=PreferencesResponse)
def get_preferences(user: dict = Depends(get_current_user)):
    markets = user.get("markets", {})
    delivery = _ensure_delivery(user)
    return PreferencesResponse(
        markets=markets,
        delivery=delivery,
        language=user.get("language", "zh-CN"),
    )


@router.put("")
def update_preferences(
    body: PreferencesUpdate,
    user: dict = Depends(get_current_user),
):
    updates = {}

    if body.markets:
        existing_markets = user.get("markets", {})
        for market, prefs in body.markets.items():
            existing_markets[market] = {
                **existing_markets.get(market, {}),
                "holdings": [h.model_dump() for h in prefs.holdings],
                "industries": prefs.industries,
            }
        updates["markets"] = existing_markets

    if body.delivery:
        updates["delivery"] = [d.model_dump() for d in body.delivery]

    result = update_recipient(user["id"], updates)
    if result is None:
        return {"error": "user_not_found"}

    return {"status": "ok"}
```

- [ ] **Step 2: Verify import**

Run: `uv run python -c "from investbrief.web.routers.preferences import router; print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add investbrief/web/routers/preferences.py
git commit -m "feat(api): add preferences GET/PUT endpoints"
```

---

## Task 5: Create email sending service and router

**Files:**
- Create: `investbrief/web/services/email_sender.py`
- Create: `investbrief/web/routers/email.py`

- [ ] **Step 1: Create email sender service**

Create `investbrief/web/services/email_sender.py`:

```python
import json
import logging
import os
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

CONFIG_FILE = Path(__file__).resolve().parent.parent.parent.parent / "config.json"


def send_email_for_user(market: str, user_config: dict) -> dict:
    """Run the email pipeline for a single user and single market.

    Returns a dict with status and message.
    """
    try:
        from investbrief.core.mailer import EmailSender
        from investbrief.report import load_template, render_template, translate_html

        # Load config
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            config = json.load(f)

        # Get user's market config
        market_cfg = user_config.get("markets", {}).get(market, {})
        holdings = market_cfg.get("holdings", [])
        industries = market_cfg.get("industries", [])
        symbols = [h.get("symbol", "") for h in holdings]

        if not holdings and not industries:
            return {"status": "skipped", "message": f"No holdings or industries configured for {market}"}

        # Create provider and fetch data
        if market == "us":
            from investbrief.us.provider import USMarketProvider
            provider = USMarketProvider()
        elif market == "cn":
            from investbrief.cn.provider import CNMarketProvider
            provider = CNMarketProvider()
        else:
            return {"status": "error", "message": f"Unknown market: {market}"}

        max_recs = market_cfg.get("max_recommendations", 3)
        market_data = provider.fetch_all(holdings, industries, max_recs)

        # Fetch news
        news = []
        try:
            if market == "us":
                from investbrief.us.news import DataProvider
                dp = DataProvider(config)
                news = dp.get_financial_news(tickers=symbols, limit=20, user_tickers=symbols, industries=industries)
            elif market == "cn":
                from investbrief.cn.news import fetch_cn_news
                news = fetch_cn_news(symbols, industries, 20)
                for item in news:
                    if "date" in item and "time" not in item:
                        item["time"] = item["date"]
        except Exception as e:
            logger.warning(f"News fetch failed: {e}")

        # Render HTML
        render_config = {"color_up": "#e74c3c", "color_down": "#27ae60"}
        try:
            market_html = provider.render_section(market_data, render_config)
        except Exception as e:
            logger.warning(f"HTML render failed: {e}")
            market_html = "<p>Market data render failed.</p>"

        # Build report
        market_names = {"us": "US Daily", "cn": "A-Share Daily"}
        now = datetime.now(ZoneInfo("Asia/Shanghai"))
        report_data = {
            "subject": f"[{market_names.get(market, 'Invest Daily')}] {now.year}-{now.month}-{now.day}",
            "data_time": now.strftime("%Y-%m-%d %H:%M"),
            "date": now.strftime("%Y-%m-%d"),
            "global_metrics": [],
            "market_section_html": market_html,
            "news": news,
            "market": market,
        }

        # Render template
        template = load_template()
        language = user_config.get("language", "zh-CN")

        # Get delivery targets
        delivery = user_config.get("delivery")
        if not delivery:
            delivery = [{"email": user_config["email"], "language": language, "schedule": {}}]

        sender = EmailSender(str(CONFIG_FILE))
        sent_count = 0

        for target in delivery:
            target_email = target["email"]
            target_lang = target.get("language", language)

            html = render_template(template, report_data, target_lang, {})
            if target_lang != "zh-CN":
                try:
                    html = translate_html(html, target_lang)
                except Exception as e:
                    logger.warning(f"Translation failed for {target_email}: {e}")

            subject = report_data.get("subject", "Invest Daily")
            try:
                sender.send(target_email, subject, html)
                sent_count += 1
                logger.info(f"Email sent to {target_email}")
            except Exception as e:
                logger.error(f"Failed to send to {target_email}: {e}")

        return {"status": "ok", "message": f"Sent {sent_count} email(s) for {market}"}

    except Exception as e:
        logger.error(f"Email pipeline failed: {e}", exc_info=True)
        return {"status": "error", "message": str(e)}
```

- [ ] **Step 2: Create email router**

Create `investbrief/web/routers/email.py`:

```python
import logging
from fastapi import APIRouter, BackgroundTasks, Depends
from investbrief.web.auth import get_current_user
from investbrief.web.deps import get_redis
from investbrief.web.models.schemas import EmailSendRequest, EmailSendResponse
from investbrief.web.services.email_sender import send_email_for_user

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/email", tags=["email"])

RATE_LIMIT_TTL = 300  # 5 minutes


@router.post("/send", response_model=EmailSendResponse)
def trigger_email(
    body: EmailSendRequest,
    background_tasks: BackgroundTasks,
    user: dict = Depends(get_current_user),
    redis=Depends(get_redis),
):
    # Determine which markets to send for
    user_markets = list(user.get("markets", {}).keys())
    if body.market and body.market != "all":
        if body.market not in user_markets:
            return EmailSendResponse(status="error", message=f"Market '{body.market}' not configured for this user")
        markets = [body.market]
    else:
        markets = user_markets

    if not markets:
        return EmailSendResponse(status="error", message="No markets configured")

    # Check rate limit per market
    for m in markets:
        lock_key = f"email_lock:{user['id']}:{m}"
        if redis.get(lock_key):
            return EmailSendResponse(status="rate_limited", message=f"Please wait before sending another {m} email")
        redis.setex(lock_key, RATE_LIMIT_TTL, "1")

    # Launch background tasks
    for m in markets:
        background_tasks.add_task(send_email_for_user, m, user)

    return EmailSendResponse(status="started", message=f"Sending email for: {', '.join(markets)}")
```

- [ ] **Step 3: Verify imports**

Run: `uv run python -c "from investbrief.web.routers.email import router; print('OK')"`
Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add investbrief/web/services/email_sender.py investbrief/web/routers/email.py
git commit -m "feat(api): add email sending endpoint with rate limiting"
```

---

## Task 6: Register new routers in app

**Files:**
- Modify: `investbrief/web/app.py`

- [ ] **Step 1: Add imports and register routers**

In `investbrief/web/app.py`, update the import line:

```python
from investbrief.web.routers import auth, data, watchlist, chat, preferences, email
```

Add two new `include_router` lines after the existing ones:

```python
    app.include_router(preferences.router)
    app.include_router(email.router)
```

- [ ] **Step 2: Verify app starts**

Run: `uv run python -c "from investbrief.web.app import create_app; app = create_app(); print('Routes:', [r.path for r in app.routes])"`
Expected: output includes `/api/preferences`, `/api/email/send`

- [ ] **Step 3: Commit**

```bash
git add investbrief/web/app.py
git commit -m "feat(app): register preferences and email routers"
```

---

## Task 7: Add frontend API functions

**Files:**
- Create: `frontend/src/api/preferences.ts`
- Create: `frontend/src/api/email.ts`

- [ ] **Step 1: Create preferences API file**

Create `frontend/src/api/preferences.ts`:

```typescript
import client from "./client";

export interface HoldingItem {
  symbol: string;
  name: string;
}

export interface MarketPreferences {
  holdings: HoldingItem[];
  industries: string[];
}

export interface DeliveryEntry {
  email: string;
  language: string;
  schedule: Record<string, string[]>;
}

export interface PreferencesData {
  markets: Record<string, MarketPreferences>;
  delivery: DeliveryEntry[];
  language: string;
}

export interface PreferencesUpdate {
  markets?: Record<string, MarketPreferences>;
  delivery?: DeliveryEntry[];
}

export const getPreferences = () => client.get<PreferencesData>("/preferences");
export const updatePreferences = (data: PreferencesUpdate) => client.put("/preferences", data);
```

- [ ] **Step 2: Create email API file**

Create `frontend/src/api/email.ts`:

```typescript
import client from "./client";

export interface EmailSendRequest {
  market?: string;
}

export const sendEmail = (data?: EmailSendRequest) => client.post("/email/send", data || {});
```

- [ ] **Step 3: Verify TypeScript compiles**

Run: `cd frontend && npx tsc --noEmit src/api/preferences.ts src/api/email.ts 2>&1 | head -20`
Expected: no errors (or only import resolution warnings)

- [ ] **Step 4: Commit**

```bash
git add frontend/src/api/preferences.ts frontend/src/api/email.ts
git commit -m "feat(api): add frontend preferences and email API clients"
```

---

## Task 8: Add i18n translation keys

**Files:**
- Modify: `frontend/src/i18n/zh-CN.json`
- Modify: `frontend/src/i18n/ko-KR.json`

- [ ] **Step 1: Add Chinese translations**

Append to `frontend/src/i18n/zh-CN.json` (before the closing `}`), adding a comma after the last existing entry:

```json
  "error.retry": "重试",
  "avatar.logout": "退出登录",
  "avatar.sendEmail": "发送邮件",
  "avatar.sendEmail.started": "邮件发送中...",
  "avatar.sendEmail.rateLimited": "发送过于频繁，请稍后再试",
  "avatar.sendEmail.ok": "邮件发送成功",
  "avatar.sendEmail.error": "邮件发送失败",
  "avatar.sendEmail.skipped": "无持仓或行业配置，已跳过",
  "avatar.preferences": "偏好设置",
  "prefs.title": "偏好设置",
  "prefs.holdings": "持仓管理",
  "prefs.industries": "行业偏好",
  "prefs.delivery": "邮件配置",
  "prefs.hint": "修改后需点击页面刷新按钮重新获取数据才会生效",
  "prefs.holdings.symbol": "代码",
  "prefs.holdings.name": "名称",
  "prefs.holdings.market": "市场",
  "prefs.holdings.add": "添加",
  "prefs.holdings.delete": "删除",
  "prefs.delivery.email": "邮箱",
  "prefs.delivery.language": "语言",
  "prefs.delivery.schedule": "发送时间",
  "prefs.delivery.addEmail": "添加邮箱",
  "prefs.delivery.removeEmail": "删除",
  "prefs.delivery.addTime": "添加时间",
  "prefs.save": "保存",
  "prefs.cancel": "取消",
  "prefs.saved": "设置已保存",
  "prefs.saveFailed": "保存失败",
  "prefs.industries.us": "美股行业",
  "prefs.industries.cn": "A股行业"
```

- [ ] **Step 2: Add Korean translations**

Append to `frontend/src/i18n/ko-KR.json` (before the closing `}`), adding a comma after the last existing entry:

```json
  "error.retry": "재시도",
  "avatar.logout": "로그아웃",
  "avatar.sendEmail": "이메일 발송",
  "avatar.sendEmail.started": "이메일 발송 중...",
  "avatar.sendEmail.rateLimited": "너무 자주 요청했습니다, 잠시 후 다시 시도하세요",
  "avatar.sendEmail.ok": "이메일이 발송되었습니다",
  "avatar.sendEmail.error": "이메일 발송 실패",
  "avatar.sendEmail.skipped": "보유 종목 또는 산업 설정이 없습니다",
  "avatar.preferences": "환경설정",
  "prefs.title": "환경설정",
  "prefs.holdings": "보유 종목 관리",
  "prefs.industries": "산업 선호",
  "prefs.delivery": "이메일 설정",
  "prefs.hint": "변경 후 페이지 새로고침 버튼을 클릭해야 적용됩니다",
  "prefs.holdings.symbol": "종목코드",
  "prefs.holdings.name": "이름",
  "prefs.holdings.market": "시장",
  "prefs.holdings.add": "추가",
  "prefs.holdings.delete": "삭제",
  "prefs.delivery.email": "이메일",
  "prefs.delivery.language": "언어",
  "prefs.delivery.schedule": "발송 시간",
  "prefs.delivery.addEmail": "이메일 추가",
  "prefs.delivery.removeEmail": "삭제",
  "prefs.delivery.addTime": "시간 추가",
  "prefs.save": "저장",
  "prefs.cancel": "취소",
  "prefs.saved": "설정이 저장되었습니다",
  "prefs.saveFailed": "저장 실패",
  "prefs.industries.us": "미국 주식 산업",
  "prefs.industries.cn": "A주 산업"
```

- [ ] **Step 3: Verify JSON is valid**

Run: `node -e "JSON.parse(require('fs').readFileSync('frontend/src/i18n/zh-CN.json','utf8')); JSON.parse(require('fs').readFileSync('frontend/src/i18n/ko-KR.json','utf8')); console.log('OK')"`
Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add frontend/src/i18n/zh-CN.json frontend/src/i18n/ko-KR.json
git commit -m "feat(i18n): add avatar dropdown and preferences translation keys"
```

---

## Task 9: Create PreferencesModal component

**Files:**
- Create: `frontend/src/components/PreferencesModal.tsx`

- [ ] **Step 1: Create the component**

Create `frontend/src/components/PreferencesModal.tsx`:

```tsx
import { useState, useEffect } from "react";
import { useTranslation } from "react-i18next";
import { Modal, Tabs, Table, Button, Input, Select, TimePicker, Card, Space, App } from "antd";
import { PlusOutlined, DeleteOutlined, MailOutlined } from "@ant-design/icons";
import type { PreferencesData, DeliveryEntry, HoldingItem, PreferencesUpdate } from "../api/preferences";
import { getPreferences, updatePreferences } from "../api/preferences";

const US_INDUSTRIES = ["semiconductor_ai", "aerospace_defense", "e_commerce", "software_cloud", "ev_automotive"];
const CN_INDUSTRIES = ["semiconductor", "new_energy", "consumer_electronics", "pharmaceuticals", "ai_concept"];

interface Props {
  open: boolean;
  onClose: () => void;
}

export default function PreferencesModal({ open, onClose }: Props) {
  const { t } = useTranslation();
  const { message } = App.useApp();
  const [data, setData] = useState<PreferencesData | null>(null);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);

  // Local edit state
  const [holdings, setHoldings] = useState<Record<string, HoldingItem[]>>({});
  const [industries, setIndustries] = useState<Record<string, string[]>>({});
  const [delivery, setDelivery] = useState<DeliveryEntry[]>([]);
  const [newSymbol, setNewSymbol] = useState("");
  const [newName, setNewName] = useState("");
  const [newMarket, setNewMarket] = useState<"us" | "cn">("us");

  useEffect(() => {
    if (!open) return;
    setLoading(true);
    getPreferences()
      .then((r) => {
        setData(r.data);
        const mkHoldings: Record<string, HoldingItem[]> = {};
        const mkIndustries: Record<string, string[]> = {};
        for (const [mkt, cfg] of Object.entries(r.data.markets)) {
          mkHoldings[mkt] = cfg.holdings || [];
          mkIndustries[mkt] = cfg.industries || [];
        }
        setHoldings(mkHoldings);
        setIndustries(mkIndustries);
        setDelivery(r.data.delivery || []);
      })
      .catch(() => message.error(t("prefs.saveFailed")))
      .finally(() => setLoading(false));
  }, [open]);

  const handleSave = () => {
    setSaving(true);
    const body: PreferencesUpdate = {
      markets: Object.fromEntries(
        Object.entries(holdings).map(([mkt, h]) => [mkt, { holdings: h, industries: industries[mkt] || [] }])
      ),
      delivery,
    };
    updatePreferences(body)
      .then(() => {
        message.success(t("prefs.saved"));
        onClose();
      })
      .catch(() => message.error(t("prefs.saveFailed")))
      .finally(() => setSaving(false));
  };

  const addHolding = () => {
    if (!newSymbol.trim() || !newName.trim()) return;
    const list = { ...holdings };
    list[newMarket] = [...(list[newMarket] || []), { symbol: newSymbol.trim().toUpperCase(), name: newName.trim() }];
    setHoldings(list);
    setNewSymbol("");
    setNewName("");
  };

  const removeHolding = (market: string, idx: number) => {
    const list = { ...holdings };
    list[market] = (list[market] || []).filter((_, i) => i !== idx);
    setHoldings(list);
  };

  const toggleIndustry = (market: string, ind: string) => {
    const list = { ...industries };
    const current = list[market] || [];
    list[market] = current.includes(ind) ? current.filter((i) => i !== ind) : [...current, ind];
    setIndustries(list);
  };

  const addDeliveryEntry = () => {
    setDelivery([...delivery, { email: "", language: "zh-CN", schedule: {} }]);
  };

  const removeDeliveryEntry = (idx: number) => {
    setDelivery(delivery.filter((_, i) => i !== idx));
  };

  const updateDeliveryEntry = (idx: number, field: string, value: any) => {
    const list = [...delivery];
    list[idx] = { ...list[idx], [field]: value };
    setDelivery(list);
  };

  const addScheduleTime = (entryIdx: number, market: string) => {
    const list = [...delivery];
    const sched = { ...(list[entryIdx].schedule || {}) };
    sched[market] = [...(sched[market] || []), "09:00"];
    list[entryIdx] = { ...list[entryIdx], schedule: sched };
    setDelivery(list);
  };

  const removeScheduleTime = (entryIdx: number, market: string, timeIdx: number) => {
    const list = [...delivery];
    const sched = { ...(list[entryIdx].schedule || {}) };
    sched[market] = (sched[market] || []).filter((_, i) => i !== timeIdx);
    list[entryIdx] = { ...list[entryIdx], schedule: sched };
    setDelivery(list);
  };

  const updateScheduleTime = (entryIdx: number, market: string, timeIdx: number, value: string) => {
    const list = [...delivery];
    const sched = { ...(list[entryIdx].schedule || {}) };
    sched[market] = [...(sched[market] || [])];
    sched[market][timeIdx] = value;
    list[entryIdx] = { ...list[entryIdx], schedule: sched };
    setDelivery(list);
  };

  // --- Holdings Tab ---
  const holdingsTab = (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      {(["us", "cn"] as const).map((mkt) => (
        <div key={mkt}>
          <h4 style={{ color: "#fff", marginBottom: 8 }}>{mkt === "us" ? t("tab.us") : t("tab.cn")}</h4>
          <Table
            dataSource={(holdings[mkt] || []).map((h, i) => ({ ...h, key: `${mkt}-${i}` }))}
            pagination={false}
            size="small"
            rowKey="key"
            columns={[
              { title: t("prefs.holdings.symbol"), dataIndex: "symbol" },
              { title: t("prefs.holdings.name"), dataIndex: "name" },
              {
                title: "",
                width: 60,
                render: (_: any, __: any, idx: number) => (
                  <Button type="text" danger size="small" icon={<DeleteOutlined />} onClick={() => removeHolding(mkt, idx)} />
                ),
              },
            ]}
          />
        </div>
      ))}
      <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
        <Select value={newMarket} onChange={setNewMarket} style={{ width: 100 }} options={[{ value: "us", label: "US" }, { value: "cn", label: "CN" }]} />
        <Input placeholder={t("prefs.holdings.symbol")} value={newSymbol} onChange={(e) => setNewSymbol(e.target.value)} style={{ width: 120 }} />
        <Input placeholder={t("prefs.holdings.name")} value={newName} onChange={(e) => setNewName(e.target.value)} style={{ width: 140 }} />
        <Button icon={<PlusOutlined />} onClick={addHolding}>{t("prefs.holdings.add")}</Button>
      </div>
      <div style={{ color: "#8d969e", fontSize: 12 }}>{t("prefs.hint")}</div>
    </div>
  );

  // --- Industries Tab ---
  const industriesTab = (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      {(["us", "cn"] as const).map((mkt) => {
        const list = mkt === "us" ? US_INDUSTRIES : CN_INDUSTRIES;
        const selected = industries[mkt] || [];
        return (
          <div key={mkt}>
            <h4 style={{ color: "#fff", marginBottom: 8 }}>{mkt === "us" ? t("prefs.industries.us") : t("prefs.industries.cn")}</h4>
            <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
              {list.map((ind) => (
                <Button
                  key={ind}
                  size="small"
                  type={selected.includes(ind) ? "primary" : "default"}
                  onClick={() => toggleIndustry(mkt, ind)}
                >
                  {ind}
                </Button>
              ))}
            </div>
          </div>
        );
      })}
      <div style={{ color: "#8d969e", fontSize: 12 }}>{t("prefs.hint")}</div>
    </div>
  );

  // --- Delivery Tab ---
  const deliveryTab = (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      {delivery.map((entry, idx) => (
        <Card key={idx} size="small" title={<span><MailOutlined /> {entry.email || t("prefs.delivery.addEmail")}</span>}
          extra={<Button type="text" danger size="small" onClick={() => removeDeliveryEntry(idx)}>{t("prefs.delivery.removeEmail")}</Button>}>
          <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
            <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
              <span style={{ color: "#8d969e", width: 50 }}>{t("prefs.delivery.email")}</span>
              <Input value={entry.email} onChange={(e) => updateDeliveryEntry(idx, "email", e.target.value)} style={{ flex: 1 }} />
            </div>
            <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
              <span style={{ color: "#8d969e", width: 50 }}>{t("prefs.delivery.language")}</span>
              <Select value={entry.language} onChange={(v) => updateDeliveryEntry(idx, "language", v)}
                style={{ width: 120 }} options={[{ value: "zh-CN", label: "中文" }, { value: "ko-KR", label: "한국어" }]} />
            </div>
            <div>
              <span style={{ color: "#8d969e" }}>{t("prefs.delivery.schedule")}</span>
              {(["us", "cn"] as const).map((mkt) => (
                <div key={mkt} style={{ marginTop: 8 }}>
                  <span style={{ color: "#aaa", fontSize: 12 }}>{mkt.toUpperCase()}</span>
                  <div style={{ display: "flex", flexWrap: "wrap", gap: 4, marginTop: 4 }}>
                    {(entry.schedule?.[mkt] || []).map((time, ti) => (
                      <TimePicker key={ti} format="HH:mm" value={time ? (() => { const [h, m] = time.split(":"); const d = new Date(); d.setHours(+h, +m); return d; })() : null}
                        onChange={(_, s) => { if (s) updateScheduleTime(idx, mkt, ti, s); }} />
                    ))}
                    <Button size="small" onClick={() => addScheduleTime(idx, mkt)}>{t("prefs.delivery.addTime")}</Button>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </Card>
      ))}
      <Button icon={<PlusOutlined />} onClick={addDeliveryEntry}>{t("prefs.delivery.addEmail")}</Button>
    </div>
  );

  return (
    <Modal
      title={t("prefs.title")}
      open={open}
      onCancel={onClose}
      onOk={handleSave}
      okText={t("prefs.save")}
      cancelText={t("prefs.cancel")}
      confirmLoading={saving}
      width={680}
    >
      <Tabs items={[
        { key: "holdings", label: t("prefs.holdings"), children: holdingsTab },
        { key: "industries", label: t("prefs.industries"), children: industriesTab },
        { key: "delivery", label: t("prefs.delivery"), children: deliveryTab },
      ]} />
    </Modal>
  );
}
```

- [ ] **Step 2: Verify TypeScript compiles**

Run: `cd frontend && npx tsc --noEmit 2>&1 | head -30`
Expected: errors only from other existing files, not from PreferencesModal

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/PreferencesModal.tsx
git commit -m "feat(ui): add PreferencesModal with holdings, industries, delivery tabs"
```

---

## Task 10: Update Header with avatar dropdown

**Files:**
- Modify: `frontend/src/components/Header.tsx`

- [ ] **Step 1: Rewrite Header with dropdown**

Replace the entire contents of `frontend/src/components/Header.tsx`:

```tsx
import { useTranslation } from "react-i18next";
import { Dropdown, App } from "antd";
import { StockOutlined, ReloadOutlined, LoadingOutlined, SendOutlined, SettingOutlined, LogoutOutlined, UserOutlined } from "@ant-design/icons";
import { useAuth } from "../hooks/useAuth";
import { logout } from "../api/auth";
import { sendEmail } from "../api/email";

interface HeaderProps {
  market: "us" | "cn";
  onMarketChange: (m: "us" | "cn") => void;
  onRefresh: () => void;
  refreshing?: boolean;
  updatedAt?: string;
  onOpenPreferences?: () => void;
}

const pillStyle = (active: boolean): React.CSSProperties => ({
  padding: "6px 20px",
  borderRadius: 9999,
  fontSize: 14,
  fontWeight: 600,
  cursor: "pointer",
  background: active ? "#494fdf" : "#16181a",
  color: "#fff",
  border: "none",
  outline: "none",
  transition: "background 0.2s",
});

const langPillStyle = (active: boolean): React.CSSProperties => ({
  padding: "4px 10px",
  borderRadius: 9999,
  fontSize: 12,
  fontWeight: 600,
  cursor: "pointer",
  background: active ? "#494fdf" : "transparent",
  color: "#fff",
  border: "none",
  outline: "none",
  transition: "background 0.2s",
});

export default function Header({ market, onMarketChange, onRefresh, refreshing, updatedAt, onOpenPreferences }: HeaderProps) {
  const { t, i18n } = useTranslation();
  const { user } = useAuth();
  const { message } = App.useApp();

  const handleSendEmail = () => {
    sendEmail()
      .then((r) => {
        const d = r.data;
        if (d.status === "started") message.success(t("avatar.sendEmail.started"));
        else if (d.status === "rate_limited") message.warning(t("avatar.sendEmail.rateLimited"));
        else if (d.status === "error") message.error(d.message || t("avatar.sendEmail.error"));
        else if (d.status === "skipped") message.info(t("avatar.sendEmail.skipped"));
      })
      .catch(() => message.error(t("avatar.sendEmail.error")));
  };

  const handleLogout = () => {
    logout().finally(() => {
      localStorage.removeItem("token");
      window.location.href = "/login";
    });
  };

  const avatarInitial = user?.name?.charAt(0) || "?";

  const menuItems = [
    {
      key: "info",
      label: (
        <div style={{ padding: "4px 0" }}>
          <div style={{ fontWeight: 600, color: "#fff" }}>{user?.name || ""}</div>
          <div style={{ fontSize: 12, color: "#8d969e" }}>{user?.email || ""}</div>
        </div>
      ),
      disabled: true,
    },
    { type: "divider" as const },
    { key: "email", icon: <SendOutlined />, label: t("avatar.sendEmail"), onClick: handleSendEmail },
    { key: "preferences", icon: <SettingOutlined />, label: t("avatar.preferences"), onClick: onOpenPreferences },
    { type: "divider" as const },
    { key: "logout", icon: <LogoutOutlined />, label: t("avatar.logout"), onClick: handleLogout },
  ];

  return (
    <header
      style={{
        height: 64,
        padding: "0 40px",
        background: "#000",
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
        borderBottom: "1px solid rgba(255,255,255,0.06)",
      }}
    >
      {/* Left: Logo */}
      <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
        <StockOutlined style={{ fontSize: 22, color: "#494fdf" }} />
        <span style={{ color: "#fff", fontSize: 20, fontWeight: 600 }}>
          {t("app.title")}
        </span>
      </div>

      {/* Center: Market tabs */}
      <div style={{ display: "flex", gap: 8 }}>
        <button style={pillStyle(market === "us")} onClick={() => onMarketChange("us")}>
          {t("tab.us")}
        </button>
        <button style={pillStyle(market === "cn")} onClick={() => onMarketChange("cn")}>
          {t("tab.cn")}
        </button>
      </div>

      {/* Right */}
      <div style={{ display: "flex", alignItems: "center", gap: 16 }}>
        {/* Language switch */}
        <div
          style={{
            display: "flex",
            background: "#16181a",
            borderRadius: 9999,
            padding: 2,
          }}
        >
          <button style={langPillStyle(i18n.language === "zh-CN")} onClick={() => i18n.changeLanguage("zh-CN")}>
            中
          </button>
          <button style={langPillStyle(i18n.language === "ko-KR")} onClick={() => i18n.changeLanguage("ko-KR")}>
            한
          </button>
        </div>

        {/* Refresh */}
        <button
          style={{
            display: "flex",
            alignItems: "center",
            gap: 6,
            background: "#16181a",
            border: "none",
            borderRadius: 9999,
            padding: "6px 16px",
            color: "#fff",
            fontSize: 13,
            cursor: refreshing ? "not-allowed" : "pointer",
            opacity: refreshing ? 0.7 : 1,
            pointerEvents: refreshing ? "none" : "auto",
            transition: "opacity 0.2s",
          }}
          onClick={onRefresh}
        >
          {refreshing ? (
            <LoadingOutlined style={{ fontSize: 13 }} />
          ) : (
            <ReloadOutlined style={{ fontSize: 13 }} />
          )}
          {refreshing ? t("refreshing") : t("refresh")}
        </button>

        {/* Last update */}
        {updatedAt && (
          <span style={{ color: "#8d969e", fontSize: 12 }}>
            {t("refresh.lastUpdate", { time: updatedAt })}
          </span>
        )}

        {/* Avatar Dropdown */}
        <Dropdown menu={{ items: menuItems }} trigger={["click"]} placement="bottomRight">
          <div
            style={{
              width: 32,
              height: 32,
              borderRadius: "50%",
              background: "#494fdf",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              color: "#fff",
              fontSize: 14,
              fontWeight: 600,
              cursor: "pointer",
            }}
          >
            {avatarInitial}
          </div>
        </Dropdown>
      </div>
    </header>
  );
}
```

- [ ] **Step 2: Verify TypeScript compiles**

Run: `cd frontend && npx tsc --noEmit 2>&1 | head -30`
Expected: no new errors from Header.tsx

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/Header.tsx
git commit -m "feat(header): add avatar dropdown with user info, email, preferences, logout"
```

---

## Task 11: Wire up PreferencesModal in DashboardPage

**Files:**
- Modify: `frontend/src/pages/DashboardPage.tsx`

- [ ] **Step 1: Add imports and state**

In `DashboardPage.tsx`, add import after the existing imports:

```tsx
import PreferencesModal from "../components/PreferencesModal";
```

Add state after the existing state declarations (after line 87):

```tsx
  const [prefsOpen, setPrefsOpen] = useState(false);
```

Update the `useAuth()` call (line 89) to keep the `user` reference if needed — it's already unused beyond the call, so no change needed.

- [ ] **Step 2: Pass onOpenPreferences to Header**

Update the Header component call (line 187) to include the new prop:

```tsx
<Header market={market} onMarketChange={setMarket} onRefresh={() => refreshData(market)} refreshing={refreshing} updatedAt={formatUpdatedAt(data?.updated_at)} onOpenPreferences={() => setPrefsOpen(true)} />
```

- [ ] **Step 3: Add PreferencesModal**

Add the PreferencesModal right before the closing `</div>` of the root div (before line 256):

```tsx
      <PreferencesModal open={prefsOpen} onClose={() => setPrefsOpen(false)} />
```

- [ ] **Step 4: Verify build**

Run: `cd frontend && npm run build 2>&1 | tail -5`
Expected: build succeeds

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/DashboardPage.tsx
git commit -m "feat(dashboard): wire up preferences modal from avatar dropdown"
```

---

## Task 12: Manual smoke test

- [ ] **Step 1: Start backend**

Run: `uv run python run_web.py` (requires Redis running)

- [ ] **Step 2: Start frontend**

Run: `cd frontend && npm run dev`

- [ ] **Step 3: Test avatar dropdown**

1. Login and navigate to dashboard
2. Click avatar — verify dropdown appears with user name, email, send email, preferences, logout items
3. Click "Preferences" — verify modal opens with three tabs
4. In Holdings tab — add a stock, verify it appears in table, delete it
5. In Industries tab — toggle some industries, verify they highlight
6. In Delivery tab — add an email entry, set language and schedule
7. Click Save — verify success message
8. Click "Send Email" — verify status message appears (started or error if no SMTP configured)
9. Click "Logout" — verify redirect to login page

- [ ] **Step 4: Commit any fixes**

If bugs found, fix and commit.
