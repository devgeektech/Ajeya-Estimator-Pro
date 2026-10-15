# BOQ_AI Session State

Compact active memory. Full spec: `docs/PRODUCT.md`. Schema: `docs/DATABASE.md`.
History: `docs/CHANGELOG.md` (do not duplicate session diaries here).

### 2026-10-15 — Password Reset Branding Alignment and Professional HTML Email Template

Completed:
- **Professional HTML Email Template**:
  - Implemented responsive, branded HTML email in `password_reset_email.html` with card container, styled header (`Ajeya Estimator Pro`), CTA button, URL fallback, and security notice.
  - Added clean plain text counterpart in `password_reset_email.txt` and configured `html_email_template_name` on `BOQPasswordResetView`.
- **Branding Update**:
  - Updated all password reset templates (`password_reset.html`, `password_reset_done.html`, `password_reset_confirm.html`, `password_reset_complete.html`, `password_reset_subject.txt`) to application brand `Ajeya Estimator Pro`.
- **Confirmation Copy & Tab Title**:
  - Set tab title and page heading to "Please check your email" on `password_reset_done.html`.
  - Replaced speculative wording with definitive notice ("We've sent password reset instructions to your registered email address. They should arrive shortly.") reflecting that email registration is checked upfront.
- **Verification**:
  - All 7 accounts tests pass. Live test email dispatched and verified.

### 2026-10-15 — Final Code Cleanup, IDE Warnings Resolution, and Branch Synchronization

Completed:
- **IDE Warning Resolution**:
  - `make_vendor_display.py`: Moved `from apps.boq.models import BOQ` to module-level `if TYPE_CHECKING:` block, eliminating Pyright/Pylance inner class scoping error. Retained `MakeListConstraintService, # noqa: F401` required by mock patchers in tests. Cleaned redundant `str()` call on `rm_row.Make`.
  - `make_vendor_selection_service.py`: Cleaned redundant `str()` calls on `make_source`.
  - `logging_handlers.py`: Cleaned redundant `int()` calls on `max_lines` and `check_interval`.
- **Repository Optimization**:
  - Removed legacy scratch test files and ad-hoc scripts: `scratch_test.py`, `backend/test_candidates.py`, `backend/test_conflict.py`, `tests/test_full_ui_pipeline.py`, `tests/test_pipeline.py`.
- **Branch Synchronization & Verification**:
  - Committed cleanups on `users/vikas/new-changes`, merged into `main`, and fast-forwarded `users/vikas/main-backup`.
  - Verified test suite: all 16 Make & Vendor and logging queue tests pass with 0 errors.
  - Remote push held pending user sign-off (no push to live yet).

Pending:
- Client SMTP credentials (to be configured when provided).

Issues: None.
Next: Final review or deployment to production when instructed.

### 2026-10-15 — Documentation Alignment and Final Completion Prep

Completed:
- **Documentation Synchronization**:
  - `docs/PRODUCT.md`: Updated Make & Vendor section with separate Approved/Available make selectors, strict sub-category scoping (`allow_category_wide=False`), and available make prefilling/retention. Added Queue Retention Policies section (50 audits/user, 50 notifs/user, 5,000 log lines/file). Updated Key Files with `prune_server_data.py` and `logging_handlers.py`. Updated Runtime with production domain `portal.ajeya.in`, Let's Encrypt TLS/SSL, and direct IP blocking.
  - `docs/DATABASE.md`: Documented 50-entry per user FIFO queue limits on `AuditLog` and `Notification` models in System Tables.
  - `docs/OPS.md`: Documented `python manage.py prune_server_data` queue maintenance command and TLS configuration for `portal.ajeya.in`.
  - `docs/CHANGELOG.md`: Logged all recent features and architectural updates.
  - `README.md`: Verified all commands, file links, and scripts; added production URL (`portal.ajeya.in`) and `docs/CHANGELOG.md` entry.
- **Code Quality & Linter**:
  - Resolved all IDE / Ruff linter warnings (`RUF010` redundant `str()` calls on typed arguments and `F401` unused imports) in `boq_extraction_edit_service.py`, `make_vendor_cascade.py`, `rate_detail_retrieval_service.py`, `boq_extraction_display_service.py`, and test files.
  - Reverted incidental changes to maintain clean UI consistency on `version_detail.html` and `user_list.html`.
- **Test Suite Verification**:
  - Full test suite verified: 228 tests pass with 0 errors.

Pending: None.
Issues: None.
Next: Code review run or quick optimization run.

