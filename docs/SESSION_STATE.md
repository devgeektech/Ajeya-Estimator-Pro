# BOQ_AI Session State

Compact active memory. Full spec: `docs/PRODUCT.md`. Schema: `docs/DATABASE.md`.
History: `docs/CHANGELOG.md` (do not duplicate session diaries here).

### 2026-10-13 — Labour Rate Retrieval & Stale Database Version Resolution Fix

Completed:
- **Active Database Version Resolution & Purged Version Fallback**:
  - Identified root cause for un-fetched labour rates on live BOQ `MANESAR FACTORY`: BOQ had stored `database_version_id = 4`. When database version 5 was uploaded and activated, PostgreSQL purged master data rows for inactive versions (`DatabaseVersion` 4, 3, etc.). When `BOQLabourService` queried `Labour_master_Output` with `database_version_id = 4`, 0 rows were found.
  - Implemented `resolve_active_database_version_id` in `apps/database_manager/services/activation.py` to ensure queries always resolve to an active DatabaseVersion holding master data.
  - Updated `_database_version_id` in `BOQLabourService` and `MakeVendorSelectionService` to use `resolve_active_database_version_id` and sync the active database version onto `analysis_data`.
  - Updated `LabourDetailRetrievalService` and `RateDetailRetrievalService` `__init__` to fall back to the active database version when passed an inactive or missing database version ID.
  - Added integral float string ID normalization (e.g. `"154.0"` -> `"154"`) in `LabourDetailRetrievalService.get_by_product_id`.
- **Export Hyperlink MergedCell Guard**:
  - In `boq_export_service.py`, guarded hyperlink assignment with `not isinstance(cell, MergedCell)` to prevent OpenXML `AttributeError`.
- **Test Coverage**:
  - Added `tests/boq/test_labour_retrieval.py` verifying active DB version fallback and numeric ID formatting. All 205 tests passing cleanly.

Pending: None.
Issues: None.
Next: Deploy changes to EC2 and re-apply auto labour on BOQ 27 (MANESAR FACTORY).

### 2026-10-12 — Confidence Score Re-weighting, MS vs GI Pipe Disambiguation, & Export Sheet Yellow/#1976E7 Styling

Completed:
- **Confidence Score Weight Adjustment (70% Extracted Inputs, 30% AI Section Understanding)**:
  - Reduced `category` weight from 30% to 15% (-15%).
  - Reduced `sub_category` weight from 40% to 25% (-15%).
  - Allocated remaining 30% to AI understanding and semantic section meaning in candidate scoring (`_CHROMA_WEIGHT = 0.30`, `_STRUCTURED_WEIGHT = 0.70`).
  - Updated `_compute_match_confidence` in `product_ai_common.py` to blend 30% AI understanding (`ai_weight = 0.30`).
  - Updated `_TEXT_WEIGHTS` in `product_helper_matching_service.py` to match (category 15%, sub_category 25%).
- **MS vs GI Piping Disambiguation & Conflict Prevention**:
  - In `product_matching_service.py`, added pipe material conflicts (`MS` vs `GI`, `CPVC`, `UPVC`, `SS`) to `_SUB_CATEGORY_CONFLICTS` and phrase pairs.
  - In `product_type_conflicts`, added explicit check flagging candidates whose pipe material contradicts section text (caps confidence at 29%, preventing 90%+ scores for wrong metals).
  - In `product_extraction_sanitize.py`, reinforced `_sanitize_sub_category` for PIPE to correct hallucinated GI sub_category to MS when evidence specifies M.S./Mild Steel/Black ERW.
  - In `extract_products.txt`, added piping base material dominance rule ensuring section header material applies to all child diameter slots regardless of joint fitting notes.
- **Export Sheets Styling & Formula Preservation**:
  - In `boq_export_service.py`, styled entire highlighted calculation columns (I, O, Q, S, U, V, W) in solid yellow (`#FFFF00`) for headers and all data rows.
  - Styled all other headers in `#1976E7` royal blue with bold white font.
  - Removed literal `Not available` text across Review and BOQ sheets: leaves input cells blank while keeping active calculation formulas (`=IF(...)`, `=N(...)`, etc.) in place on all rows.
  - Maintained bidirectional hyperlinks and formula linkage between BOQ and Review sheets so manual entries in Excel calculate seamlessly.
