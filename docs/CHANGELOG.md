# Changelog

Meaningful product and technical changes. Day-by-day micro-entries older than
the summaries below live in **git history** (`git log -- docs/`).

---

## 2026-08-25 — Sync DB upload (no Celery) + global lock UX

- Master-database import runs **synchronously** in the upload HTTP request
  (Celery task removed). Global file lock + status JSON still block concurrent
  uploads and keep **Uploading…** visible across Database/BOQ tab switches.
- Flow unchanged: validate → sheets → embeddings (required) → activate → purge
  previous master data. Failure leaves the previous active DB unchanged.

## 2026-08-25 — Global DB upload lock + Celery import UX

- One global master-database import at a time (file lock + status JSON).
- Upload button shows **Uploading…** and stays locked across Database/BOQ tab
  switches via `/database/import-status/` polling.
- Celery runs validate → sheets → embeddings (required) → activate → purge
  previous master data. Failure leaves the previous active DB unchanged.
- Django admin can no longer force-activate a version without embeddings.

## 2026-08-25 — Embedding-gated import + Admin peer isolation

- Database list/detail/download remain available to all signed-in users
  (intentional awareness/share feature); upload still access-gated.
- Master DB import activates only after embeddings complete successfully;
  failed/partial embeddings leave the previous active DB and Chroma intact.
- `SuperAdminRequiredMixin` is Superadmin-only (no longer an Admin alias).
  Admins manage only Experts they created; only Superadmin manages Admins.
- Audit: Admins see self + their Experts; Superadmin sees all (except
  Superadmin accounts).

## 2026-08-25 — BOQ visibility Superadmin / Admin underlings

- Superadmin lists and opens all BOQs.
- Admin lists/opens own BOQs plus Experts where `created_by` is that Admin —
  not other Admins or those Admins' Experts.
- Expert remains own-BOQs only. Tests and PRODUCT updated.

## 2026-08-25 — Manual deploy guide

- Added `docs/DEPLOY.md`: first EC2 go-live and subsequent manual `git pull`
  deploys (no CI/CD), including staticfile permissions and a copy/paste cheat
  sheet. Linked from README, OPS, AGENTS, and PRODUCT.

## 2026-08-24 — EC2 static CSS permissions

- After `collectstatic`, Nginx could not read `/srv/boq_ai/staticfiles` (403)
  because files were `boq_ai:boq_ai` mode 750/640. Fixed ownership to
  `boq_ai:www-data` and documented the chown/chmod in `docs/OPS.md` for go-live
  and subsequent deploys.

## 2026-08-25 — Labour manual missing-charge copy

- In Manual mode, products without labour show **No Manual Charge percentage is
  applied** instead of the Auto “no labour charge found” wording.

## 2026-08-25 — Labour Apply only in Manual

- Auto mode has no Apply button (switching to Auto already reloads
  Labour_master_Output). Manual mode keeps **Apply Labour**.

## 2026-08-25 — Labour Auto restores master rates

- Switching Manual → Auto reloads Labour_master_Output prices (no longer leaves
  manual % amounts on the cards).
- Apply button label follows mode: **Apply Auto Labour** / **Apply Manual Labour**.

## 2026-08-25 — Make & Vendor filter clear, same-price badge, selection preserve

- Filter × / Clear all restore lowest-price picks (same as initial Make & Vendor
  load) for the filtered scope.
- Duplicate **Same price** badge removed (one yellow badge only).
- Returning from Analysis only refreshes rates for products whose Product_ID
  changed; manual Apply / cascade work on other products is kept.

## 2026-08-25 — BOQ visibility by role

- Each uploader keeps their own BOQs. Superadmin and Expert see only their
  uploads. Admin sees their own BOQs plus every Expert's BOQs (not other Admins'
  or Superadmins'). List, detail, status, and dashboard use the same rule.

## 2026-08-24 — Go-live documentation

- README and `docs/OPS.md` now have a complete first-boot EC2 sequence, including
  master-database upload, `check_celery`, Postgres schema grants, and Nginx
  default-site removal. Subsequent `git pull` deploys are a separate section.

## 2026-08-24 — Production go-live settings

- Hardened `config.settings` for EC2 HTTP go-live: CSRF trusted origins, cookie
  flags, Postgres `CONN_MAX_AGE`, upload field limits, and refuse eager Celery
  when `DEBUG=False`.
- Added `backend/config/gunicorn.conf.py` (10-minute timeout for sync database
  import) and matching Nginx proxy timeouts in `docs/OPS.md`.
- Default AI instruction logging is off unless `DEBUG=True`.

## 2026-08-24 — Analysis Product Id column + Next gate

- Analysis product form shows a view-only **Product Id** column before Category
  for the loaded/selected catalog id.
- Analysis **Next** already blocked missing Product Ids; warning copy now tells
  experts to confirm or remove the product from Analysis first.

## 2026-08-24 — Analysis button labels

- Analysis **Re-analyse** is now **Re-analyse with AI**; **Confirm** is now **Confirm Manually**.

## 2026-08-24 — Job Only Add/Remove product

- **+ Add product** on a Job Only section now keeps the product visible and
  clears the Job Only mark (Unit=Job no longer hides added products).
- Removing the last product in a section marks it Job Only by default.

## 2026-08-24 — Keep chapter products before 1.1 on Analysis

- Oversized BOQ chapters still split at ``1.1`` / ``2.1``, but leftover chapter
  qty rows (BOQ_4 pipes ``c)``–``j)`` under ``1``) now appear as Section 1 in
  sheet order instead of after ``1.14``.

## 2026-08-24 — BOQ sheet extra-column headers stay horizontal

- Floor/other BOQ columns (Ground, basement, remarks) now keep one-line headers (`nowrap`, no hyphenation, no max-width squeeze).
- Description absorbs leftover table width so unused space on the right is used; the sheet still scrolls horizontally when columns overflow.

## 2026-08-24 — Remove dead Match/Confirm/HTMX code

- Deleted unused BOQ Match / row-match / match-results / calculate-price / session-confirm views and URLs (live matching stays inside Analyse).
- Removed Celery `boq.process_matching`, `BOQAnalysisEnrichmentService`, `BOQConfirmationService`, match-results JSON writers, and django-htmx (unused; UI is Alpine + fetch).
- Kept `MATCHING` / `PROCESSED` statuses for existing rows and `boq.process_analysis` as an extract-only Celery alias.

## 2026-08-24 — BOQ list auto-refresh after upload
- Added a JSON endpoint + client polling to refresh the BOQ list table body when returning to the BOQs page (browser back/forward cache + no manual refresh).
- BOQ list rows now include `data-boq-id`/`data-boq-status` so the client can detect changes and swap the table DOM.

## 2026-08-24 - Testing expansion, cleanup, and UI fixes
- Set the header row background color to yellow in the exported "Review" sheet for better visibility.
- Fixed long BOQ names overflowing behind the status badge on the dashboard.
- Added intelligent auto-refresh logic to the BOQ List and Dashboard pages so that when background analysis completes while on another tab, the UI automatically updates upon returning to the active tab.
- Deleted legacy test output files (`rendered_analysis.html` and `test_output.txt`).
- Verified all testing modules successfully migrated to root `tests/` directory.
- Added foundational view testing for all remaining apps (`dashboard`, `database_manager`, `notifications`, `accounts`).

## 2026-08-23 — Test cases moved and codebase cleaned
- Moved all test cases from `backend/` to a root `tests/` directory structure.
- Cleaned the entire codebase using `autoflake` to remove unused imports and dead code.
- Reviewed and removed definitively unused variables identified by `vulture` in `boq/services`.

## 2026-08-20 — Testing and Extraction Updates
- Re-analyse function now properly prioritizes BOQ description context over user inputs to calculate accurate confidence.
- Upgraded the AI Extraction prompt (`extract_products.txt`) to aggressively identify "Job Only" sections by looking for activity/labor verbs and completely avoid over-extracting products beyond the provided rate/quantity slots.
- Engineered a robust unit test suite (`apps/boq/tests/`) running entirely on Django TestCase with 100% pass rates to ensure production readiness.
- Validated real-world robustness by orchestrating an unmocked End-to-End (`test_pipeline.py`) runner against actual client BOQs, ensuring safe completions without system crashes.

## 2026-08-20 — Populate all database makes/vendors in dropdowns when Make List is not uploaded

