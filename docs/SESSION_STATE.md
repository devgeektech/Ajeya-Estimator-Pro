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
`/database/import-status/`. Only Product_Helper / Rate_Master_Output /
Labour_Master_Output imported; other sheets ignored. Stored file stamped
`_{YYYYMMDD_HHMMSS}`. Newest **10** upload records retained; on successful 11th,
oldest row + `media/database/` workbook deleted.

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
| Candidates UI | Summary = **Product ID** / Category / Sub / Class / Size / Unit / Capacity; open on unmatched; weak banner only when effective % below 50; Category/Sub/Size/**Attributes** stay from extract when found (else empty; placeholder **Not found**) |
| Re-analyse | Saves expert UI inputs + **AI Description**; recall = hint + filled inputs + slot line (full section only if identity empty); real match % from structured fields only (not AI jitter; not forced 100%); unfound inputs stay empty |
| Confirm | Sets match to **100%** when product is correct but % is lower (hidden at 100%) |
| Select candidate | Prefills Rate_Master core fields + Attribute values into Analysis inputs; keeps that candidate's listed match % |
| Matching score | Weighted filled extract fields vs catalog (Sub 30 / Cat 24 / Size 18 / …); blank inputs omitted; thin size+unit identity capped; operating temp ≠ Size |
| Make list map | **AI-first** multi-target (v11): understands free text; compound lines can map multiple category/sub pairs (e.g. sprinkler + rosette); null sub = category-wide makes; heuristics soft-only; auto remap on stale mapping version |
| Make & Vendor | Product_ID → Rate_Master; AI Description + Rate/Product id; **Not available** / **Not listed** / **Not in Db**; Next confirms Labour promotion |
| Labour | Unlock promotes Not listed/Not in Db → **Not available** (red); missing labour = orange **No labour**; complete → Review NA |
| Review / Export | Not available (red); Amount = “Not available”; other columns unchanged |
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

### 2026-09-21 — Fix Top DB Candidates taxonomy focus and AI extraction misclassification

Completed:
- Adaptive size mismatch penalty in `structured_match_score`: reduced from 45 to 20 when extracted sub_category matches the catalog row's sub_category (taxonomy-confirmed). SLUICE VALVE at nearby size now scores 56% vs PIPE at exact size 23% — correct family wins.
- Added `_guarantee_taxonomy_hits` in `ProductMatchingService.match_product`: when no Chroma hit belongs to the extracted category+sub_category, a direct SQL query injects up to 20 matching rows so `_rank_candidates` can score them. Prevents Chroma returning only wrong-family rows.
- Taxonomy-aware sort key in `_rank_candidates`: valid (non-type-mismatch) candidates sort by `_taxonomy_score` (sub_category match = 1.0, category match = 0.5) first, then blended confidence. Correct product family always tops the list.
- Added `product_noun_taxonomy_hints` (36 entries) to `build_database_context` in `ai/context.py`: maps BOQ product nouns to Category/Sub_Category. Landing valve, external hydrant, branch pipe, reflux/NRV valve etc. now have explicit entries.
- Updated `ai/prompts/extract_products.txt`: added CRITICAL TAXONOMY TABLE at top, HYDRANT/VALVE/reflux examples in STEP 1, clarified material keywords (SS, CI, MS) describe material — not product type.
Pending: None
Issues: None
Next: Re-run Analyse on BOQ with stainless steel landing valve and sluice valve sections to verify AI extracts correct taxonomy and top DB candidates are correct family.
