# BOQ_AI Session State

Compact active memory. Full spec: `docs/PRODUCT.md`. Schema: `docs/DATABASE.md`.
History: `docs/CHANGELOG.md` (do not duplicate session diaries here).

## Current Status

- **Phase:** Go-live polish — BOQ pipeline + UI active on PostgreSQL / Celery
- **Migrations:** Fresh `0001_initial` per app (reset 2026-07-10); applied locally
- **Tests:** Suite removed — needs restoration
- **Runtime:** `config.settings`, PostgreSQL `boq_db`, Django templates + HTMX, Celery
- **Active apps:** accounts, users, database_manager, boq, dashboard, notifications, audit
- **AI logging:** `AI_INSTRUCTION_LOGGING=True` for now (embedding dumps truncated)

## Active Workflows

**Database:** upload → validate → import → activate → embeddings (sync). Last 10
uploads kept for view/download; only the active upload retains master rows.

**BOQ tabs:** BOQ → Make list → Analysis → Make & Vendor → Labour → Review → Export

1. Upload workbook (+ optional make list) → parse to JSON
2. **Analyse** → AI extract products + map top Rate_Master candidates (Celery)
3. Expert edit / **Re-analyse** (rematch) / **Re-extract** (workbook AI again)
4. Analysis **Next** → lowest-price Make & Vendor defaults
5. Make & Vendor **Next** → unlock Labour → complete → Review → Export Excel

## Active Behaviour (in use)

| Area | Current behaviour |
| --- | --- |
| Sections | Serial-lineage groups with qty **slots**; empty slots show Add + Re-analyse |
| Analysis | Product tabs; confidence border (all-green → green else red); Qty/Unit + count header |
| Re-analyse | Rematch vs Rate_Master (no workbook re-read); lock released during AI |
| Re-extract | Workbook AI extract for that section (`mode=reextract`) |
| Select candidate | Keeps BOQ class/size/unit/capacity; uses analysis `database_version_id` |
| Make & Vendor | Lowest price defaults; same-price radio ties; status borders; Product rate view-only |
| Labour | Product rate → Labour rate → Total → Qty → Final; mode badge; aligned headers |
| Detail open | Default tab follows `BOQ.status` |
| Jobs | Stuck analysis heal/fail; progress reset; Celery concurrency 8 |
| Upload | `.xlsx` / `.xlsm` / legacy `.xls` (converted); **not** `.xlsb`; single sheet |

## Pending

- Restore `backend/tests/`
- Fresh migrations on EC2 after deploy (squashed history)
- UAT: Analyse / Re-analyse / Re-extract quality and speed
- Optional later: qty/slot hard-enforce; retire legacy Match/Confirm URLs

## Verify

```powershell
.venv\Scripts\python.exe backend\manage.py check
# After Celery code changes: restart the worker
```

## Session Log

Keep only the latest entry below. Older work is in `docs/CHANGELOG.md`.

### 2026-07-30 — Full App Smoke / UAT Pass

Completed: Local smoke of stack + key pages + live **Re-analyse** and
**Re-extract** on BOQ 82 (`hg`). Django check clean; Redis/Celery ping OK;
active DB `14_July_DB`. Pages 200: login, dashboard, BOQs, upload, database,
notifications, users, audit, profile; BOQ 81/82 detail tabs + status JSON.
Pending: Restore tests; EC2 migrate; restart Celery after code changes before
full Analyse jobs; Export needs Labour→Review complete (blocked as designed).
Issues: None blocking found in this pass.
Next: Restart Celery worker; optional full Analyse Celery job UAT.