- Updated `make_vendor_rates.py` with `_all_database_makes` and `_all_database_vendors` helpers.
- When no Make List file is uploaded for a BOQ (`self.has_make_list` is `False`), the Make & Vendor dropdowns automatically load all available Makes and Vendors present in `Rate_Master_Output` database for that database version.

## 2026-08-20 — Fix Make & Vendor, Labour, and Review tab line rendering after Analysis

- Fixed `make_vendor_display.py` line iteration so that rows with 0 products (e.g. Activity Only sections) build and append line objects instead of skipping them (`if not products and not is_act_only: continue`).
- Updated `has_products` and `has_analysis` across `make_vendor_display.py`, `boq_labour_service.py`, and `boq_review_display_service.py` to evaluate `bool(analysis.get("rows")) and (len(lines) > 0 or has_vendor)`, resolving the issue where tabs showed "No analysed products yet" after Analysis.
- Fixed `make_vendor_display.py` to set `show_manual_apply = True` for `same_price_tie` rows.
- Implemented `resolveSamePrice()` method in `_make_vendor_table.html` Alpine.js component, making the Apply / "Use selected vendor" button visible and functional for same-price tie resolution.

## 2026-08-20 — Activity Only ("job" unit) detection, product suppression, UI badge & orange highlight, light-blue export fill

- Added `is_job_unit` helper in `boq_row_fields.py` to identify rows where unit is `"job"` (or `"JOB"`, `"Job"`, `"jobs"`).
- Suppressed product display (`products = []`) for Activity Only sections so no products, product cards, candidate matching, or action buttons (`+ Add product`, `Re-analyse`) are shown under Activity Only lines across Analysis, Make & Vendor, Labour, and Review UI tabs.
- Displayed `Found Activity Only` badge (`badge--orange`) and orange card border & inset shadow (`extraction-line--activity-only`) on Activity Only section cards.
- Updated `BOQExportService` to keep rate and amount cells empty for `"job"` unit rows and apply a light blue background fill (`#D6EAF8`) to those rows in both `Review` and `BOQ` Excel output sheets.
- Added unit tests in `apps/boq/tests.py`.

## 2026-08-19 — Review export spacing + BOQ-native serials

- Review sheet inserts blank rows where the uploaded BOQ workbook has empty rows
  (matches section spacing on the BOQ tab).
- Review **Ser no of BOQ** now mirrors the original BOQ S.No (`1.1`, `a)`, `b)`,
  …) instead of parent-qualified forms like `1.1 a)`.

## 2026-08-19 — Review export: Net/Sub_Total formulas + BOQ Rate → Final Rate

- Review sheet Excel formulas now include **Net_Material_Rate** and **Sub_Total**
  (plus existing **Final_Material_Amount**, **Final Rate**, totals, and **Amount**).
  Procurement through Wastage and **Profit_Value** stay as Rate_Master values.
- BOQ tab **Rate** references Review column **Final Rate** (S), not Q+R inline.

## 2026-08-19 — Cascade Apply field label is Price

- Renamed the apply-filter preview field from **Lowest price** to **Price**.

## 2026-08-19 — Review export: Final Rate + fewer formulas

- Added **Final Rate** column before **Qty** in the Review sheet export.
- Excel formulas are now limited to **Final_Material_Amount**, **Final Rate**,
  **Total Material**, **Total Labour**, and **Amount** rollups.

## 2026-08-18 — Cascade Apply shows lowest price

- Make & Vendor apply-filter panel shows the lowest Rate_Master price for the
  selected category / sub-category / make / vendor.
- Applied filter chips also include that amount.

## 2026-08-18 — Make & Vendor Clear all filters restores lowest price

- Applied filters has **Clear all**. Removing one filter or all filters reloads
  the lowest-price make/vendor/rate for those sub-category products.

## 2026-08-14 — AI Description includes taxonomy + attributes

- AI Description is composed as
  ``Category / Sub-category / Class / Size / Unit / Capacity — attr labels``
  (known fields only; up to four attributes such as IS Standard / Type / Material).
- Extract prompt and post-extract enrichment both use this format; saving fields
  refreshes it unless the expert edited AI Description itself.

## 2026-08-14 — AI Description label + normal text size

- Renamed Analysis field label **AI understanding** → **AI Description**.
- Description field uses the same font/size as Category and other inputs
  (no monospace).

## 2026-08-14 — Make & Vendor product dropdowns show all options

- Product Make dropdown always lists every Rate_Master make for the Product_ID
  (no longer shrinks to the prefilled lowest make/vendor pair).
- Vendor lists all vendors for the selected make, or all vendors when Make is
  empty / Lowest price.

## 2026-08-14 — Remove Find in DB; Apply-only for not found / no match

- Removed Find in DB button and backend action.
- Not found / No match keep the warning; make/vendor dropdowns stay available
  (options from Product_ID rates on page load). Selecting a pair only previews
  the rate (``preview_only`` — no analysis write) — card stays red until
  **Apply**, which turns it green.
- Apply reload keeps scroll on the same card via ``#make-vendor-{rowId}``.

## 2026-08-14 — Find in DB uses Product_ID + keep scroll position

- Find in DB prefers the product's existing ``Product_ID``, then loads
  Rate_Master make/vendor/rate rows for that id (no make-list filter).
- Falls back to Product_Helper only when Product_ID is missing; description
  hint can resolve cat/sub (e.g. fire door → FIRE DOOR).
- Reload after Find in DB / Apply anchors to ``#make-vendor-{rowId}`` so the
  page does not jump to the top.

## 2026-08-14 — Make & Vendor prefill + button row + scroll

- Align make-list spellings (``NEWAGE``) to Rate_Master dropdown labels
  (``NEW AGE``) so Make/Vendor stay selected when the product rate is filled.
- Store Rate_Master Make/Vendor on matched rates for UI consistency.
- Action buttons sit on a full-width nowrap row (no grid squeeze / jump).
- Scroll restore stops when settled and does not fight user scroll on reload.

## 2026-08-14 — Multiproduct review = slot count mismatch only (strict)

- Multi-product review badge only when product count ≠ Unit/Qty slot count.
- Slot-fallback / needs-extraction-review no longer reuse that badge (was
  wrongly flagging 1-slot / 1-product sections such as 4.2).

## 2026-08-14 — AI understanding description on Analysis

- Extract writes a short one-line ``description_hint`` (AI understanding of the
  product from section + slot), not a raw Unit/Qty row paste.
- Enrichment keeps that AI line unless empty/size-only/slot-paste; slot fallback
  synthesizes noun+size instead of dumping the qty row.
- Label/placeholder: **AI understanding** — expert can rewrite in plain language
  then Re-analyse; rematch uses understanding first + section for nearest products.
- Map prompt treats free-form corrections as matching intent.

## 2026-08-14 — Re-analyse 100% fix + empty section recall + sand buckets

- Re-analyse no longer forces match % to 100% at ≥85 structured; that ceiling
  stays on initial Analyse after Rate-align only. Rematch shows the real blend.
- Empty-input Re-analyse folds the full BOQ section into Chroma/SQL recall so
  nearest products surface when Analysis fields were blanked.
- Sand bucket synonyms + category hint from description; Product_ID 40 recalled.
- Regenerated Product_Helper Chroma embeddings (collection was empty — vector
  search had been falling back to keyword SQL only).

## 2026-08-14 — Make & Vendor Apply UX + make/vendor cascade

- Apply uses its own busy label (other buttons no longer show Searching).
- Action buttons stay on one non-wrapping row.
- Make dropdown lists only vendors’ makes when a vendor is selected (clear
  vendor to see all makes); Vendor lists only that make’s vendors (clear make
  to see all vendors).
- Selecting make/vendor auto-loads product rate; Find rates kept for typed entry.

## 2026-08-14 — Make & Vendor Apply on not found / no match

- Not found / No match cards show **Apply**; saves expert make/vendor as matched
  (green) even when no Rate_Master row exists (still tries rates first).

## 2026-08-14 — Initial Analyse: Size=0 catalog → high match

- Rate_Master Size ``0``/``0.0`` treated as blank (same as Capacity) so cabinet
  dims no longer penalize FIRE HOSE BOX / similar rows to ~40%.
- Initial Analyse Rate-aligns + prefer-fills when match ≥30 (not only ≥50) so
  correct DB products promote toward 100% without Re-analyse.