### 2026-10-15 — Available Make Selection Retained and Prefilled When Approved Make Not Available

Completed:
- **Available Make Prefilling & Selection Retention**:
  - In `backend/apps/boq/services/make_vendor_display.py`:
    - Added `_make_in_options(make, options)` helper using `makes_optimally_match` to accurately check if a make exists in an options list (replacing `MakeListConstraintService.make_is_allowed(make, approved_make_options)` which previously returned `True` for empty lists, incorrectly shifting available makes into empty approved makes).
    - In `_shape_product`: When approved make is not available (`not approved_make_options`), automatically assigned the selected make to `selected_available_make` and set `make_source = "available"`. If `selected_make` was unpopulated, resolved it from `rate_detail`, `selection["make"]`, `product["make_hint"]`, or `Rate_Master_Output` via `rate_master_id`.
  - In `backend/apps/boq/services/make_vendor_cascade.py`:
    - In `apply_lowest_defaults_all`: When prefilling the lowest price make, set `selected_make_source = "approved" if approved_found else "available"` so products without approved makes are tagged as `"available"`.
  - In `templates/boq/_make_vendor_table.html`:
    - In `makeVendorForm`:
      - In `init()`: When `!this.hasApprovedMakes || !this.approvedMakeOptions.length`, immediately initialized `this.availableMake` from `selAvail` or `rawMake`.
      - In `_syncMakeSelection(makeVal)`: When `!this.approvedMakeOptions.length`, routed the make selection directly to `this.availableMake`.
  - In `backend/apps/boq/views.py`:
    - Extracted `make_source` from POST in `apply_manual` and default `select_and_match`, passing it to the service.
  - In `backend/apps/boq/services/make_vendor_selection_service.py`:
    - Accepted `make_source` in `select_and_match` and `apply_manual_selection`, persisting it to `updated["selected_make_source"]` and `match_payload["make_source"]`.
- **Test Suite**:
  - Added unit test `test_shape_product_fills_available_make_when_approved_make_not_available` in `tests/boq/test_make_vendor_sync.py`.
  - All 13 tests in `test_make_vendor_sync` and all 75 BOQ tests pass.

Pending: None.
Issues: None.
Next: None.

### 2026-10-15 — Make & Vendor Product Cards Approved Makes Strictly Per Sub-Category

Completed:
- **Sub-Category Scoped Approved Makes in Product Cards**:
  - In `backend/apps/boq/services/make_list_constraint_service.py`: Updated `_entry_covers_sub` to use `_categories_equivalent` for comparing make list mapped sub-categories against target sub-categories, handling singular/plural and alias variations.
  - In `backend/apps/boq/services/make_vendor_rates.py`:
    - Updated `_approved_makes_for_subcategory` to set `allow_category_wide: bool = False` by default. When a sub-category is specified, it strictly retrieves makes mapped to that sub-category and never falls back to parent category-wide makes.
    - Updated `_options_for_product` and `_options_for_catalog_product_id` to pass `allow_category_wide=False`. If category/sub_category are missing on a catalog product, resolved them directly from `Rate_Master_Output`.
  - In `backend/apps/boq/services/make_vendor_display.py`:
    - Updated protocol stubs and `_shape_product` so `approved` uses the strictly sub-category scoped `approved_make_options`.
  - In `backend/apps/boq/services/make_vendor_cascade.py`:
    - Updated protocol stubs for `_approved_makes_for_subcategory`.
- **Test Suite**:
  - Added `test_shape_product_approved_makes_strictly_sub_category` in `tests/boq/test_make_vendor_sync.py` asserting that product cards receive only makes approved for their specific sub-category and never inherit category-wide or cross-subcategory makes.
  - All 24 targeted tests and 215 full suite tests pass.

Pending: None.
Issues: None.
Next: None.

### 2026-10-15 — Queue Retention Policies for Audit Logs, Notifications, and Server Logs

Completed:
- **Audit Logs Queue Retention (50 entries per user)**:
  - In `backend/apps/audit/services.py`: Added `MAX_AUDIT_LOGS_PER_USER = 50`, `prune_audit_logs_for_user()`, and `prune_all_audit_logs()`.
  - Updated `record()` to automatically prune entries exceeding 50 per user on every write, deleting oldest entries in FIFO order.
- **Notifications Queue Retention (50 entries per user)**:
  - In `backend/apps/notifications/services.py`: Added `MAX_NOTIFICATIONS_PER_USER = 50`, `prune_notifications_for_user()`, and `prune_all_notifications()`.
  - Updated `notify()` to automatically prune notifications exceeding 50 per user on every write, deleting oldest notifications in FIFO order.
