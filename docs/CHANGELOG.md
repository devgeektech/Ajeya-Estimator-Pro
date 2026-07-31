# Changelog

Meaningful product and technical changes. Day-by-day micro-entries older than
the summaries below live in **git history** (`git log -- docs/`).

---

## 2026-07-31 — Guarantee Product Coverage For Every Qty Slot

- Changed extraction from “exactly one product per slot” to **at least one per
  slot**. Six filled Unit/Qty rows now require at least six products, while
  separately evidenced extras are preserved rather than truncated.
- Added a focused AI correction pass for sections where any slot is omitted.
  The corrected response must cover every `qty_row_id` and retain real extras.
- Added a final fault-containment fallback: if the correction still misses a
  slot, a review product built only from that slot's BOQ evidence preserves the
  line. It carries the slot quantity/unit, invents no catalog fields, and is
  visibly flagged for review.
- Verified service postconditions: 6 slots / 3 AI products → 6 products; 2 / 2
  remains 2; 2 slots / 3 AI products remains 3.

## 2026-07-31 — Multi-product Qty Visible Beside Tabs

- Multi-product Analysis sections hid the section header qty and only put values
  inside each product card (often missed under match/candidates). The active
  product's quantity/unit now sits on a dedicated row under the Product tabs and
  updates when switching tabs (e.g. ``4 / 0 / 1 No.``).

## 2026-07-31 — Candidates Collapsed By Default

- Analysis ``Top database candidates`` ``<details>`` is closed again by default;
  expand on click when needed.

## 2026-07-31 — Per-product Quantity On Analysis Cards

- A multi-product section showed one section-level quantity/unit, so switching
  product tabs kept displaying the first slot's figures even though each product
  binds to its own Unit/Qty slot.
- `_shape_product` now exposes the product's own `quantity` / `quantity_unit`
  and the card renders them, so Product 1 and Product 2 show their own values.
  The section header keeps its single figure only when there is one product.

## 2026-07-31 — Labour Summary Shows Total Products

- Labour tab summary format:
  ``Products Y · Labour Charges found for X products · Mode: Manual/Auto``
  with product total, found count, and mode bold.

## 2026-07-31 — Remove Login Welcome Flash

- Dropped the green ``Welcome back, …`` Django message shown on the dashboard
  after login.

## 2026-07-31 — Candidate Tech Key Uses Dot Separators

- Analysis candidate keys now display as ``FITTINGS . Elbow .  .  .  . 90Deg``
  instead of pipe-separated ``FITTINGS|Elbow||||90Deg``. Stored keys are unchanged.

## 2026-07-31 — Compact Candidate Confidence Text

- Replaced rounded percentage and **Selected** badges in the Analysis candidate
  list with plain text, removing badge padding and margins.

## 2026-07-31 — Show Top Candidates By Default

- "Top database candidates" was always stored but sat inside a collapsed
  `<details>`, so it looked missing right after Analyse. It now renders open.
- Tightened the candidate list spacing (row gap 4px → 1px, 0 on the Analysis
  canvas; list top margin 8px → 4px) so three candidates read as one block.

## 2026-07-31 — Verify Chroma Fix On A Fresh Analyse

- First Analyse still produced no confidence: the running Celery worker was
  started before the Chroma fix and Celery does not auto-reload, so the task
  kept executing the old code (BOQ 98 mapped 1 of 39 products).
- Reproduced the failure deliberately — a long-lived client plus a concurrent
  full re-index of the collection — and confirmed the reconnect-and-retry in
  `query_similar` recovers where the old code raised.
- After restarting the worker, a Celery-dispatched extraction of BOQ 98 gives
  22 matched / 12 provisional / 5 unmatched and renders 32 confidence badges.

## 2026-07-31 — Multi-product Review = Qty/Product Mismatch

- Analysis **Multi-product review** now flags only when product count ≠ Unit/Qty
  row count in a section (1 qty → 2+ products, or 2 qty → 1 product). Equal
  counts are not flagged.

## 2026-07-31 — Labour Apply Visible In Auto Mode