- **Tests**: All 147 tests in `tests.boq` pass.

Pending: None.
Issues: None.
Next: Deploy and verify in production runtime.

### 2026-10-12 — Immediate Confirm Manually Responsiveness & Idempotent Match Locking

Completed:
- **Immediate UI Feedback & Unblocked Execution**:
  - In `_extraction_table.html`, added immediate button feedback (`Confirming…`) and replaced the unconstrained `while (formData.saving)` loop with a bounded 100ms wait.
  - Set `formData._confirming = true` so any pending background auto-save cannot overwrite the confirmed product's score or status.
  - Switched DOM update in `confirmExtractionMatch` to `replaceExtractionLine` first (with `activeProduct` preserved) to atomically update line headers, tabs, borders, badges, and card state in a single synchronous DOM replacement.
  - Stripped `x-cloak` from inserted DOM trees so dynamic content is never hidden by `[x-cloak] { display: none !important; }`.
  - Added `extraction-line--confidence-orange` to `syncExtractionLineConfidence` to ensure orange borders transition properly to green.
- **Idempotency & Grouped Slot Row Matching**:
  - In `boq_extraction_edit_service.py`, made `confirm_match` idempotent: if a product is already confirmed at 100%, return the product cleanly instead of raising `ValidationError("This product is already confirmed.")`.
  - In `boq_extraction_edit_service.py`, targeted `product_row_id` first when locating the target product to accurately match slot products in grouped rows, while preserving the anchor row ID for frontend DOM replacement.
  - In `views.py`, updated `_render_extraction_line_html` with a fallback to find lines by child slot `source_row_id`, guaranteeing non-empty line HTML is returned.
  - In `boq_extraction_display_service.py`, enabled `show_confirm_match` for products where a candidate was picked (`selection_source == "select"`) with `< 100%` match so experts can confirm candidates immediately.
- **Test Coverage**:
  - Added unit tests in `tests/boq/test_extraction_edit.py` and `tests/boq/test_product_id_visibility.py` verifying `confirm_match` idempotency, slot product targeting, and candidate button visibility.
  - Verified all 145 tests pass cleanly.

Pending: None.
Issues: None.
Next: Monitor live manual confirmations in the UI.

### 2026-10-12 — Export Sheets Bidirectional Hyperlinking & Review Calculation Column Highlighting

Completed:
- **Export Sheets Bidirectional Hyperlinking (Rate & Amount)**:
  - In `boq_export_service.py`, implemented ECMA-376 OpenXML internal worksheet hyperlinks (`openpyxl.worksheet.hyperlink.Hyperlink`) between the `Review` sheet and the `BOQ` sheet.
  - On the `BOQ` sheet: Rate and Amount cells link directly to the corresponding product's Final Rate (col S) and Amount (col W) on the `Review` sheet (`location="'Review'!S{row}"` and `location="'Review'!W{row}"`) with descriptive tooltips.
  - On the `Review` sheet: Final Rate (col S) and Amount (col W) link directly back to the item's Rate and Amount cells on the `BOQ` sheet (`location="'BOQ'!{col}{row}"`).
  - Added support across both standard workbook filling and JSON-fallback BOQ tab generation.
- **Review Sheet Formula Column Name Updates**:
  - In `boq_review_display_service.py`, updated `REVIEW_OUTPUT_HEADER_SPECS` to incorporate exact algebraic formula notation into column headers:
    - `Net_Material_Rate (G*(1-H))`
    - `Sub_Total (K+L+M+N)`
    - `Final_Material_Amount (O+P)`
    - `Final Rate (Q+R)`
    - `TOTAL MATERIAL (Q*T)`
    - `TOTAL LABOUR (R*T)`
    - `Amount (U+V)`