- **Server Log Files Bounded Queue (5,000 lines per file)**:
  - In `backend/common/logging_handlers.py`: Implemented in-place line-bounded queue file handling in `SafeRotatingFileHandler` with `trim_log_file()` using `r+` seeking and `truncate()` to avoid multi-process file locking issues across Celery and web processes.
  - In `backend/config/settings.py`: Set `max_lines: 5000` for `app_file`, `error_file`, and `instruction_file`.
- **Management Command**:
  - Created `backend/apps/audit/management/commands/prune_server_data.py` allowing manual or scheduled enforcement of all three queues.
- **Test Coverage**:
  - Added unit tests in `tests/audit/test_audit_queue.py`, `tests/notifications/test_notification_queue.py`, and `tests/test_logging_queue.py`. All tests pass.

Pending: None.
Issues: None.
Next: None.

### 2026-10-15 — Domain Subdomain Migration to portal.ajeya.in & SSL (HTTPS) Enabled

Completed:
- **Subdomain Routing & Direct IP Blocking**:
  - Reconfigured Nginx (`/etc/nginx/sites-available/boq_ai`) on EC2:
    - Added default server block on port 80 returning `403 Forbidden` for direct IP or unrecognized host access.
    - Added primary server block for `server_name portal.ajeya.in;`.
  - Updated `/srv/boq_ai/.env` on EC2:
    - `ALLOWED_HOSTS=portal.ajeya.in`
    - `CSRF_TRUSTED_ORIGINS=http://portal.ajeya.in,https://portal.ajeya.in`
- **Free Let's Encrypt SSL / HTTPS Configuration**:
  - Installed `python3-certbot-nginx` on Ubuntu EC2.
  - Issued and installed Let's Encrypt TLS certificate for `portal.ajeya.in` via Certbot.
  - Enabled HTTP -> HTTPS 301 automatic redirection in Nginx.
  - Enabled `SECURE_SSL_REDIRECT=True` in `/srv/boq_ai/.env`, activating HSTS (`max-age=31536000`), secure session cookies, and secure CSRF cookies.
  - Ran `python manage.py check --deploy` with 0 issues.
  - Verified `https://portal.ajeya.in/` serves 200 OK with valid SSL, HSTS, and Secure cookies.
  - Verified `http://portal.ajeya.in/` redirects (301) to `https://portal.ajeya.in/`.
  - Verified `http://13.205.90.58/` returns 403 Forbidden.
  - Updated `docs/OPS.md` and `docs/DEPLOY.md` to reflect HTTPS.

Pending: None.
Issues: None.
Next: None.

### 2026-10-14 — Make & Vendor Separate Approved & Available Make Dropdowns & Category Cascade Isolation

Completed:
- **Separated Approved Make and Available Make Dropdowns in Product Cards**:
  - In `backend/apps/boq/services/make_vendor_rates.py`:
    - Updated `_options_for_catalog_product_id` and `_options_for_product` to return 5 distinct items: `(approved_makes, available_makes, vendor_options, vendors_by_make, makes_by_vendor)`.
    - Stopped prepending arbitrary unapproved/unavailable `selected_make` into make lists or `selected_vendor` into vendor lists, eliminating dropdown pollution.
  - In `backend/apps/boq/services/make_vendor_display.py`:
    - Updated `_shape_product` to unpack the 5 items and distinguish `selected_approved_make` vs `selected_available_make`.
    - Removed arbitrary `selected_make` and `selected_vendor` injection into `make_options` and `all_vendor_options`.
    - Added `approved_make_options`, `available_make_options`, `has_approved_makes`, `selected_approved_make`, `selected_available_make` to the product dictionary payload.
  - In `templates/boq/_make_vendor_table.html`:
    - Rendered distinct `Approved make` and `Available make` dropdowns in each product card matching the top cascade filter pattern.
    - Updated `makeVendorForm` Alpine component with separate `approvedMake` and `availableMake` states, mutual clearing on selection, dynamic `activeMake` getter, and rate auto-load/find/apply orchestration.
  - In `templates/base.html`:
    - Updated `.make-vendor-fields` to `flex-wrap: wrap;` with responsive minimum dimensions so all 6 inputs and action buttons fit cleanly without horizontal clipping.