- The Labour toolbar **Apply labour** button was only shown in Manual mode, so
  Auto had no way to load charges even though `applyAuto()` existed. The button
  is visible again for both modes: Auto calls `apply_auto`, Manual calls
  `apply_manual`.

## 2026-07-31 — Multi-product Flag + Make/Vendor Vendor Lists

- Restored the Analysis **Multi-product review** badge: any section with two or
  more extracted products is flagged (the old “products > qty rows” rule never
  fired after extraction was locked to one product per slot).
- Make & Vendor product cards now reload the full vendor list when Make changes
  (`vendors_by_make` + Alpine `vendorOptions`), instead of keeping a static
  single/lowest vendor from the initial render.
- Vendor lookup falls back to the whole category when the sub-category only has
  one vendor for that make, so alternatives like HD → Astral / HD appear.

## 2026-07-31 — Stop A Chroma Hiccup From Wiping Every Match

- Analysis showed no confidence badges, no database match and no attributes for
  any product. Cause: `chromadb.errors.InternalError: Error finding id`. Chroma
  caches one system per path per process, so the long-lived Celery worker kept
  serving the segment it opened first; the database re-import rewrote every
  vector and the worker's handle went stale.
- One failed recall aborted the whole run: `match_product` only caught
  `AIServiceError`, so the Chroma error propagated through `map_products` /
  `map_rows` up to `_enrich_extracted_attributes`, whose blanket `except` threw
  away the mapping for all 39 products and left the extraction looking complete.
- Three fixes: `ChromaEmbeddingStore.query_similar` reopens the index and retries
  once; `match_product` degrades any recall failure to the SQL fallback instead
  of raising; `map_rows` contains a chunk failure to that chunk.
- Verified on BOQ 97 — 22 matched / 12 provisional / 5 unmatched, 32 confidence
  badges and 118 candidate percentages rendered, page open 1.6s.
- The Celery worker must be restarted to pick this up; it does not auto-reload.

## 2026-07-31 — Remove Blocking AI From BOQ Detail Page

- `BOQDetailView.get_context_data` ran `ensure_attribute_enrichment()`, a full
  AI product-mapping pass (`map_product_match` calls + embeddings), inline on
  every analysis page open. After Analyse finished, the poll redirected to the
  Analysis tab and that page then blocked for tens of seconds — the "stuck after
  Analysis complete" report. It also broke the rules banning AI calls in views
  and blocking BOQ views.
- Extraction already enriches inside the Celery task (`run_extraction` →
  `_enrich_extracted_attributes`), so the view-side backfill was removed. Detail
  page open measured at ~0.2s for a 65-row / 39-product analysis. Products that
  still need mapping are handled by Analyse / Re-analyse, both async.

## 2026-07-31 — Recent BOQs Seven-Row Layout

- Dashboard Recent BOQs now reserves seven equal row slots across the available
  panel height. Seven results fill the panel; one or two results occupy only
  their own slots rather than stretching to fill it. Mobile keeps the normal
  scrollable table layout.

## 2026-07-31 — Fix BOQ Detail Page Re-running AI On Every Open

- `ensure_mappings` treated any make-list material without a category as
  "incomplete", so the 24 legitimately `unmapped` materials re-triggered the full
  AI mapping pass (3–4 OpenAI calls, ~30s) on **every** BOQ detail open. The
  browser gave up mid-response — the "Broken pipe" log lines and BOQs that would
  not open. Varying AI output also re-persisted the payload each time, so it
  never settled.
- `unmapped` is now a final answer; only `pending` stubs (taxonomy was empty) are
  retried. Detail page open drops from ~30s to ~5ms with zero AI calls.
- Backfilled BOQs 83–87 so no stored make list still holds pending stubs.

## 2026-07-31 — Text Master IDs + Fail Loudly On Empty Import

- Root cause of blank make-list Mapped Category / Sub-category: the active
  workbook used `P1001`-style `Product_ID`, which failed the integer parser, so
  all 200 Rate_Master_Output rows were silently skipped and the category
  taxonomy was empty.
- `Product_ID` and `Rate_ID` are now `varchar(64)` on both master models
  (`database_manager.0002`), so workbook ID codes import as written. Excel
  floats like `1001.0` normalize to `1001`. Chroma metadata and the labour
  lookup compare IDs as strings; PK-based references are untouched.