## 2026-08-14 — Multiproduct review = slot count mismatch only

- Multi-product review applies only when product count ≠ Unit/Qty slot count
  (e.g. 2 rate/qty slots with 1 or 3 products). Sections with equal counts are
  not flagged; ≥2 products alone is not enough.

## 2026-08-14 — Analysis extract stability + Select / Re-analyse

- Extract stabilizes to one product per Unit/Qty slot (pad missing, trim extras)
  so Analyse product counts stay consistent; prompt forbids per-slot extras.
- Multi-product review flag shows when product count ≠ Unit/Qty slot count (or
  hollow fallbacks), not merely when a section has ≥2 products.
- Weak “Unable to match” banner only when effective match % is below 50; badge
  uses top candidate % when the product row was left at 0%.
- Selecting a Top database candidate no longer re-scores sibling candidate %.
- Re-analyse prefers edited ``description_hint`` for Chroma/SQL recall and
  resolves the active product tab more reliably.

## 2026-08-14 — Product_ID sync for Labour + return from Analysis

- Capture prefers Analysis-selected Rate_Master ``Product_ID`` over a stale
  Make & Vendor catalog id.
- Labour unlock / Apply Auto re-captures Product_IDs then loads
  ``Labour_master_Output`` by that id.
- Make & Vendor / Labour tab or Next after Analysis edits re-syncs Product_IDs;
  rates reload only when the Product_ID changed (unchanged make/vendor kept).

## 2026-08-14 — Analysis Next: Product_ID capture then rate load

- Analysis → Next first captures each updated product’s catalog ``Product_ID``
  from the Analysis-selected Rate_Master row, then loads Make/Vendor rate rows
  filtered by that ``Product_ID``.
- Lowest default always picks by ``Final_Material_Amount`` (never
  ``Net_Material_Rate``); approved-make filter keeps Product_ID rows when labels
  do not optimally match. Dropdown keeps the auto-selected Make/Vendor visible.

## 2026-08-14 — Make & Vendor auto-make + Final_Material_Amount prices

- Analysis → Next fills Make even when Category was blanked but Product_ID is
  known; approved-make filter no longer wipes all Rate_Master rows for a
  Product_ID when labels do not optimally match.
- Product rate display uses ``Final_Material_Amount`` only (no Net_Material_Rate
  fallback). Dropdown keeps the auto-selected Make/Vendor visible.

## 2026-08-14 — Fix bogus m) serial + no AI on Analysis GET

- Stop treating ``M.S.`` / ``C.I.`` / ``D.I.`` description leads as letter
  serials (``m)`` / ``c)`` / ``d)``) on BOQ upload/display.
- Analysis tab GET no longer runs make-list OpenAI remap or embedding recall;
  unmatched candidates use SQL-only recall. Stops Analysis UI drift (including
  multi-product review) when switching tabs.

## 2026-08-14 — Candidates on unmatched 0% products

- Unmatched Analysis products with empty stored candidates now live-recall Top
  database neighbors from description (Select available without Re-analyse).
- SQL recall adds a description-only pass so cabinet sizes like 30"x24"x10" do
  not hide FIRE HOSE BOX rows with blank Size.

## 2026-08-14 — Slot order, score ceiling, Confirm match

- Analysis products stay in BOQ/slot sequence (not sorted by match %).
- Confidence reaches 100% when core fields align (no more stuck ~90–92% after
  catalogue fill); hose box synonyms include FIRE HOSE BOX; hose reel vs hose
  box treated as a type conflict; hint boost for named Sub_Category.
- Analysis **Confirm** button (non-100% with a selected/suggested product) locks
  match confidence at 100%.

## 2026-08-14 — Top candidates visible on unable-to-match

- Unmatched / low-confidence Analysis products open **Top database candidates**
  by default and always show Select; messaging covers unmatched and provisional.

## 2026-08-14 — Re-analyse expert inputs + section-as-context matching

- Re-analyse recall uses filled product fields + qty/unit slot line; full section
  is AI context only (stops system titles like Yard Hydrant from pulling Hydrant
  catalog rows for pipe slots).
- Extract/match prompts and section payloads send complete lineage; products stay
  slot-bound. Expert-filled attributes kept after rematch; candidates refresh.

## 2026-08-14 — Monotonic Analyse progress + stabler product matching

- Progress % is monotonic in the job file, vanilla poller, and Alpine ticker
  (no soft-creep-ahead); matching progress no longer reports done &gt; total.
- Slimmed `extract_products.txt` / `map_product_match.txt` for gpt-4o-mini;
  qty+unit slots are the only main products; AI uses seed 42; candidates sorted
  by confidence then id for more repeatable Product_ID picks.

## 2026-08-14 — Analysis progress UI no longer stuck at 1%

- Added a vanilla `BOQAnalysisProgress` status poller on the BOQ detail page so
  Analysis %/label update and the page reloads when ready even if Alpine’s
  inline poll chain never starts (previously: spinner stayed at 1% while Celery
  and the runserver echo thread advanced).
- Progress title now shows the live server label; initial % uses server progress.

## 2026-08-14 — BOQ upload auto-redirect to list

- AJAX upload success always navigates to the BOQs list (`location.replace`,
  `redirect: 'manual'`, absolute `redirect` in JSON) so the browser does not
  stay on `/boqs/upload/` after a followed 302/HTML response.
- Upload status copy notes PDF make-list parsing can take up to a minute.

## 2026-08-14 — Fix IDE basedpyright on Django models/services

- Annotated `BOQ` and master DB models with instance value types + `objects` /
  `DoesNotExist` so basedpyright no longer treats fields as Field classes.
- Added `common.db.atomic` / `q` helpers; wired services to them; pinned
  `basedpyright`; added `.vscode/settings.json` for the project `.venv`.

## 2026-08-13 — Clear basedpyright diagnostics on BOQ services

- Added `django-stubs` / `django-stubs-ext` and early `monkeypatch()` so models
  type as instances (`objects`, JSONField values as dicts).
- Restored missing imports after Phase 4/5 splits; annotated Make Vendor /
  Product AI mixins; fixed remaining `int`/`float` on `.get()` that could be
  `None`. `pyright` on `backend/apps/boq/services` is clean (0 errors).

## 2026-08-13 — Fix Product AI candidates mixin imports

- Restored missing `display_material_label` / `structured_match_score` imports in
  `product_ai_candidates.py` after the Phase 4 split, and typed mixin attrs for
  the facade (`database_version_id`, `_matcher`).

## 2026-08-13 — Split BOQ extraction service (Phase 5)

- Split `boq_extraction_service.py` into facade + modules:
  `boq_extraction_fields`, `boq_extraction_slots`, `boq_extraction_groups`.
  Public helpers include `normalize_product_fields` (replaces private-only use),
  `quantity_display_fields`, and quantity rehydrate helpers. `extract` /
  `extract_anchor` API unchanged. Behaviour-neutral structure only.

## 2026-08-13 — Split Product AI mapping service (Phase 4)

- Split `product_ai_mapping_service.py` (~1.8k lines) into facade + modules:
  `product_ai_common`, `product_ai_candidates`, `product_ai_apply`. Public API
  (`map_rows`, `rematch_product`, `apply_selected_candidate`, …) unchanged.
  Behaviour-neutral structure only.

## 2026-08-13 — Split Make & Vendor service (Phase 3)

- Split `make_vendor_selection_service.py` (~2.2k lines) into facade + mixins:
  `make_vendor_common`, `make_vendor_rates`, `make_vendor_cascade`,
  `make_vendor_display`. Views still import `MakeVendorSelectionService`; public
  method names unchanged. Behaviour-neutral structure only.

## 2026-08-13 — Remove unused BOQ service symbols (Phase 2)

- Deleted unused `BOQAnalysisDisplayService` (Analysis tab already uses
  `BOQExtractionDisplayService`).
- Removed dead helpers: `has_priced_quantity`, `is_pdf_title_line`, labour
  `tech_key` aliases, unread extract/analysis JSON readers, and unused
  `map_product` wrapper. Live Analyse / Make & Vendor / Labour paths unchanged.

## 2026-08-13 — Shared BOQ row field helpers (Phase 1)

- Added `boq_row_fields.py` for description/qty/unit keys, `field_from_map`,
  `is_filled` / `is_blank`, whitespace `normalize_text`, and `ordered_boq_rows`.