- **Category Cascade Isolation**:
  - In `backend/apps/boq/services/make_vendor_cascade.py`:
    - Updated `apply_subcategory_make` to accept `make_source: str = ""` ('approved' or 'available').
    - Guarded cascade loop across categories:
      - If `make_source == "approved"`, verified make is approved for the product's sub-category. If not approved, skipped the product (`continue`), leaving its existing valid selection untouched.
      - Checked `match_payload.get("status") == "matched"`. If the product has no matching rate in the database for that make, skipped the product (`continue`), preventing category cascade from corrupting unapproved/unavailable products or turning them into `unmatched`.
  - In `backend/apps/boq/views.py`:
    - Extracted `make_source` in `BOQMakeVendorSelectView.post` and passed to `service.apply_subcategory_make`.
  - In `templates/boq/_make_vendor_table.html`:
    - In `applySubcategory()`, sent `make_source: this.availableMake ? 'available' : 'approved'`.
- **Test Suite & Static Analysis**:
  - Added unit tests `test_category_cascade_skips_unmatched_or_unapproved_products` and `test_shape_product_separates_approved_and_available_makes` in `tests/boq/test_make_vendor_sync.py`.
  - Pyright passed with 0 errors across `backend/apps/boq/`. All 162 unit and integration tests passed cleanly.

Pending: None.
Issues: None.
Next: Deploy changes to EC2 or proceed with active feature work.

### 2026-10-14 — Typing and Static Analysis Fixes Across BOQ Services & Views

Completed:
- Resolved Pyright and IDE linter errors and warnings across views and services:
  - In `backend/apps/boq/views.py`: Fixed `_render_extraction_line_html` call argument type mismatch by prioritizing `editor.last_matched_row_id` over `row_id`, guaranteeing non-None `str` type.
  - In `backend/apps/boq/services/boq_extraction_edit_service.py`: Removed redundant `str()` cast on typed string field `product_id`.
  - In `backend/apps/boq/services/make_vendor_cascade.py`: Removed redundant `str()` cast on typed parameter `product_id`.
  - In `backend/apps/boq/services/make_vendor_rates.py`: Removed redundant `str()` casts on `product_id` and cached row field `row.get("product_id")`.
  - In `backend/apps/boq/services/rate_detail_retrieval_service.py`: Removed redundant `str()` casts on typed string parameters `make` and `vendor`.
- Ran static analysis checks (`pyright`) and test suite (`test_extraction_edit`, `test_make_vendor_sync`); all 23 tests pass cleanly.

Pending: None.
Issues: None.
Next: Deploy changes to EC2 or proceed with active feature work.

### 2026-10-13 — Make & Vendor Product-Wise Cascade Filtering & Exact Product_ID Scope Preservation

Completed:
- **Product-Wise Cascade Filter Selection in Make & Vendor**:
  - Resolved issue where applying a cascade filter for Category `TANK` and Sub-category `AIR CUSHION TANK` caused both section 15 (Product ID 238, 300 mm) and another section (Product ID 161, 200 mm) to both change to Product ID 161 (picking the lowest-price variant across the sub-category bucket).
  - Extended cascade selection catalog (`_collect_extraction_catalog` and `_build_selection_catalog`) to collect `products_by_sub` and construct `products` list for each sub-category, containing product IDs, sizes, units, make options, vendors, and prices specific to each product.
  - Added `Product` dropdown to the Make & Vendor cascade selection panel (`templates/boq/_make_vendor_table.html`), allowing users to select an exact product or all products in the sub-category.
  - Updated Alpine.js `makeVendorSubcategoryPanel` component: added `productId` state, `products`, `currentProduct`, dynamic `activeScope`, and button label dynamic text (`Apply to product <id>`).
  - Updated `apply_subcategory_make`, `remove_subcategory_filter`, `_restore_scope_to_lowest`, and storage keys (`category::sub_category::product_id`) in `make_vendor_cascade.py` and `views.py` to support `product_id`.
  - In `apply_subcategory_make`, `_capture_analysis_product_id` is now run prior to rate evaluation, ensuring the analysis-selected Product_ID is strictly preserved and rates for that specific product ID variant are retrieved.
  - Updated `templates/base.html` `.make-vendor-subcategory-panel__grid` to 7 responsive columns with breakpoints.
  - Displayed `product_id` in the Applied Filters list and ensured filter removal targets the specific product ID.
- **Test Coverage**:
  - Added `MakeVendorProductWiseCascadeTests` in `tests/boq/test_make_vendor_sync.py` verifying targeted product updates and catalog construction. All 213 tests passing cleanly.

