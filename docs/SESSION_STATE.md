# BOQ_AI Session State

Compact active memory. Full spec: `docs/PRODUCT.md`. Schema: `docs/DATABASE.md`.
History: `docs/CHANGELOG.md` (do not duplicate session diaries here).

## Current Status

- **Phase:** Fresh start on new master DB schema (Rate_Master_Output / Labour_master_Output)
- **Migrations:** `database_manager.0002` (text `Product_ID` / `Rate_ID`) applied locally
- **Tests:** Suite removed — needs restoration
- **Runtime:** `config.settings`, PostgreSQL `boq_db`, Django templates + HTMX, Celery
- **Active apps:** accounts, users, database_manager, boq, dashboard, notifications, audit
- **AI logging:** `AI_INSTRUCTION_LOGGING=True` for now (embedding dumps truncated)

## Active Workflows

**Database:** upload → validate → import **Product_Helper** +
**Rate_Master_Output** + **Labour_master_Output** → activate → embeddings (sync).
Other sheets counted for UI. Stored file stamped `_{YYYYMMDD_HHMMSS}`. Last 10
uploads retained.

**BOQ tabs:** BOQ → Make list → Analysis → Make & Vendor → Labour → Review → Export

1. Upload workbook (+ optional make list) → parse to JSON
2. **Analyse** → AI extract products + map top Rate_Master_Output candidates (Celery)
3. Expert edit / **Re-analyse** (rematch; empty sections fall back to workbook extract)
4. Analysis **Next** → lowest-price Make & Vendor defaults
5. Make & Vendor **Next** → unlock Labour → complete → Review → dual Export
   (Review sheet | priced BOQ)

## Active Behaviour (in use)

| Area | Current behaviour |
| --- | --- |
| Sections | Serial-lineage groups with qty **slots**; empty slots show Add + Re-analyse |
| Analysis | Product tabs show match % + per-product slot Qty/Unit in header |
| Re-analyse | Rematch vs Rate_Master_Output; empty sections fall back to workbook extract |
| Select candidate | Keeps BOQ class/size/unit/capacity; uses analysis `database_version_id` |
| Make list map | Heuristic + AI category/sub-category; retries `pending` stubs only — `unmapped` is final |
| Make & Vendor | Same per-product slot qty as Analysis; lowest price defaults; status borders; line header Auto/filtered badge |
| Labour | Same per-product slot qty; Product rate → Labour → Total → Qty → Final |
| Review | Same per-product slot qty + lineage UI; export uses short/red Output headers; BOQ export fills original file on qty+unit rows |
| Detail open | Default tab follows `BOQ.status`; renders stored data only — no AI in the GET |
| Jobs | Stuck analysis heal/fail; progress reset; Celery concurrency 8 |
| Upload | `.xlsx` / `.xlsm` / legacy `.xls` (converted); **not** `.xlsb`; single sheet |

## Pending

- Fill Rate_Master_Output with full Make/Vendor price rows; re-import
- Restore `backend/tests/`
- Fresh migrations on EC2 after deploy
- UAT Analyse / Make & Vendor / Labour against new Product_ID + Final_Material_Amount
- Optional later: qty/slot hard-enforce; retire legacy Match/Confirm URLs

## Verify

```powershell
.venv\Scripts\python.exe backend\manage.py check
# After Celery code changes: restart the worker
```

## Session Log

Keep only the latest entry below. Older work is in `docs/CHANGELOG.md`.

### 2026-08-06 — Review serial from qty-row parent

Completed: Review S. No. / export Ser no now use each product's qty-row serial
qualified by its nearest structural parent (`5.1 a)` instead of wrong group
`5 a)(A)`).
Pending: UAT Review S. No. against uploaded BOQ numbering.
Issues: None new.
Next: UAT Review serials on multi-level sections (e.g. 5.1 / 5.2).