- Database import now raises when a required sheet has rows but none are
  importable, naming the empty columns, instead of activating an empty version
  and purging the previous one.
- BOQ upload form no longer prints the browser's bare "Failed to fetch" when the
  request cannot reach the server; it explains the connection failed, notes the
  files are still selected, and logs the raw error to the console.

## 2026-07-31 — BOQ Sheet Left Alignment

- Forced BOQ and Make List header/data cells left-aligned without affecting
  other tables; removed preserved template whitespace and bumped CSS to `?v=71`.

## 2026-07-31 — Make List Category Remapping + Drop Re-extract

- `ensure_mappings` remaps incomplete/pending make-list category stubs when
  Rate_Master_Output taxonomy becomes available (no longer stuck forever).
- Removed Analysis **Re-extract** button; keep **Re-analyse** only (empty
  sections still fall back to workbook extract in the service).
- Documented that blank Mapped Category columns need a non-empty rate DB.

## 2026-07-31 — BOQ / Make List Sheet Column Layout

- Sheet headers carry a `col_class`; rows render `display_cells` so each cell
  keeps its column class. Both tabs use fixed percentage widths.
- BOQ columns: S.No 5% / Description 47% / Unit 8% / Qty 8% / Rate 11% / Amount 11%.
- Make List keeps Mapped Category and Mapped Sub-category; all columns
  left-aligned (dropped the right-aligned Approved Makes with 4.5rem padding).
- Cache-bust `app.css` to `?v=70`.

## 2026-07-31 — Dashboard Recent BOQ Headers

- Recent BOQs table headers slightly bolder (`font-weight: 800`).

## 2026-07-31 — Fix BOQ / Make List Sheet Layout

- Make List sheet CSS assumed 3 columns while display builds 5 (Mapped Category /
  Sub-category / Approved Makes); Approved Makes was crushed to a vertical strip.
- Sheet template now renders `col_class` + `display_cells`; fixed column widths for
  BOQ (S.No / Description / Unit / Qty / Rate / Amount) and Make List.
- Cache-bust `app.css` to `?v=67`.

## 2026-07-31 — Unified List Page Layout

- Aligned BOQ, Database, Notifications, Users, and Audit tables to the same
  Audit Log structure (left-aligned columns, ghost icon actions, shared sort).
- Unified topbar min-height and action button sizing across pages.
- Shared list-search / table-sort / list-actions styles in `app.css`.

## 2026-07-31 — List / Profile UI Layout Fixes

- Moved list Search into a separate horizontal card (`Search :` + textbox) above
  table panels (BOQ, Database, Audit, Notifications, Users).
- Notifications unread badge and User Management Create User moved to topbar right.
- Dashboard Recent BOQs rows no longer stretch to fill the card when few items.
- Profile Account and Password cards stack vertically.

## 2026-07-31 — Vendor-Only Selection Contract

- Removed supplier compatibility keys and fallbacks from Make & Vendor persistence,
  POST handling, display shapes, templates, labour/review, and export.
- Renamed vendor option/catalog/review fields and removed transitional
  `Rate_Master` / `Labour_Master` model aliases.
- Aligned `docs/PRODUCT.md` wording to Rate_Master_Output / Labour_master_Output,
  Vendor, and Product_ID (no Tech_Key / Supplier).

## 2026-07-30

**UI / viewport**
- Removed desktop `html { zoom: 0.9 }` that left a grey strip under full-height
  pages (login, dashboard, and others) on Windows Chrome / DPI setups.
- Layout and auth use `min-height: 100dvh` (with `100vh` fallback); dashboard
  lock uses `100dvh`; auth pages set body to the dark canvas color.
- Auth shell uses `position: fixed; inset: 0` so it always covers the viewport.
- With local `DEBUG=False`, WhiteNoise serves `staticfiles/` — ran
  `collectstatic` so the fix is actually live (stale collected CSS was the
  reason the first edit looked unchanged).

