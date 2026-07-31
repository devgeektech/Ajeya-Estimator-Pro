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
5. Make & Vendor **Next** → unlock Labour → complete → Review → Export Excel

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

### 2026-07-31 — Text Master IDs + Empty Import Root Cause

Completed: Traced blank make-list Mapped Category / Sub-category to the import,
not the mapping service. Version `new_db`
(`New_Database_with_dummy_entries.xlsx`) uses `Product_ID` like `P1001`, which
failed the integer parser, so all 200 rate rows were skipped and the version
activated empty (also purging the prior version). `Product_ID` / `Rate_ID` are
now `varchar(64)` (`database_manager.0002`); Excel floats normalize (`1001.0` →
`1001`). Import now fails loudly when a required sheet yields no usable row.
Re-imported `New_Database.xlsx` as active version 8 `real_db` (1 rate row, 100
labour rows, embeddings regenerated). Verified: taxonomy loads `PIPE / MS`,
labour lookup resolves by string ID, and BOQ 90 maps 6 of 50 make-list
materials by heuristic alone.
Confirmed the dummy workbook now imports 200/200 rate + labour rows with
categories Electrical / Fire Fighting / Plumbing (verified in a rolled-back
transaction). A "Failed to fetch" on BOQ upload at 12:16 was the dev server
autoreloading mid-request during these edits, not an app fault; the upload form
now shows a connection message instead of the raw browser string.
Fixed BOQ detail pages not opening: `ensure_mappings` counted legitimately
`unmapped` materials as incomplete, so every open re-ran the AI mapping pass
(~30s, 3–4 OpenAI calls) and the browser aborted ("Broken pipe"). Only `pending`
stubs are retried now; open is ~5ms with no AI calls. Backfilled BOQs 83–87.
Dashboard Recent BOQs now uses seven equal row slots: seven rows fill the panel,
while smaller result sets occupy only their corresponding slots.
Fixed "stuck opening Analysis after Analyse completes": the detail view ran
`ensure_attribute_enrichment()` (full AI product mapping) inline on every open.
Extraction already does this in the Celery task, so the view-side backfill was
removed; page open measured ~0.2s for 65 rows / 39 products.
Fixed Analysis showing no confidence, no DB match and no attributes: the Celery
worker's cached Chroma segment went stale after the database re-import
(`InternalError: Error finding id`), and because `match_product` only caught
`AIServiceError` that single recall failure unwound the whole mapping pass —
`_enrich_extracted_attributes` swallowed it and saved 39 unmapped products.
Chroma now reopens and retries once, recall failures degrade to the SQL
fallback, and a failed mapping chunk no longer discards the other chunks.
BOQ 97 re-enriched to 22 matched / 12 provisional / 5 unmatched; BOQ 96 to 23 /
11 / 5. Restart the Celery worker for this to take effect on new runs.
Restored Analysis **Multi-product review** for any section with 2+ products
(5 sections on BOQ 97). Make & Vendor vendor dropdowns now follow Make changes
via `vendors_by_make`, with category-wide fallback when a sub-category only has
one vendor for that make.
Labour **Apply labour** is visible again in Auto mode (it had been Manual-only),
so Auto can load Labour_master_Output charges for every product.
Multi-product review flags only qty↔product count mismatches (not every
multi-product section).
Confirmed the Chroma fix end to end: the running Celery worker still held
pre-fix code (started 10:19), so BOQ 98's first Analyse mapped only 1 of 39
products. Verified in an isolated process that a concurrent full re-index makes
the stale handle fail and that the reconnect-and-retry recovers, then restarted
the worker. A Celery-dispatched extraction of BOQ 98 now yields 22 matched /
12 provisional / 5 unmatched with 32 confidence badges rendered.
Note: Celery does not auto-reload — restart the worker after changing task-side
code, otherwise fixes look like they did not apply.
Top database candidates now render expanded (they were stored all along, just
collapsed in a `<details>`), with tighter row spacing.
Candidate percentages and **Selected** now use plain text instead of rounded
badges, removing their padding and margin.
Candidate tech keys show `` . `` separators instead of pipes.
Removed the green ``Welcome back`` flash after login.
Labour summary shows
``Products Y · Labour Charges found for X products · Mode: Manual/Auto``
with bold counts and mode.
Analysis shows quantity/unit only in the section-header position beside product
count. In multi-product sections, clicking Product tabs updates that header to
the selected product's slot value; quantity/unit is not repeated inside cards.
Top database candidates are collapsed by default again.
Multi-product Analysis shows the active product's quantity/unit on a row under
the Product tabs (updates on tab switch), not only inside the card.
Initial extraction now enforces Unit/Qty slots as minimum product coverage:
every slot needs a product, but genuine extras are retained. Underfilled
sections get one focused AI correction pass; any still-missing slot becomes a
BOQ-evidence-only review product so no priced line is silently ignored.
Fixed the Make & Vendor cards being dead: the `vendors_by_make` JSON added for
per-make vendor lists was injected with `|safe` into the double-quoted `x-data`
attribute, so its quotes closed the attribute and Alpine never initialised the
card — **Find rates** showed as an empty yellow stub and `Product rate` was
blank. Escaping the JSON (no `|safe`) restores both; verified all 39 cards on
BOQ 100 parse with labels. Rule of thumb: never `|safe` JSON into an attribute.
Second cause of the same dead card: a **multi-line** `{# … #}` comment added next
to that fix. Django template comments are single-line only, so it rendered as
literal text inside the `x-data` object and Alpine died with
`Unexpected token '{'`. Because the component never initialised, `Product rate`
also stayed blank on matched (green) cards even though the rate was in the
payload. Both fixed; confirmed in headless Chrome with zero console errors.
Debug tip: `chrome --headless=new --dump-dom` over a saved copy of the page
surfaces Alpine expression errors that server-side HTML checks cannot.
`staticfiles.json` was serving a stale 15 KB `app.css` (source is 51 KB), which
is why `?v=` bumps kept appearing to do nothing; `collectstatic` re-pointed it
at `css/app.2edc5a8cc945.css`. Re-run `collectstatic` after editing `app.css`.
Pending: Upload a full Rate_Master_Output so more than `PIPE` exists.
Issues: Only 6 of 50 make-list materials map because the active DB has a single
category. `Size` values like `150 mm` still parse to NULL (decimal column) —
decide whether unit suffixes should be stripped. Pre-existing `boq` migration
drift on JSON field defaults (`0011`) is unresolved and unrelated. Only 9 of 39
matched products show an attribute panel because the dummy workbook leaves
`Attribute` (and Size / Unit / Class / Capacity) blank on most rate rows — the
schema is read from the matched row, so real data is needed to exercise it.
Next: Import full rate data; UAT make-list category columns end to end.