- Display, matching, labour, export, and grouping now import those helpers
  instead of copying them. Make-list brand matching still uses its own
  alphanumeric normalizer; grouping still extends qty keys with floor/total
  columns. No pipeline behaviour change.

## 2026-08-13 — Make & Vendor cascade: sub-category makes only

- Selecting a sub-category now lists only that sub's Approved makes (Rate_Master
  scope; with make list = approved ∩ sub Rate_Master makes).
- Stopped falling back to every make in the parent category when the sub had no
  exact Rate_Master rows / category-wide make-list mappings.

## 2026-08-13 — Loosen Analysis matching (fix 29% floor)

- ``product_type_conflicts`` now checks Category + Sub_Category + Class (not Sub
  alone), so ``80mm pipe`` vs Sub ``MS`` is no longer treated as a conflict.
- Replaced the hard 29% confidence cap with a soft type-mismatch penalty.
- Blank category/sub get partial credit from ``description_hint``; size can be
  read from the hint when the size field is empty.
- Slot noun enrichment prefers pipe/valve over incidental ``Yard Hydrant System``
  wording; extract prompt clarifies pipe size rows are PIPE, not Hydrant.

## 2026-08-13 — Analyse progress via console logging (no print)

- Analyse progress uses ``logger.info`` only (console + ``application.log``).
- Removed ``print`` / stdout writes for Analyse progress.
- Django runserver mirrors Celery progress with the same ``boq_ai`` logger so
  the server terminal shows live ``BOQ Analyse id=… percent=…`` lines.

## 2026-08-13 — Analyse progress prints live on terminals

- Celery and Django runserver log ``BOQ Analyse …`` as work advances.
- Django starts a progress-echo thread when Analyse is queued so runserver
  shows percent/label every few seconds.
- Fixed ``run_celery_worker.ps1`` parse error (PowerShell ``@`` / format string)
  that prevented the unique-nodename worker from starting.

## 2026-08-13 — Celery unique nodename (no DuplicateNodenameWarning)

- Worker hostname is now ``boq-<pid>@<computer>`` so multiple leftovers cannot
  collide as ``boq@ThedEaD``.
- ``run_celery_worker.ps1`` / ``.sh`` stop leftover Celery processes on start.
- Run **one** Celery terminal only.

## 2026-08-13 — Celery reliability for Analyse

- Analyse **refuses to queue** when the Celery worker is down (no more frozen
  loading with nobody consuming Redis).
- Worker writes ``media/job_progress/celery_worker_heartbeat.json``; dispatch
  checks it (Windows ``threads`` pool cannot rely on control inspect).
- ``scripts/run_celery_worker.ps1`` / ``.sh`` auto-restart if the worker exits.
- Clear alert tells the expert to start the worker and retry Analyse.

## 2026-08-13 — Analyse stuck after Celery restart + row logs

- Celery tasks now ack late and re-queue if the worker dies mid-job
  (``CELERY_TASK_ACKS_LATE`` / ``REJECT_ON_WORKER_LOST``).
- Stuck PROCESSING heals after **2 minutes** of frozen progress so Analyse
  unlocks from BOQ / Make List / Analysis.
- Extraction and matching log each section/product batch in the Celery worker
  terminal (``BOQ extract row done…``, ``BOQ match product…``).
- Retry Analyse button shown after ``ANALYSIS_FAILED``.

## 2026-08-13 — Analysis Product_ID display + match blanking + auto-reload

- Candidate / match summaries show **Product ID** (not Rate_ID) then Category /
  Sub / Class / Size / Unit / Capacity.
- Top database candidates stay **collapsed** by default.
- Weak-match input blanking runs **after** the refine rematch pass so first-pass
  identity fields are not cleared before scoring (fixes 0% candidate lists).
- Analyse completion navigates with ``location.replace`` and a 2s fallback so
  the loading panel does not stick until a manual refresh.

## 2026-08-13 — AI-first multi-target make-list category mapping

- Mapping is AI-first (v11): understands free-text meaning; returns
  ``mapped_targets`` so compound lines can map multiple categories/subs
  (e.g. sprinklers + rosette plates).
- Null subcategory = approved makes apply category-wide.
- Constraint index + Make List Category/Subcategory columns support multi-target.
- Heuristic phrase lists are soft hints only (not the primary mapper).

## 2026-08-13 — Make-list All Types + catch-all equipment mapping

- ``Sprinklers & Rosette Plates (All Types)`` → SPRINKLER with blank sub
  (never ACCESSORIES/Rosette).
- ``Fire Fighting Equipment not covered elsewhere`` → HYDRANT with blank sub.
- ``All Types`` / catch-all lines do not invent Pendant/Upright/etc. Mapping v10.

## 2026-08-13 — Analysis loading polls live to 100% then auto-reloads

- Status polls are cache-busted (`Cache-Control: no-store` + timestamp query).
- Analyse on the Analysis tab keeps the live poll chain (no mid-run page kill).
- Watchdog restarts stuck/hung polls; progress soft-creep is faster.
- Celery worker logs each progress tick (`BOQ job progress id=… percent=…`).

## 2026-08-13 — Make-list re-parse restores row 1 + synonym category map

- Stale make-list JSON re-parses from the uploaded PDF/Excel when
  ``parse_version`` is behind (fixes missing serial 1 that split-repair could
  not restore).
- Category/subcategory heuristics expand synonyms (``M.S``↔mild steel,
  ``D.I.``↔ductile iron, NRV/hose reel, …) before matching; AI mapping v9
  still uses ``{{SYNONYM_MAP}}`` for remaining gaps.
- Confirmed Approved Makes are **not** capped at 4 — ``approved_makes_list``
  holds all brands; ``approved_makes_N`` columns grow to the longest row.

## 2026-08-13 — Make-list PDF keeps material nouns in Description

- Fixed Title-Case peel that moved ``Drum`` / ``Drums`` / ``Reel`` into Approved
  Makes (rows 14–16 on `List_of_Approved_Makes`).
- Numbered ALL-CAPS product lines are no longer dropped as document banners
  (restores row 1 / cables / isolators).
- ``H.GURU``-style brands stay intact; leading material stopwords are repaired
  on load via ``split_repair_version`` (no re-upload required).
- Make-list category mapping bumped to **v7**.

## 2026-08-13 — Product_Helper Chroma + labour from state multiplier

- AI validates up to **5** Product_Helper neighbors (UI still shows top **3**).
- Chroma indexes **Product_Helper only** (full row text; discontinued Status
  skipped). Search returns Product_ID; Rate_Master Make/Vendor/`Final_Material_Amount`
  and Labour load from Postgres by that id.
- Auto labour prefers **`Labour_With_State_Multiplier`** (fallback
  `Total_Labour_Per_Unit`, then `Labour_Rate_Per_unit`).
- Re-activate/re-import the master DB to rebuild Chroma; restart Celery.

## 2026-08-13 — Initial Analyse fetches DB products more reliably

- AI validates up to **8** nearest Rate_Master neighbors (UI still shows top 3).
- Initial recall includes BOQ section text (same as Re-analyse).
- SQL Category filters use synonym expansion; Chroma product text excludes
  Make/Vendor (re-generate embeddings on next DB activate).
- After the first map pass, products under 50% get one automatic refine rematch.

## 2026-08-12 — Shared synonym map injected into AI prompts

- Single synonym map from ``utils/product_synonyms.py`` is rendered for AI and
  injected into ``extract_products``, ``map_product_match``, and
  ``map_make_list_categories`` via ``{{SYNONYM_MAP}}`` (no hardcoded duplicate lists).
- Added Reflex Valve / reflex as NRV / non-return synonyms; make-list mapping v6.

## 2026-08-12 — Analysis loading no longer stuck until refresh

- Status polling resumes after tab switches / bfcache / tab focus; a watchdog
  restarts a dead poll chain. Completion reloads Analysis with scroll preserved.
- Job heal no longer false-fails a live run: progress is reset before status
  flips to PROCESSING, and terminal 100% needs a 45s grace before orphan heal.

## 2026-08-12 — Tab before candidate Attribute text

- Top database candidate summaries separate identity fields from Attribute
  ``key=value`` pairs with a tab (HTML preserves it via ``white-space: pre-wrap``).