**Master database restructure**
- Ingest only `Rate_Master_Output` + `Labour_master_Output` (both required).
- Models/tables renamed to match sheets; removed TOR / State / Labour_Structure.
- `Product_ID` / `Rate_ID` / `Vendor` / `Final_Material_Amount`; labour by Product_ID.
- Stored upload files datetime-stamped; detail UI counts all workbook sheets.
- Embeddings: one vector per rate row; fresh `database_manager.0001_initial`.

**Docs**
- `README.md` and `docs/OPS.md`: Windows (PowerShell) setup steps alongside
  Linux/macOS (venv, migrate, collectstatic, runserver, tests, Celery).
- `DATABASE.md` / `PRODUCT.md` updated for Output-sheet schema.

**UAT / smoke**
- Local full-stack smoke: Django check, Redis, Celery ping, pages, status JSON;
  live Re-analyse + Re-extract on BOQ `hg` OK (status preserved).

**Docs (earlier)**
- Compacted `SESSION_STATE.md`, `CHANGELOG.md`, and `MAKE_VENDOR_APPROACH.md`;
  refreshed stale `PRODUCT.md` overview to the active pipeline.

**Extraction / Re-analyse**
- AI instruction logging kept on; embedding log bodies truncated.
- Re-analyse: no long DB lock during AI; preserves pipeline status; keeps unmatched attrs.
- **Re-extract** (workbook) vs **Re-analyse** (Rate_Master rematch).
- Batched product embeddings; `AI_ROW_EXTRACTION_BATCH_SIZE` / `AI_PRODUCT_MAPPING_BATCH_SIZE`.
- Cache extract DB context once per job; Select candidate keeps BOQ core fields + analysis DB version.

**Production cleanup**
- Dead aliases/stubs/orphan match-results templates; CSS dedupe into `app.css`.
- Demoted noisy per-row INFO; job/export/import/error/AI metadata logs kept.

---

## 2026-07-28 – 2026-07-29 (summary)

**Analysis / Labour / Make & Vendor UI**
- Aligned section headers (Qty/Unit + product count), confidence borders, grouped lines.
- Labour: Product rate → Labour → Total → Qty → Final; mode badge; Product rate rename.
- Make & Vendor: same-price vendor ties; Product rate view-only; summary “Found rates for N”;
  status borders; filter/cascade polish; Next unlocks Labour.

**Pipeline**
- Section slots (1 product per Unit/Qty); empty sections Add + Re-analyse; qty 0 / Rate Only.
- Open detail tab from status; stuck-analysis heal/fail; progress reset; Celery concurrency 8.
- Top-3 candidates; BOQ source of truth on rematch; schema-only attributes; products only (no activities).
- Selectable candidates; concurrent analysis isolation; list search/sort across BOQ/DB/audit/notifications.

---

## 2026-07-20 – 2026-07-27 (summary)

- Labour page + Review path; export Excel formatting; Match rematch UI retired from main flow.
- Make & Vendor gate after Analysis Next; approved-make / lowest-price rules; cascade filters;
  no-make-list open lowest price; not-found/no-match editing; unlock persistence.
- Analysis progress spinner/%; adaptive lineage split; serial-lineage sections; taxonomy mapping.
- Single-sheet Excel validation; legacy `.xls` conversion; mobile layout; dashboard redesign.
- Notifications / audit / BOQ step alerts; confirm modal for edits.

---

## 2026-07-10 – 2026-07-17 (summary)

- Pipeline reset: fresh migrations, lean docs, removed orphan apps/`workflows/`.
- Master DB: active-only rows, last-10 upload history, no rollback, batched embeddings, Chroma.
- BOQ upload → hierarchical JSON + tabs; PDF make list; extract_json storage.
- Analyse + Match Celery/Redis; interactive Analysis; multi-product rows; AI instruction logging.
- DB product/attribute mapping on Analyse; rematch; category/make-list mapping; IST timestamps.
- Confidence bands; product autosave; Make & Vendor selection tab (category-wise make).

---

## Older

Pre-2026-07-10 history and ultra-fine UI tweaks: use `git log` / prior commits.
Product behaviour truth: `docs/PRODUCT.md`. Session memory: `docs/SESSION_STATE.md`.