- **Review Sheet Calculation Column Highlighting**:
  - In `boq_export_service.py`, designated `_HIGHLIGHTED_REVIEW_COLS` (cols 9, 15, 17, 19, 21, 22, 23).
  - Styled headers in row 1 with distinct accent fill `_FORMULA_HEADER_FILL` (`#BDD7EE`, soft pastel blue).
  - Styled data cells in those columns with `_FORMULA_CELL_FILL` (`#EDF2F8`, subtle ice blue) while safely preserving error/warning fills (`_MISSING_PRODUCT_FILL`, `_ZERO_OR_RATE_ONLY_FILL`, `_ACTIVITY_ONLY_FILL`).
- **Test Coverage**:
  - Extended `tests/boq/test_boq_export.py` to assert header labels, header fill colors, and bidirectional hyperlinks.
  - All 144 tests in `tests.boq` passing cleanly.

Pending: None.
Issues: None.
Next: Test Excel exports in desktop Excel.

### 2026-10-09 — Make & Vendor Dropdown Scoping, Approved Makes Completeness & Price Preview

Completed:
- Added a distinct **"Available make"** dropdown after "Approved make" in the Make & Vendor top bulk panel (**Apply to Category / Sub-category**).
- Enforced strict mutual exclusivity: selecting a make from "Approved make" automatically clears "Available make", and selecting from "Available make" automatically clears "Approved make". Only one can be active at a time.
- Fixed **Approved make** loading so that 100% of approved makes from the Make List are loaded without dropping makes that lack Rate_Master rows in that sub-category.
- Ensured "Approved make" is always a select dropdown. When there are no approved makes, it displays a single option `"No Approved Make Found"` and remains disabled, never loading database makes into the approved dropdown.
- Fixed **Vendor** scoping: strictly loads vendors for the active make within the selected sub-category by removing the parent category vendor fallback that previously leaked random vendors from other subcategories.
- Fixed **Available make** selection: cleared stale auto-selection on sub-category change so it never defaults to a make from another scope.
- Fixed **Price preview**: removed sub-category requirement so prices load and display dynamically at both category and sub-category scopes for both approved makes and available database makes.
- Removed text inputs from the bulk panel for both make and vendor to ensure clean, consistent select inputs.
- Robust vendor loading: implemented case/whitespace-tolerant lookup in `vendorOptions` so vendors are reliably loaded from `vendors_by_make` whether an approved make or database make is selected.
- Updated `make_vendor_rates.py` and `make_vendor_cascade.py` to prevent injecting database makes into `make_options`.
- Updated `_lowest_amount_maps` to compute lowest price and vendor maps for all available database makes and approved makes, enabling real-time Price preview when selecting any make or vendor.
- Updated `apply_subcategory_make` in `make_vendor_cascade.py` to allow makes from either the approved make list or the database's available makes, cascading make/vendor selections to all analysed products in the category/sub-category.
- Removed the **"Review"** and **"Vendor review"** tags and notes from the Make & Vendor page, since Product IDs are already assigned on the Analysis page.
- Make & Vendor selection now strictly loads the Product ID + Rate ID combination from `Rate_Master_Output`, directly setting status to `"Matched"` upon rate retrieval.
- Disabled `_flag_same_material_rate_vendor_review` and removed the `vendor_review_count` tag from the summary header.
- Fixed suggestion match percentage badge in `_extraction_line.html`: removed `|default:product.attribute_confidence` which caused 0% database matches to falsely render as 100% match due to Django template `default:` evaluating 0 as falsy.
- All 144 tests in `tests.boq` passing cleanly.

Pending:
- None.

Issues: None.

Next: Test Make & Vendor bulk selection in browser with real BOQ data.

### 2026-10-07 — Re-analyse Missing Input Penalty & AI Re-extraction Fix