## 2026-08-12 — Weak-match warning + selectable candidates

- Below 50% confidence, Analysis shows a warning that no confident match was
  found and points experts to the top database candidates or manual entry +
  Re-analyse. The candidates list opens by default; each of the three rows is
  selectable.

## 2026-08-12 — Empty Analysis inputs below 50% confidence

- When match confidence is under 50%, Analysis leaves Category / Sub-category /
  Class / Size / Unit / Capacity and Attribute values empty. Product description,
  qty, suggestion banner, and top candidates stay visible. Expert Select and
  rematch with typed values still fill as before. Confirm threshold remains 30%.

## 2026-08-12 — Skip Discontinued Product_Helper on DB upload

- Product_Helper rows with Status ``Discontinued`` (column I) are not imported.
- Rate_Master_Output / Labour rows for those Product_IDs are skipped so they are
  never embedded in Chroma and cannot appear during Analysis matching.
- Embedding generation also skips any leftover discontinued Product_IDs on older
  active databases.

## 2026-08-12 — BOQ detail JS no longer dumps as page text

- Alpine ``x-data`` on the BOQ detail page used a CSS selector with double
  quotes (``[id^="line-"]``), which closed the HTML attribute early and showed
  raw JavaScript under the BOQ title. Selector is now quote-free.

## 2026-08-11 — Electrical panel must not match rosette at 100%

- Section 4.6 extracted two identical panel products and confirmed
  ACCESSORIES / ROSETTEE PLATE at 100%. Rate_Master has no control-panel
  row; scoring after copying catalog fields minted a false 100%.
- Match % now uses extract/expert fields plus a description-vs-sub-category
  gate so unrelated types stay provisional. Duplicate products on the same
  slot are collapsed. Make-list no longer maps bare ``panel`` to ACCESSORIES.

## 2026-08-11 — Analysis scroll survives tab switch

- Tab switch saves the visible Analysis section (not only ``window.scrollY``)
  and restores it after layout. Leaving via BOQ / Make List no longer opens
  Analysis at the top.

## 2026-08-11 — Show 0 / null / NA / NB on candidates

- Candidate identity slots always include ``0``, ``null``, ``NA``, and ``NB``
  instead of dropping them. Analysis fields keep those tokens as stored.

## 2026-08-11 — Candidate label: Rate ID / Product ID / …

- Top database candidates show one line: Rate ID / Product ID / Category /
  Sub-category / Class / Size / Unit / Capacity, then attributes after a space.
  The duplicate slash + dotted tech-key line is removed.

## 2026-08-11 — Re-analyse keeps scroll position

- Product Re-analyse swaps only that product panel and restores the section’s
  viewport offset so the page does not jump on the first click.

## 2026-08-11 — Valve Class 0 from Rate_Master

- Extract DB context now sends deduped ``classes`` plus
  ``classes_by_category_sub_category`` (includes Class ``0``).
- Class ``0`` is no longer wiped as a placeholder or replaced with material
  (DI). Sluice / butterfly Class snaps to the catalog value; material stays on
  Attribute.

## 2026-08-11 — Hide duplicate Analysing badge

- While Analyse is running, the pale status badge no longer repeats
  “Analysing…”. The action button is the only label.

## 2026-08-11 — Review Discount/Base edits recalc Amount

- Review Net → Final material → TOTAL MATERIAL/LABOUR → Amount are Excel
  formulas. Changing Discount, Base, Labour, or Qty updates Review Amount and
  the linked BOQ Rate/Amount cells.

## 2026-08-11 — Linked Review + BOQ export workbook

- Export is one ``{upload}_result.xlsx`` with **Review** and original **BOQ** tabs.
- Result **Amount** formulas point at Review Amount; Result **Rate** is
  Final_Material_Amount + Labour (summed when several products share a slot).
- Rate/Amount columns detected across client header formats; qty/rate/amount
  written only on Unit/Qty rows.
- Muted green (amount found), orange (zero / Rate Only), red (missing).
- Section header rows no longer show the first child's quantity.

## 2026-08-11 — Rematch keeps expert inputs; isolate product %

- Class ``0`` is a real expert/Rate_Master value — no longer wiped or replaced
  with material on save, rematch, or Analysis render.
- Product Re-analyse keeps the filled inputs used for search; fetched DB details
  remain on the match banner and candidate list.
- Rematch updates only that product. Sibling products and their match % are
  unchanged (no section-wide normalize or display re-score).

## 2026-08-10 — Honest candidate % + Multi-product flag

- Structured match uses fixed core-field weights so size+unit alone cannot score
  100% (e.g. pressure gauge vs MS pipe now ~34% vs ~100%).
- Analysis display refreshes candidate % from current product fields; mapping
  re-scores after Rate_Master fill.
- **Multi-product review** only when product count ≠ Unit/Qty slots, or a hollow
  slot-fallback still has no category — matched 3-for-3 dia sections are not
  flagged.

## 2026-08-10 — Backend synonym / matching cleanup

- Make-list description/sub-category hints live only in `utils/product_synonyms.py`
  (no duplicated local lists).
- Removed unused synonym hint wrappers, write-only `catalog_candidates`, and
  leftover Top-5 candidate slice; shared `CANDIDATE_LIMIT=3`.
- No UI/template/CSS changes.

## 2026-08-10 — Top-3 candidates + broader synonyms

- Top database candidates limited to **3** again.
- Shared synonym groups (materials + product phrases like NRV/check valve,
  sluice/gate) used for Analysis matching/recall and Make List category mapping.
- Make-list mapping version **v4** remaps stored lists so correct category/sub
  drive Make & Vendor makes.

## 2026-08-10 — Top-5 candidates + rematch prefills DB product

- Top database candidates are consistently up to **5**, with match % re-scored
  from filled Analysis fields.
- Re-analyse prefills the selected Rate_Master row into UI inputs (core fields +
  attributes) and scores confidence from those filled fields.
- Broader SQL recall (category+size and Class/Sub/Attribute synonym search) so
  products present in the DB are less likely to be missed (DI ↔ ductile iron).

## 2026-08-10 — Synonym-aware Analysis matching

- Material/class synonyms treated as identical for scoring and recall
  (DI↔ductile iron, CI↔cast iron, MS↔mild steel, GI, SS).
- Chroma query + SQL fallback expand synonyms so nearest Rate_Master rows are
  found; structured score weighted higher than sparse attributes.
- Top database candidates increased to 5; rematch prompt must not lower
  confidence for synonym wording alone.

## 2026-08-07 — Analysis Capacity last + Unit in candidates

- Analysis product inputs order: Category → Sub-category → Class → Size → Unit →
  Capacity.
- Top database candidates include Unit after Size; dotted separators use a darker
  style. Display key is ``Category|Sub|Class|Size|Unit|Capacity|Attribute``.

## 2026-08-07 — Re-analyse fresh DB search with filled inputs

- Product **Re-analyse** re-queries Chroma/SQL using filled Analysis fields and
  the BOQ section/slot text instead of locking the previous top-3 candidates.
- AI rematch picks the best new match, re-scores confidence, and prefills
  Analysis inputs from that Rate_Master row.

## 2026-08-07 — Prefill selected DB candidate into Analysis inputs

- Selecting a top database candidate loads that Rate_Master row into Analysis
  inputs (category/class/size/unit/capacity + Attribute values) and keeps the
  candidate’s listed match %.
- The Selected candidate is clickable to reload the same product into the form.
- Confirmed AI matches fill blank Attribute schema keys from Rate_Master while
  keeping filled BOQ values.

## 2026-08-07 — Analysis progress tracks real extract work

- Analysis loading starts at **1%** (not an immediate **8%** jump).
- Extract progress maps **3% → 55%** as AI batches finish; matching remains
  **55% → 95%**. UI soft-creep follows the last server target instead of a
  fixed mid-band floor.

## 2026-08-07 — Fix corrupt BOQ result Excel export

- BOQ result export no longer leaves broken ``#REF!`` defined names / external
  links from the uploaded workbook (Excel “We found a problem with some
  content…”). Loads with ``keep_links=False``, clears defined names, writes
  Rate/Amount as numbers.

## 2026-08-07 — Product-wise Re-analyse + stable candidate confidence

- **Re-analyse** rematches one product: BOQ row description + UI fields/attrs +
  prior Product_IDs via ``rematch_product`` (not section-wide).
