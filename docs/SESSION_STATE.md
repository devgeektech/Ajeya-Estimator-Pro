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
3. Expert edit / **Re-analyse** (product rematch with filled attrs; empty section re-extract)
4. Analysis **Next** → lowest-price Make & Vendor defaults
5. Make & Vendor **Next** → unlock Labour → complete → Review → dual Export
   (Review sheet | priced BOQ)

## Active Behaviour (in use)

| Area | Current behaviour |
| --- | --- |
| Sections | Serial-lineage groups with qty **slots**; empty slots show Add + Re-analyse |
| Analysis | Product tabs show match % + per-product slot Qty/Unit in header |
| Re-analyse | Product-wise: fresh DB recall with filled fields + BOQ section; synonym-aware (DI=ductile iron); AI nearest match + prefill; empty section: workbook re-extract |
| Select candidate | Prefills Rate_Master core fields + Attribute values into Analysis inputs; keeps that candidate's listed match % |

| Make list map | Heuristic + AI category/sub-category (v4 synonym rules); remaps on version bump; `unmapped` final per version |
| Make & Vendor | Product_ID → Rate_Master Make/Vendor/amounts from Postgres; Find in DB yellow; cascade; Chroma not used for rates |
| Labour | Product_ID → Labour_master_Output from Postgres (auto on Make & Vendor Next); Apply labour reloads |
| Review | Same per-product slot qty + lineage UI; export uses short/red Output headers; BOQ export writes Qty/Rate/Amount on qty+unit rows; zero-qty / Rate Only rows orange on both exports |
| Detail open | Default tab follows `BOQ.status`; renders stored data only — no AI in the GET |
| Jobs | Stuck analysis heal/fail; progress reset; Celery concurrency 8 |
| Upload | Requires active DB; `.xlsx` / `.xlsm` / legacy `.xls` (converted); **not** `.xlsb`; single sheet |

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

### 2026-08-10 — Backend synonym / matching cleanup (no UI)

Completed: Deduped make-list hint tables into `utils/product_synonyms.py`; removed
unused synonym wrappers, write-only `catalog_candidates`, and leftover Top-5 slice;
single `CANDIDATE_LIMIT=3` shared by matching + AI mapping.
Pending: UAT Analyse / Re-analyse / Make List after Celery restart.
Issues: None.
Next: UAT Make List → correct makes on Analysis Make & Vendor.