Completed:
- Modified `structured_match_score` to properly penalize missing inputs (`size`, `class`, `capacity`, `attributes`) if the DB candidate requires them and the BOQ has evidence. This lowers the Re-analyse score from 100% when the user's filled inputs are incomplete compared to the catalog row.
- Updated the AI mapping prompt (`map_product_match.txt`) to aggressively scan the `description_hint` and `boq_row.description` to re-extract missing attributes if the user leaves them blank during Re-analyse.
- Replaced the `alert` popup on the Extract row with a visually integrated, top-of-screen `appAlert` banner.
- Updated Re-analyse highlights: selected Database Candidate attributes are now highlighted via text color (e.g. `text-emerald-700 font-semibold`) instead of a circular background to improve readability.
- **Fixed PDF Make List Extraction using pdfplumber**: Replaced `pypdf` with `pdfplumber` to bypass PDF layout issues and corrupt fonts (`Tf` missing).
- **Tabular Extraction**: Rewrote `parse_make_list_pdf` to cleanly preserve column separation by using `extract_table` and spacing it, falling back to layout extraction safely.
- **Lowercase Brand Preservation**: Updated boundary peeling in `text_boundary.py` (`repair_description_and_makes`) to intelligently `.title()` lowercase brand names so they pass validation and aren't dropped.
- Resolved IDE linter warnings in `test_conflict.py` and `pdf_make_list_parser.py`.
- **Deployed Fixes**: Merged `new-changes` to `main` locally and pulled latest code onto the live EC2 server.

Pending:
- None.

Issues: None.

Next: Monitor live system for feedback on pdfplumber table extraction logic.

### 2026-09-24 — Dynamic Contextual AI Extraction and Logical Confidence Scoring

Completed:
- Replaced static/hardcoded product examples with a generalized, dynamic **MOUNTED / CONTEXTUAL ITEMS RULE** in `ai/prompts/extract_products.txt`. The AI is now instructed conceptually to distinguish between the primary component being purchased (e.g., instruments, valves) and the underlying structure it mounts to (e.g., pipes, ducts), ensuring it works dynamically across all scenarios and doesn't mistakenly categorize mounted items as pipes.
- Updated `description_hint` instructions in `extract_products.txt` to ensure the AI explicitly includes all extracted attributes to aid logical matching.
- Updated `map_product_match.txt` to instruct the AI to calculate the confidence score strictly based on the extracted metadata matching the candidate's fields, specifically penalizing mismatches in size and material, and forbidding arbitrary or random scores.
- **Fixed Dashboard BOQ Deletion Redirect**: Updated `BOQDeleteView` to check for and redirect to a `next` query parameter. Updated the BOQ row actions form template (`_boq_row_actions.html`) to pass `request.path` as the `next` param, ensuring users remain on the Dashboard after deleting a BOQ instead of being bounced to the BOQ list page.

Pending:
- None.

Issues: None.

Next: Test extraction on real BOQ data featuring diverse dynamically-contextual items.


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
### 2026-10-07 — Re-analyse confidence fix and Top DB selection highlighting

Completed:
- Highlighted text color for product candidate IDs in the Top DB candidates when they match the currently assigned `db_product_id` (or when none is assigned), rather than drawing a background circle.
- Adjusted server `.env` variables (`AI_ROW_EXTRACTION_BATCH_SIZE=10`, `AI_PRODUCT_MAPPING_BATCH_SIZE=10`, `AI_EXTRACT_PARALLELISM=2`) to align with local settings and eliminate the production performance bottleneck.
- Switched native `alert()` calls in `_extraction_table.html` to use a consistent custom `window.appAlert`.
- Fixed the issue where a manual "Top DB candidate" selection artificially locked the product into a 100% confidence score during subsequent `Re-analyse` executions. Now, `rematch_product` explicitly clears pre-filled database attributes (`attribute_source == "database"`) prior to the AI map request, forcing a genuine re-extraction from the product description and resulting in an honest match confidence score.
- Fixed an issue where the Re-analyse button continued to use the previously selected candidate's ID and matching candidates to constrain the new AI extraction. Now `db_candidates` and `product_id` are explicitly cleared so the AI can use the updated inputs to find completely fresh DB candidates.

Pending: None
Issues: None
Next: Continue with further BOQ refinements.