- Confirmed match / candidate select loads Rate_Master category/class/size/unit/
  capacity into Analysis columns.
- Selecting a top DB candidate keeps that candidate’s listed match % instead of
  recomputing a new blended score.

## 2026-08-07 — Match % color band rounding

- Analysis match colour uses the rounded display percentage so a shown **95%**
  is green (≥95), **90–94** orange, **<90** red (fixes 94.5–94.9 showing as
  orange while the label read 95%).

## 2026-08-07 — Section-wide Re-analyse rematch

- Analysis **Re-analyse** rematches every product in the section after saving all
  product forms (filled blanks + prior Product_ID seeds). No longer product-wise.
- Empty-section Re-analyse still re-extracts from the workbook.

## 2026-08-07 — Optimal product Re-analyse (rematch)

- Product **Re-analyse** rematches using saved product fields, expert-filled blank
  attributes, and seeded prior Product_IDs / candidates (not a fresh BOQ extract).
- Empty-section Re-analyse still re-extracts from the workbook.
- Wider Chroma recall on rematch; ``map_product_match`` payload includes
  ``rematch`` / ``prior_match`` / ``expert_filled_attributes``.

## 2026-08-06 — Make-list category/sub-category mapping fix

- Hardened make-list Category / Subcategory assignment: specific phrase hints,
  no weak shared-token subs (Alarm Valve ≠ Ball Valve), keep solid heuristic
  category when AI disagrees weakly, hyphen-safe phrase match, sprinkler-only
  flexible-pipe hint.
- ``category_mapping_version`` remaps stored make lists when rules change.
- Prompt ``map_make_list_categories.txt`` prefers null sub over wrong guesses.

## 2026-08-06 — Labour charges by Product_ID (Postgres)

- Auto labour resolves Product_ID from Analysis ``catalog_product_id`` /
  suggested id as well as ``vendor_selection`` / rate_detail.
- Make & Vendor **Next** unlocks Labour and auto-loads Labour_master_Output by
  that Product_ID.
- Docs: Chroma/vector search is only for finding Product_ID; Make/Vendor amounts
  and labour always come from PostgreSQL.

## 2026-08-06 — Product_ID Make/Vendor dropdown cascade

- Analysis **Next** and **Find in DB** load Make/Vendor from Rate_Master_Output by
  Analysis ``Product_ID``; selecting one dropdown filters the other to matching
  pairs. Find in DB button is yellow (``btn--boq-analyse``).

## 2026-08-06 — Not-found Make/Vendor dropdown format

- Not-found Make & Vendor cards use the same Make/Vendor ``<select>`` dropdowns as
  matched products when Rate_Master options exist (free-text only if the list is empty).

## 2026-08-06 — Optimized extract + match recall

- Tightened ``extract_products.txt`` and ``map_product_match.txt`` (same rigor,
  less repetition; one multi-slot example; hard size rule on map).
- Extract payloads drop duplicate ``qty_rows``; weak size-only hints are enriched
  with product type for better Chroma recall.
- Matching: higher size/capacity weight, size-mismatch penalty + filter, PN soft
  match, ignore Class ``0``, keep material on attributes, Product_ID dedupe, SQL
  same-size boost into the candidate pool; provisional taxonomy fills blanks only.

## 2026-08-06 — Section extract + shared Re-analyse

- Multi-slot extraction binds each product's size/unit from its letter slot,
  prefers BOQ PN rating for capacity, clears placeholder class ``0``, and copies
  shared parent attributes (IS / seat / connection) onto every product.
- Analysis **Re-analyse** re-extracts the whole section with the same
  ``extract_products.txt`` instructions as initial Analyse (then remaps), instead
  of product-wise Rate_Master rematch.

## 2026-08-06 — Export Qty + orange zero/rate-only rows

- BOQ result export writes resolved numeric Qty on qty+unit rows (replacing
  floor ``SUM`` formulas that looked blank until Excel calculated).
- Zero-qty and Rate Only rows are highlighted orange on both BOQ and Review
  exports; unmatched product rows stay red.

## 2026-08-06 — Export rates + Review section rows

- BOQ result export fills Rate/Amount for headers like ``RATE (Rs.)`` /
  ``AMOUNT (Rs.)`` (not only bare ``rate`` / ``amount`` keys).
- Review/breakdown export includes other BOQ section text rows (Material,
  Fittings, Painting, notes) in addition to product lines.

## 2026-08-06 — Review export name includes review

- Review sheet download is now ``{upload}_review result sheet.xlsx`` (BOQ export
  remains ``{upload}_result.xlsx``).

## 2026-08-06 — Notifications auto-read on open

- Opening the Notifications page marks all as read (nav unread badge clears).
- Removed Mark all read and the header select-all control; per-row select and
  Clear selected / Clear all remain.

## 2026-08-06 — Remove Cancel on database upload

- Removed the Cancel button from the Upload Database page.

## 2026-08-06 — Export filenames from uploaded BOQ

- Export downloads are named from the uploaded workbook:
  ``{upload}_result.xlsx`` (BOQ) and ``{upload}_review result sheet.xlsx`` (Review).

## 2026-08-06 — Review BOQ Description without qty/unit

- Review BOQ Description shows only the row text (e.g. ``a) 150 mm dia``);
  quantity and unit are not appended (they stay in Qty / Unit fields).

## 2026-08-06 — Find in DB keeps scroll position

- Make & Vendor **Find in DB** (and Find rates / same-price / filter reloads)
  restore the previous scroll position after refresh instead of jumping to top.

## 2026-08-06 — Analysis mapping + Make & Vendor Next

- Initial Analyse was dropping mapped candidates for whole chunks when
  Product_Helper attribute scoring treated `attribute_overlap_score`'s
  `(ratio, details)` tuple as a number. Unpacked correctly (same as Rate
  matching). Re-analyse still works; re-run Analyse on older runs to remap.
- Analysis **Next** opened an empty Make & Vendor page because display used
  missing `self.make_list`; now uses `make_list_service` /
  `_approved_makes_for_subcategory` like the rest of the service.

## 2026-08-06 — Analysis tab opens after BOQ/Make List

- Fixed Analysing-stage tab switch: BOQ/Make List no longer desync URL to
  Analysis, so the Analysis tab opens again when clicked. Starting Analyse from
  BOQ/Make List navigates to the Analysis progress panel.

## 2026-08-06 — PDF make-list multi-format wrap fix

- Wrapped PDF rows re-split after merge so brands on later lines
  (Thermaflex/Vidoflex, Minimax/Newage, Tyco/Rapidrop) land in Approved Makes.
- Category banners no longer bleed into prior rows; short labels like
  ``Plumbing pumps`` are section rows. Manufacturer-only Material lines keep
  the company name in Description. fire_kitchen re-parsed.

## 2026-08-06 — Make List peel + responsive grid

- Stopped material words (Bolts, Rods, Extinguishers, Accessories, FM…) leaking
  into Approved Makes; kept them in Description. Restored fluid Make List column
  grid so resizing no longer crushes/warps text (`app.css` `?v=107`).

## 2026-08-06 — Make List brands no longer stuck in Description

- PDF make-list parsing moves manufacturer-only lines and fused/slash brands
  into Approved Makes (e.g. Grundfoss/KSB, Tata/Jindal, Spraysafe/System Sensor,
  ASR Italy) instead of leaving them in Description.

## 2026-08-06 — BOQ tab hides Excel-hidden columns

- BOQ tab now matches the workbook UI: columns hidden in Excel (e.g. UNIT,
  EXTERNAL + TERRACE + PUMP ROOM, GF, 1ST on `New_test_cpu_kitchen.xlsx`) stay
  in stored JSON for analysis but are not shown on the BOQ tab. fire_kitchen
  re-parsed.

## 2026-08-06 — BOQ headers match uploaded workbook

- BOQ tab shows workbook header text as uploaded (e.g. `EXTERNAL + TERRACE +
  PUMP ROOM`, `GF`, `1ST`, `QTY`); only Excel newlines are collapsed. Removed
  earlier invented short/Title-Case renames.

## 2026-08-06 — Make List shows empty-makes / section rows

- PDF section banners and description-only make-list lines (empty Approved Makes)
  now appear in the Make List UI without Category mapping or approved-make
  constraints. fire_kitchen make list re-parsed.

