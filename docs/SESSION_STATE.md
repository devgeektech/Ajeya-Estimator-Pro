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

**Database:** upload → validate → import **Rate_Master_Output** +
**Labour_master_Output** only → activate → embeddings (sync). Other sheets counted
for UI. Stored file stamped `_{YYYYMMDD_HHMMSS}`. Last 10 uploads retained.

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
| Analysis | Product tabs; confidence border (all-green → green else red); Qty/Unit + count header |
| Re-analyse | Rematch vs Rate_Master_Output; empty sections fall back to workbook extract |
| Select candidate | Keeps BOQ class/size/unit/capacity; uses analysis `database_version_id` |
| Make list map | Heuristic + AI category/sub-category; retries `pending` stubs only — `unmapped` is final |
| Make & Vendor | Lowest price defaults; same-price radio ties; status borders; Product rate view-only |
| Labour | Product rate → Labour rate → Total → Qty → Final; mode badge; aligned headers |
| Review | Client Output format columns; Export Review sheet + Export BOQ |
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

### 2026-08-03 — Master DB workbook alignment + Review export

Completed: Verified `BOQ_Master_03 Aug_2026.xlsx` against models/importer.
Rate columns/types OK (no migration). Fixed labour sheet title alias
(`Labour_Master_Output`) and `Labour_With_State_Multiplier` mapping. Dry-map:
184/184 rates, 101/101 labour buildable. Review dual-export also local.
Pending: Upload the new workbook in UI to activate; restore tests.
Issues: Workbook labour Product_ID `101` has no matching rate row (data).
Next: Upload master DB; UAT Make & Vendor / Labour / Review exports.

Branch: `user/vikas/new_database` = `origin/user/vikas/new_database` (`9f08fe7`).
Uncommitted local work is Review export + this import fix only.
