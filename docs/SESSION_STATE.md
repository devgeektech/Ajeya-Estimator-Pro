# BOQ_AI Session State

Compact active memory. Full spec: `docs/PRODUCT.md`. Schema: `docs/DATABASE.md`.
History: `docs/CHANGELOG.md` (do not duplicate session diaries here).

## Current Status

- **Phase:** Fresh start on new master DB schema (Rate_Master_Output / Labour_master_Output)
- **Migrations:** `database_manager.0002` (text `Product_ID` / `Rate_ID`) applied locally
- **Tests:** Suite moved to root `tests/` folder and basic view coverage added for all apps
- **Runtime:** `config.settings`, PostgreSQL `boq_db`, Django templates + Alpine/fetch, Celery
- **Active apps:** accounts, users, database_manager, boq, dashboard, notifications, audit
- **AI logging:** `AI_INSTRUCTION_LOGGING=False` in production; default follows `DEBUG`

## Active Workflows

**Database:** upload (global lock) → validate → import sheets (inactive) →
**embeddings must succeed** → activate → purge previous master data (synchronous
in the request). UI shows **Uploading…** across tab switches via
`/database/import-status/`. Other sheets counted for UI. Stored file stamped
`_{YYYYMMDD_HHMMSS}`. Last 10 upload records retained.

**BOQ tabs:** BOQ → Make list → Analysis → Make & Vendor → Labour → Review → Export

1. Upload workbook (+ optional make list) → parse to JSON
2. **Analyse** → AI extract products + map top Rate_Master_Output candidates (Celery)
3. Expert edit / **Re-analyse** / **Confirm** (100% lock) / Select candidate
4. Analysis **Next** → lowest-price Make & Vendor defaults
5. Make & Vendor **Next** → unlock Labour → complete → Review → Export
   (one workbook: Review + original BOQ tabs)

## Active Behaviour (in use)

| Area | Current behaviour |
| --- | --- |
| Sections | Serial-lineage groups with qty **slots**; empty slots show Add + Re-analyse |
| Analysis | Product tabs in **BOQ slot order**; match %; multi-product review **only** when product count ≠ Unit/Qty slot count |
| Matching | Chroma = Product_Helper only (AI validates top **5**; UI shows top **3**); Product_ID → Rate_Master / Labour from Postgres |
| Candidates UI | Summary = **Product ID** / Category / Sub / Class / Size / Unit / Capacity; open on unmatched; weak banner only when effective % below 50 |
| Re-analyse | Saves expert UI inputs + **AI Description**; empty inputs use full section; edited description leads recall + section; real match % (not forced 100%) |
| Confirm | Sets match to **100%** when product is correct but % is lower (hidden at 100%) |
| Select candidate | Prefills Rate_Master core fields + Attribute values into Analysis inputs; keeps that candidate's listed match % |
| Make list map | **AI-first** multi-target (v11): understands free text; compound lines can map multiple category/sub pairs (e.g. sprinkler + rosette); null sub = category-wide makes; heuristics soft-only; auto remap on stale mapping version |
| Make & Vendor | Product_ID → Rate_Master Make/Vendor/amounts from Postgres; not found/no match → dropdowns + Apply (green); cascade; Chroma not used for rates |
| Labour | Product_ID → Labour_master_Output; amount from **Labour_With_State_Multiplier** (fallback Total_Labour_Per_Unit); auto on Make & Vendor Next |
| Review | Same per-product slot qty + lineage UI; Export is one workbook (Review + BOQ). Review Base/Discount/Labour/Qty are inputs; Net, Sub_Total, Final material, Final Rate, totals are Excel formulas. BOQ Rate → Review Final Rate; Amount → Review Amount |
| Detail open | Default tab follows `BOQ.status`; renders stored data only — no AI in the GET |
| Jobs | Stuck analysis heal/fail; progress reset; Celery concurrency 8; Analyse completion uses `location.replace` auto-reload |
| Upload | Requires active DB; `.xlsx` / `.xlsm` / legacy `.xls` (converted); **not** `.xlsb`; single sheet |

## Pending

- Fill Rate_Master_Output with full Make/Vendor price rows; re-import if needed
- Restore `backend/tests/` (suite is at repo-root `tests/` today)
- First EC2 go-live: follow `docs/OPS.md` through master-database upload
- UAT Analyse / Re-analyse on 2.13 sand buckets → Product_ID 40; confirm rematch % not forced to 100
- Optional later: qty/slot hard-enforce; retire legacy Match/Confirm URLs

## Verify

```powershell
.venv\Scripts\python.exe backend\manage.py check --deploy
# After Celery code changes: restart the worker
# After embedding code changes: re-activate/re-import the master DB
# Go live: docs/OPS.md steps 1–14
```

## Session Log

Keep only the latest entry below. Older work is in `docs/CHANGELOG.md`.

### 2026-08-25 — Sync DB upload (no Celery) + embedding gate

Completed: Master DB import runs synchronously in the upload request under a global lock. UI Upload becomes Uploading… and polls status across tabs. Embeddings must succeed before activate; previous master data purged only on success; failed import leaves current DB. Django admin cannot force-activate.
Pending: Deploy when approved.
Issues: Long imports hold the HTTP worker; raise proxy/gunicorn timeouts if needed.
Next: Commit/merge/deploy when ready.