## 2026-08-06 — Block BOQ upload without active database

- BOQ upload refuses to run when no active master database exists; the upload
  form warns the user and links to database upload.

## 2026-08-06 — BOQ tab header labels cleaned

- BOQ sheet headers normalized: Title Case, short location labels
  (`Ext. + Terrace + Pump`, `GF`, `1st`), and compact floor-column styling.

## 2026-08-06 — Make List PDF parse (Title Case brands)

- PDF make-list splitting now recognizes Title Case brands (Jaquar/Kohler),
  hyphenated Brand-Country tokens, and section headings so Approved Makes
  separate cleanly from Description across varied PDF layouts.

## 2026-08-06 — BOQ tab layout for multi-qty columns

- BOQ sheet display no longer crushes Unit/Qty when floor columns (GF, 1ST,
  EXTERNAL…) are present; headers cleaned of Excel newlines; inferred ``a)``
  serials shown in S.No when the Excel cell is blank.

## 2026-08-06 — Review S. No. uses qty-row parent

- Review/export Ser no qualifies letter slots with the qty row's nearest
  structural parent (`5.1 a)`), not the broader group serial (`5 a)(A)`).

## 2026-08-06 — Export Rate/Amount on qty rows + red unmatched

- BOQ export fills Rate/Amount on each product's Unit/Qty row (`qty_row_id`),
  not the parent section row. Rows with no matched product are highlighted red
  on both BOQ and Review exports.

## 2026-08-06 — Export sheet format (Review + BOQ)

- Review/breakdown export headers follow `Output format.xlsx`: red labels kept
  (and styled red); long Rate_Master instructional headers shortened to field
  names. BOQ export copies the uploaded workbook and fills Rate/Amount only on
  rows that have both Qty and Unit.

## 2026-08-06 — Product_Helper → Product_ID Make/Vendor flow

- Required import of `Product_Helper` (alias `Product_Master`). Analysis stores
  `catalog_product_id`. Make & Vendor loads Make/Vendor Rate_IDs by Product_ID
  (`Final_Material_Amount`). Not found / No match show **Find in DB**. Labour
  prefers `Total_Labour_Per_Unit`.

## 2026-08-05 — Status stripes match Analysis (3px inset)

- Make & Vendor / Labour / Review status stripes use Analysis format
  (`box-shadow: inset 3px 0 0` + soft border tint). Analysis is the UI reference
  for shared BOQ detail chrome on later tabs.

## 2026-08-05 — Card status color lines (dark mode)

- Dark mode no longer wipes Make & Vendor / Labour / Review left status stripes.
- Review cards map matched / pending products onto the same stripe classes.

## 2026-08-05 — Dark mode text on MV / Labour / Review

- Make & Vendor, Labour, and Review use theme text tokens and dark-mode
  overrides so labels, values, lineage, badges, and summary stay readable.

## 2026-08-05 — Review values lighter than headers

- Review values (dd / readonly inputs) use muted slate; headers stay darker so
  label and value textures differ (dark mode included).

## 2026-08-05 — Review field labels slightly bolder

- Review card headers (S. No., BOQ Description, amounts, etc.) use heavier
  label weight so they stand out from values.

## 2026-08-05 — Extract Class snap + DB context classes

- AI extract DB context now includes `classes_by_category_sub_category` and omits
  material-owned attribute keys. Post-extract snap corrects mis-filed class
  (e.g. PIPE sub_category MS copied into Class → catalog Class C). Full context
  payload is logged to `application.log` on each extract.

## 2026-08-05 — Make & Vendor Auto/filtered line badge

- Each product section header shows soft badge **Auto** or **filtered** after
  “N lines grouped” (filtered when any product uses a make-list pick).

## 2026-08-05 — Review S. No. with parent + qty-row desc

- Review S. No. includes the parent section (e.g. `1.1 a)` instead of only `a)`).
- BOQ Description uses the Unit/Qty rows (`a) 150mm dia — 350 Metre`), not the
  parent header text.

## 2026-08-05 — Review BOQ Description from qty row

- Review BOQ Description now comes from the Unit/Qty workbook row for that
  product, not the parent section header above it.

## 2026-08-04 — Review labels + BOQ description see more

- Review cards: S. No., Material amount, Total Amount. Long BOQ Description
  clamps to 2 lines with see more… / see less (export column headers unchanged).

## 2026-08-04 — Remove Review page hint text

- Removed the Review tab intro hint about product-wise review / export when ready.

## 2026-08-04 — Labour: drop duplicate Next; status right

- Removed upper Labour Next (Apply labour / Next stay in the labour toolbar).
- Status badge (Ready to Export) is right-aligned on the same row as the
  product/mode summary.

## 2026-08-04 — Fix hang: revert soft tab nav + refresh static

- Soft tab navigation (fetch + Alpine.initTree of full 0.6–1.5MB pages) caused
  UI freezes; reverted to normal `window.location` tab switches. CSS `?v=96`
  and collectstatic refreshed.

## 2026-08-04 — Remove duplicate Make & Vendor Next

- Removed the upper tab-context Next on Make & Vendor (kept the summary-bar Next).

## 2026-08-04 — Smaller match % on product tabs

- Match percentage after Product 1 / Product 2 on Analysis tabs is one size
  smaller than the label (`0.85em`).

## 2026-08-04 — Hide Analyse on MV/Labour/Review; restore Next

- Analyse BOQ no longer appears on Make & Vendor / Labour / Review (those tabs
  had empty extraction payloads so the button wrongly showed). Top-bar Next is
  restored for Make & Vendor and Labour; Review keeps Export actions.

## 2026-08-04 — MV/Labour/Review card stripe matches Analysis

- Make & Vendor, Labour, and Review even line cards use the same `#e2e8f0`
  background as Analysis alternating cards. CSS `v=95`.

## 2026-08-04 — Fast BOQ tab switching

- Make & Vendor tab build preloads Rate_Master_Output once (was ~1205 queries /
  ~2.2s per open). Detail view loads extract JSON only for tabs that need it.
- Tab clicks soft-fetch and swap `.boq-view` instead of a full page reload.

## 2026-08-04 — Make List column gap increased

- Make List `column-gap` raised from `1.5rem` to `2.75rem`. CSS `v=94`.

## 2026-08-04 — Make List column gap

- Make List grid uses `column-gap: 1.5rem` so Category / Subcategory / Makes are
  spaced farther apart. CSS `v=93`.

## 2026-08-04 — Make List all left-aligned

- Make List headers and cell values are both left-aligned. CSS `v=92`.

## 2026-08-04 — Make List content left-aligned

- Category, Subcategory, and Approved Makes values are left-aligned; headers
  remain center-aligned. CSS `v=91`.

## 2026-08-04 — Make List Category/Subcategory labels + align

- Make List columns renamed Mapped Category → Category, Mapped Sub-category →
  Subcategory. All headers center-aligned; Category, Subcategory, and Approved
  Makes values right-aligned. CSS `v=90`.

## 2026-08-04 — Make List Approved Makes header centered

- Approved Makes header is center-aligned; cell values remain right-aligned.
  CSS `v=89`.

## 2026-08-04 — Make List Approved Makes right-aligned

- Approved Makes column content is right-aligned so values sit on the panel’s
  right edge (column already filled remaining width with `1fr`). CSS `v=88`.

## 2026-08-04 — Make List row borders align

- Make List CSS grid cells stretch to equal height; horizontal border is on the
  row (not each cell) so wrapped descriptions and empty Mapped Sub-category
  cells no longer show a line cutting through mid-row text. CSS `v=87`.

## 2026-08-04 — Per-tab BOQ detail (faster tab switching)

- BOQ detail loads only the active tab’s data and HTML (BOQ / Make List /
  Analysis / Make & Vendor / Labour / Review). Tab clicks navigate to `?tab=…`
  without embedding every other tab (~3.4MB combined → single-tab payloads).

## 2026-08-04 — Make List CSS grid + smaller Make List page

- Make List uses a CSS grid so columns fill the panel; Approved Makes takes the
  remaining width (no right-side table gap).
- Make List tab HTML no longer embeds other BOQ tabs (~3.4MB → ~180KB), reducing
  cancelled loads / Broken pipe noise; log filter skips Broken pipe INFO lines.
  CSS `v=85`.

## 2026-08-04 — BOQ sheet indent capped