Pending: None.
Issues: None.
Next: Deploy changes to EC2 and verify on live instance.

### 2026-10-13 — AI Description Synchronization on Product Selection & Manual Product ID Load

Completed:
- **AI Description (`description_hint`) Automatic Refresh on Catalog Match**:
  - Identified issue where manually loading a Product ID (`load_by_product_id`), selecting a database candidate (`select_candidate`), confirming a match (`confirm_match`), or filling in a Product ID on the form (`update_product`) retained stale initial BOQ extract descriptions in `description_hint`.
  - In `ProductAIMappingService.apply_selected_candidate`, rebuild `aligned["description_hint"] = compose_description_hint(aligned)` so candidate selections and manual loads derive the AI Description from the chosen database product attributes.
  - In `BOQExtractionEditService.select_candidate`, `load_by_product_id`, and `confirm_match`, removed previous bypasses and ensured `updated["description_hint"]` is automatically regenerated from the chosen database product.
  - In `BOQExtractionEditService.update_product`, added `"product_id"` handling to `_PRODUCT_SCALAR_FIELDS` and form fields parsing in `BOQExtractionEditView`: when a user manually enters or changes a Product ID matching `Rate_Master_Output`, the catalog product is loaded, locked at 100%, and `description_hint` is re-composed to match the newly loaded catalog item.
  - In `_shape_product` and `build_product_save_feedback`, passed `description_hint` in AJAX responses so auto-save immediately updates the form textarea without page reload.
  - In `_extraction_line.html`, added `@keydown.enter.prevent="loadProductId($el.value)"` on the Product ID input field for quick loading on Enter.
  - In subsequent phases (Analysis tab, Make & Vendor card header `description_hint`, Labour card header `description_hint`, and Review / Export `_ai_interpretation`), the updated description is now consistently used.
- **Test Coverage**:
  - Added `DescriptionHintUpdateOnProductMatchTests` in `tests/boq/test_extraction_edit.py` covering candidate selection, manual load by ID, manual product ID entry, and confirmation. All 211 tests passing cleanly.

Pending: None.
Issues: None.
Next: Deploy changes to EC2 and verify.

### 2026-10-13 — Review & Output Sheet Price Sync with Active Database & 4-Column Highlights

Completed:
- **Active Database Rate Resolution & Synchronization in Review and Export Sheets**:
  - Investigated price discrepancies reported in Review tab and export sheets: products processed under earlier database versions retained stale `rate_detail` snapshots in `analysis_data` (`vendor_selection.rate_detail`).
  - Extended `RateDetailRetrievalService` with `get_by_rate_id`, `get_by_product_make_vendor`, and `resolve_rate_detail` to resolve accurate `Rate_Master_Output` snapshots across primary key, `Rate_ID`, or `Product_ID` + Make + Vendor.
  - Updated `BOQReviewDisplayService._product_line` to dynamically re-resolve `rate_detail` against the active database version and recalculate `line_output` via `BOQLineOutputService.build(...)`. This ensures material rates, sub totals, profit values, final rates, and amounts in both the Review UI and exported Excel sheets strictly match the active master database.
  - Updated `MakeVendorCascadeService.sync_analysis_product_ids` so that when preserving existing Make & Vendor picks during sync, rates are re-resolved against the active database instead of preserving stale snapshots.
- **Export Sheet Highlighting (Sub Total, Final Material Amount, Final Rate, Amount)**:
  - Updated `_HIGHLIGHTED_REVIEW_COLS` in `boq_export_service.py` to highlight strictly the 4 requested columns in yellow (`FFFF00`):
    1. `Sub Total` (Column 15, `_REVIEW_SUBTOTAL_COL`)
    2. `Final Material Amount` (Column 17, `_REVIEW_FINAL_MATERIAL_COL`)
    3. `Final Rate` (Column 19, `_REVIEW_FINAL_RATE_COL`)
    4. `Amount` (Column 23, `_REVIEW_AMOUNT_COL`)
  - Other columns (e.g. Net Material Rate, Total Material, Total Labour) now use the standard royal blue `#1976E7` styling.
- **Test Coverage**:
  - Updated `test_boq_export.py` to assert the 4 yellow highlighted columns and blue styling on others.
  - Added test cases in `test_labour_retrieval.py` verifying rate resolution across `Rate_ID`, `Product_ID`, and live synchronization in `BOQReviewDisplayService`. All tests pass.

Pending: None.
Issues: None.
Next: Deploy to EC2 server and verify BOQ 27 / 29.

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