- BOQ Description indent no longer grows unbounded with nesting depth (was up to
  depth 6 × 14px). Visual levels are 0 / 1 / 2+ (12 / 20 / 28px) so serial and
  description stay aligned; CSS `v=84`.

## 2026-08-04 — Make List fills panel width

- Make List uses fixed rem widths for S.No / Mapped Category / Sub-category and
  `width: auto` for Approved Makes so the last column reaches the panel’s right
  edge (inline col widths + CSS `v=83`).

## 2026-08-04 — Review grouped lines + Analysis card grey

- Review attaches serial-lineage fields and shows “View N grouped lines” like
  Analysis / Make & Vendor / Labour (was missing on Review).
- Make & Vendor / Labour / Review line cards use the same `--card-stripe`
  (`#e8edf3`) grey as Analysis; CSS cache `v=82`.

## 2026-08-04 — Make List only on its own tab

- Make List table is no longer embedded in BOQ / Analysis / other tab HTML.
  It loads only for `?tab=make_list` (tab switch navigates to that URL).

## 2026-08-04 — Make List layout scoped + full-width columns

- Make List column CSS no longer applies to the BOQ sheet (or other tabs).
- Make List columns use percentages that sum to 100% so Approved Makes reaches
  the right edge (no rem max-width gap).

## 2026-08-04 — Per-product quantity on all BOQ tabs

- Restored blank product quantities from BOQ Unit/Qty slots (products had
  `qty_row_id` but lost `quantity` after mapping/rematch).
- Make & Vendor, Labour, and Review now use the same per-product slot qty as
  Analysis, including header switch when Product tabs change.

## 2026-08-04 — Softer match-band orange

- Product match % orange (90–94.99 tabs/badges) toned down from bright
  `#ea580c` / `#ffedd5` to muted `#c2410c` / `#f3e0c8`.

## 2026-08-04 — Labour → Review gate fix

- Labour Apply and Next were blocked in the UI when status was still
  `MAKE_VENDOR` (service already allowed it), and Next could no-op with no
  error. Gates aligned; complete always posts so Review can unlock.

## 2026-08-04 — Make List Approved Makes fills right edge

- Make List left columns use fixed rem widths; Approved Makes takes all
  remaining width so the column reaches the panel’s right edge.

## 2026-08-04 — Re-analyse refreshes Product tab match %

- Analysis Re-analyse now updates the Product tab match percentage and color
  band (and section confidence border) when the product panel is swapped in.

## 2026-08-04 — Visible white/grey card striping

- Product line cards on Make & Vendor, Labour, and Review use a stronger grey
  stripe (`#e8edf3`) matching Analysis, with explicit odd/even `--alt` classes.

## 2026-08-04 — Review UI slim fields + product tabs

- Review page cards no longer show Rate_ID or material breakdown fields (Base
  Purchase through Profit); they keep Make, Vendor, final rates and totals.
  Full Output-format columns remain on the Review sheet Excel export.
- Fixed missing Product tabs on some Review rows by normalizing product indices
  and simplifying Alpine (first product always visible).

## 2026-08-04 — Make List Approved Makes full width

- Make List sheet spans the full panel; Approved Makes widened (~58%) so the
  column reaches the right edge instead of leaving empty space.

## 2026-08-04 — Analysis match % colors + export serials

- Analysis Product tabs and match badges show product match percentage with
  client bands: ≥95% green, 90–94.99% orange, <90% red. Section border turns
  green only when every product in the section is ≥95%.
- Review / Review-sheet export Ser no uses each product's original BOQ slot
  serial (`1`, `1.1`, `a`, `b`, `c`). When multiple products share one serial,
  export uses `1.1(A)`, `1.1(B)`, `1.1(C)`.

## 2026-08-03 — Card white/grey striping + darker borders

- Make & Vendor, Labour, and Review product line cards use the same white /
  grey (`--surface` / `--surface-alt`) alternating pattern as Analysis.
- Default `--border` darkened slightly (`#e2e8f0` → `#cbd5e1`) so card edges
  read more clearly; CSS cache bumped to `?v=75`.

## 2026-08-03 — Review UI product cards

- Review tab UI switched from the wide sheet table to product-wise cards
  (BOQ line groups + Product tabs), matching Make & Vendor / Labour. Cards show
  all Output-format fields; Excel export format is unchanged.

## 2026-08-03 — Fix missing Rate_Master_Output tables

- Local DB had `database_manager.0001` marked applied but only legacy
  `Rate_Master` / `Labour_Master` tables existed. Created
  `Rate_Master_Output` / `Labour_master_Output` and applied `0002`. Importer
  surfaces a migrate hint if those relations are missing again.

## 2026-08-03 — Master workbook column/sheet alignment

- Confirmed `docs/BOQ_Master_03 Aug_2026.xlsx` Rate_Master_Output columns and
  datatypes match models (no migration needed).
- Import now accepts workbook sheet `Labour_Master_Output` (alias keeps older
  `Labour_master_Output`). Maps `Labour_With_State_Multiplier` into
  `Total_Labour_per_unit_with_labour_Multipler`; labour fetch falls back to
  `Total_Labour_per_Unit` when blank.

## 2026-08-03 — Review Output format + dual export

- Review tab rebuilt to the client `Output format.xlsx` columns (Ser no, BOQ
  Description, AI Interpretation, Rate_ID, Make, Vendor, full material
  breakdown, Labour, Qty, TOTAL MATERIAL/LABOUR, Amount).
- Dual export: `GET /boqs/<id>/export/?kind=review` (Review sheet) and
  `?kind=boq` (original uploaded sheet with Rate/Amount filled). Charge
  Breakdown sheet removed from the export path.

## 2026-07-31 — Stale Static Manifest (And Broken-Pipe Diagnosis)

- `staticfiles.json` mapped `css/app.css` to a 15 KB hashed build while the
  source was 51 KB, so browsers were served an outdated stylesheet no matter how
  often the `?v=` query bump changed. Re-ran `collectstatic`; the manifest now
  points at `css/app.2edc5a8cc945.css`, byte-identical to the source.
- The `- Broken pipe from ('127.0.0.1', …)` INFO lines are not an error. Django's
  dev server logs `ConnectionResetError`/`ConnectionAbortedError` under that
  message, and it fires when the browser reaps its idle HTTP/1.1 keep-alive
  sockets. Reproduced by opening three keep-alive sockets, going idle and
  closing them: three "Broken pipe" lines, no failed request. No code change.

## 2026-07-31 — Fix Broken Make & Vendor Cards (Find Rates Button)

- `vendors_by_make_json` was interpolated with `|safe` into the double-quoted
  `x-data="makeVendorForm({...})"` attribute. Its JSON quotes closed the
  attribute early, so the browser swallowed the rest of the tag and Alpine never
  initialised the card: **Find rates** rendered as an empty yellow stub, and
  `Product rate` stayed blank instead of showing its value.
- Dropped `|safe` on `vendors_by_make_json` and `same_price_choices_json` so
  Django escapes the quotes; the browser unescapes them and Alpine still
  receives a valid object literal.
- The note added beside that fix used a **multi-line** `{# … #}`. Django template
  comments are single-line only, so both lines rendered as literal text in the
  middle of the object literal and Alpine failed with
  `Alpine Expression Error: Unexpected token '{'` on every card — same dead-card
  symptoms. The comment now sits on one line above the element.
- Verified in headless Chrome: no console errors, `Find rates` visible on all
  cards, and `Product rate` populated (1800.00 / 1700.00 / …).

## 2026-07-31 — Qty/Unit Only In Analysis Section Header

- Removed quantity/unit from inside the product card and from the row below the
  Product tabs. It now appears only in the section-header position highlighted
  by the user.
- In multi-product sections, clicking a Product tab updates that header value to
  the selected product's own slot quantity/unit.

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

## 2026-08-03

**Review / Export**
- Review tab rebuilt to the client `Output format.xlsx` columns (Ser no, BOQ
  Description, AI Interpretation, Rate_ID, Make, Vendor, full material
  breakdown, Labour, Qty, TOTAL MATERIAL/LABOUR, Amount).
- Dual export: `GET /boqs/<id>/export/?kind=review` (Review sheet) and
  `?kind=boq` (original uploaded sheet with Rate/Amount filled). Charge
  Breakdown sheet removed from the export path.

---

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
