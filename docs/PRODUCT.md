# BOQ_AI — Product & Technical Reference

Single source of truth for what the system does, how it is built, and the rules
agents and developers must follow. Update this file when product scope, structure,
or architecture changes.

---

## Overview

BOQ_AI is an AI-assisted BOQ estimation platform for Fire Protection and MEP.
It imports a client master workbook, uploads BOQ/make-list files, runs AI
analysis, Make & Vendor / Labour selection, review, and Excel export.

**Current scope (2026-07-30):**

| Feature | Status |
| --- | --- |
| User auth, roles, dashboard | Active |
| Master database upload / history / embeddings | Active |
| BOQ upload, parse, Analysis, Make & Vendor, Labour, Review, Export | Active |
| Pending-products Super Admin approval flow | Not built |

**Active BOQ pipeline:**

```text
Upload → Analyse (extract + map) → Make & Vendor → Labour → Review → Export
```

---

## Users & Roles

| Role | Access |
| --- | --- |
| **Superadmin** | Full access; user management; database management; sees all BOQs |
| **Admin** | User management; database management |
| **Expert** | Upload BOQs; database access only when granted |

Authentication: email login, password reset, no public registration. Users are
created by admins.

---

## Active Workflows

### Master database import

```text
Upload workbook → Validate → Import Product_Helper + Rate_Master_Output +
Labour_master_Output → Activate version → Generate embeddings
```

- Runs **synchronously** in the upload request (no Celery).
- `Product_Helper`, `Rate_Master_Output`, and `Labour_master_Output` are **required**.
- Other workbook sheets may exist; they are **not ingested** (UI counts only).
- **Discontinued products:** Product_Helper rows whose ``Status`` (column I) is
  ``Discontinued`` are not imported. Rate and Labour rows for those
  ``Product_ID`` values are skipped too, so they never get Chroma embeddings and
  cannot be returned during Analysis matching.
- Exactly **one** active `DatabaseVersion` at a time; Chroma holds embeddings for
  the active database only (**one vector per Product_Helper row**, full catalog
  fields + `Product_ID`; discontinued Status excluded at embed time).
  **Chroma / vector search is used only to find the product and its Product_ID
  during Analysis.** Make/Vendor options, material amounts, and labour charges
  are always loaded from PostgreSQL (`Rate_Master_Output` /
  `Labour_master_Output`) by that Product_ID — never from the vector store.
- Stored upload file is datetime-stamped; download uses original filename.
- Last **10** uploads remain visible for view/download (metadata + workbook file).
- Master sheet rows are stored in PostgreSQL only for the **active** upload.
- No rollback — new upload replaces the active database.
- Catalog identity: **`Product_Helper.Product_ID`**. Pricing amount:
  **`Final_Material_Amount`**. Labour: **`Labour_With_State_Multiplier`** by
  Product_ID (model `Total_Labour_per_unit_with_labour_Multipler`).
- Embeddings skip cleanly when OpenAI is not configured.

Entry point: `DatabaseImportService` in `apps/database_manager/services/importer.py`.
Views call the service directly (thin views).

### BOQ upload

```text
Upload BOQ (+ optional make list) → parse to JSON → store files + hierarchy
```

- **Requires an active master database.** If none is active, upload is blocked
  (service raises validation error; upload form shows a warning and disables
  submit) until a database is uploaded and activated.
- BOQ workbook: `.xlsx` / `.xlsm` / `.xls` (legacy `.xls` is converted to
  `.xlsx` on upload via `XlsUploadConversionService`, then parsed with openpyxl)
- Make list: `.xlsx`, `.xlsm`, `.xls`, or `.pdf` (same `.xls` conversion)
- Excel BOQ and make-list uploads must contain **exactly one worksheet**. Multiple
  sheets are rejected with a validation error asking for a single sheet of BOQ or
  make-list details.
- After Analyse, **Make & Vendor stays locked** until **Next** runs
  `apply_lowest_defaults_all` (sets `make_vendor_defaults_applied` and prefills
  lowest make/vendor per product). Manual cascade filters override those
  defaults afterward.
- **No make list uploaded:** Next and cascade **Lowest price** pick the cheapest
  Rate_Master_Output row for each product’s category/sub-category across **all** makes.
- **Make list uploaded:** cascade approved makes come only from the make list for
  that scope — if none map, UI shows “No Approved Make Found in Make List”
  (no fallback to all makes). Cascade: Category required; Sub-category optional
  (blank = entire category).
- Make-list ↔ Rate_Master_Output make comparison uses optimal matching (normalize,
  fingerprint, similarity) so spelling variants still count as approved.
- **BOQ name must be unique** (case-insensitive) so each upload gets its own
  `media/extract_json/{boq_name}/` folder.
- On upload, rows are normalized by serial number (`1`, `1.1`, `a`, `(a)`, `a)`,
  section romans `I`/`II`/`III`, etc.) into JSON (`boq_data`, `make_list_data`)
  while preserving hierarchy for UI, AI extraction, and future priced export.
- **Analysis uses adaptive serial lineage sections:** small related clusters stay one
  Analysis card (parent + children). Oversized chapter trees (too many lines / qty
  rows / characters) are split at dotted packages (``1.1``, ``2.1``, …) so products
  under large BOQ chapters are extracted separately; shared ancestor text is still
  passed to AI. Chapter-owned qty rows that sit **before** those packages (for
  example pipe sizes ``c)``–``j)`` under ``1`` before ``1.1``) stay on a Section
  ``1`` card **in sheet order**, not after ``1.14``. Extract batches are also packed
  by payload size so huge sections are not dropped in one OpenAI call. Amounts still
  come only from filled Unit/Qty cells
  inside each section (``0`` kept as 0; ``Rate Only`` keeps that marker and copies
  BOQ ``boq_rate``).
- Hierarchy also nests Operating Temp / roman-numeral continuation lines under the
  nearest lettered product, supports indent fallback when serials are sparse, and
  merges multi-sheet workbooks that look like BOQ tables (`sheets` on payload;
  sheet-prefixed `row_id` only when more than one sheet is merged).
- Empty / unrecognizable parses **fail the upload** (no silent empty JSON).
- Normalized JSON is also written to `media/extract_json/{boq_name}/` as
  `boq_data.json` and `make_list_data.json` for downstream AI analysis.
- **Make List section banners** (e.g. “Pipes and Fittings”, “RO Plant”) and other
  description-only lines with an empty Approved Makes column are shown in the UI
  as display rows (`is_section_heading` / empty makes). They are **not** category-
  mapped and do **not** contribute approved-make constraints. Manufacturer-only
  PDF make lists handle wrap lines, category banners, manufacturer-only Material
  rows, and fused/slash brands; Approved Makes stay out of Description.
  Material nouns that look Title Case in PDFs (``Drum`` / ``Drums`` / ``Reel`` /
  ``Modules``, etc.) are kept in Description — never peeled into Approved Makes.
  Stored make lists re-parse from the uploaded file when ``parse_version`` is
  stale (restores rows dropped by older parsers, e.g. missing serial 1). Split
  repair also runs on load. Category / Subcategory mapping is **AI-first**
  (``map_make_list_categories`` v11): the model reads free-text meaning and may
  return **multiple** ``targets`` ``[{category, sub_category}, …]`` for compound
  lines (e.g. ``Sprinklers & Rosette Plates (All Types)`` → SPRINKLER with blank
  sub **and** ACCESSORIES / ROSETTEE PLATE). Catch-all equipment lines map by
  meaning (typically HYDRANT, blank sub). ``All Types`` / unnamed subtypes leave
  ``sub_category`` null for that family (approved makes apply category-wide).
  Heuristic phrase hints are soft only. Mapping version **v11**.
- View page shows **BOQ** and **Make List** tabs with indented sheet layout
  (BOQ description indent capped at two visual levels so deep nesting does not
  create large mid-row gaps). **BOQ tab headers** match the uploaded workbook’s
  **visible** columns (Excel-hidden columns such as location breakdowns are kept
  in stored JSON for analysis but omitted from the tab). Header labels keep the
  workbook wording (newlines collapsed to spaces only).
  Make List uses a full-width CSS grid with
  equal-height stretched cells and row-level borders (avoids mid-row lines when
  descriptions wrap or mapped sub-category is empty). Approved Makes are stored
  in ``approved_makes_list`` with **no fixed count limit** (5–6+ brands are fine);
  ``approved_makes`` / ``approved_makes_2``… columns are mirrors that grow to the
  longest row. Each detail tab is
  server-rendered alone (`?tab=…`) so switching does not download all tab
  panels at once. Make & Vendor display preloads Rate_Master_Output once
  (no per-product N+1).
- Attribute value synonyms (e.g. MS→mild steel, DI→ductile iron) are applied during
  Analyse attribute comparison via `utils/attribute_parser.py`.
- Product/material synonym map lives in `utils/product_synonyms.py` (materials +
  phrases such as NRV/Reflex Valve/check valve). The same map is injected into
  AI prompts (`extract_products`, `map_product_match`, `map_make_list_categories`)
  via ``{{SYNONYM_MAP}}`` so extraction and matching share one source of truth.

Entry point: `BOQCreationService` in `apps/boq/services/boq_service.py`.

### BOQ analysis — pipeline

```text
Step 1 — Analyse:       rows → AI extract products only → attributes (Analysis tab)
Step 2 — Make & Vendor: select Make + Vendor → exact Rate_Master_Output row (Final_Material_Amount)
Step 3 — Labour:        Auto (Labour_master_Output by Product_ID) or Manual (% of material by category)
Step 4 — Review:        (material + labour) × quantity → Export Excel
                         (qty 0 / Rate Only / RO → material_rate + labour_rate only)
```

**Section combining (Analyse):**

- A **section** is a serial package (e.g. `1.04`, `1.1`) plus owned detail rows until
  the next peer serial.
- **Slots** = rows with Unit+Qty filled (`0`, numeric, Rate Only / RO). One slot →
  one product; N slots → N products. **Main products are only those qty+unit
  rows**; other lines are description/evidence for linkage, not separate products.
- Detail/reference rows without qty are **evidence** for those products (not
  separate priced lines). Single-qty packages (e.g. long panels) are never split
  into blank-serial fragments.
- Products keep `quantity`, `quantity_unit`, `qty_row_id`, `slot_index`, `rate_only`
  in `analysis_data` through Make & Vendor → Labour → Review.
- Empty sections with qty slots stay visible: **+ Add product** and **Re-analyse with AI**.
- **Job Only:** empty-product sections with Unit ``Job`` (AI default), or any
  section after the expert removes every product. **+ Add product** clears Job
  Only and shows the product form. Removing the last product marks Job Only
  again. Make & Vendor / Labour / Review / Export follow the same mark.

**Status pipeline** (persisted on `BOQ.status`):

| Status | Label |
| --- | --- |
| `UPLOADED` | Uploaded |
| `PROCESSING` | Analysing... |
| `EXTRACTED` | Analysed |
| `MAKE_VENDOR` | Make/Vendor selection (set when Analysis → Next applies defaults) |
| `LABOUR` | Labour (set when Make & Vendor → Next) |
| `READY_EXPORT` | Ready to Export (after Labour → Next aggregates row pricing) |
| `EXPORTED` | Exported |
| `ANALYSIS_FAILED` | Failed |
| `MATCHING` / `PROCESSED` | Legacy (unused in active UI) |

Opening BOQ detail (list **View** or bare `/boqs/<id>/`) selects the tab from
status: Uploaded → BOQ; Analysing/Analysed/Failed → Analysis; Make/Vendor →
Make & Vendor; Labour → Labour; Ready to Export / Exported → Review. An explicit
`?tab=` still wins when that tab is unlocked.

**Step 1 — Analyse** (BOQ detail → **Analysis** tab):

- Extracts **products only** (no labour/installation activities). Labour charges
  come later from Labour_master_Output by Product_ID on the Labour tab.
- Button: **Analyse BOQ** (toolbar, first run only) → `POST /boqs/<id>/extract/`
  via `dispatch_boq_extraction`. Full-BOQ re-analyse is not offered in the toolbar;
  use per-row **Re-analyse**.
- Per-row: **Re-analyse** (Analysis tab) → `POST /boqs/<id>/rows/<row_id>/extract/`
  - With products: **product rematch** (`mode=rematch` + `product_index`) — saves
    that product’s filled fields, sends BOQ row description + prior Product_IDs
    into ``ProductAIMappingService.rematch_product``, remaps that product only.
    The Analysis page stays at the same scroll position after Re-analyse and
    after leaving for BOQ / Make List and returning.
  - Empty section: **re-extract** (`mode=reextract`) via
    `BOQAnalysisService.re_extract_row` + `extract_products.txt`.
- Celery task: `boq.process_extraction` (full BOQ only)
- Concurrent analyses: Celery worker `--concurrency` (default **8** via
  `scripts/run_celery_worker.*`; override with `CELERY_WORKER_CONCURRENCY`)
- Stuck jobs: if progress stops for **5 minutes**, or shows 100% complete/failed
  while status is still `PROCESSING`/`MATCHING`, the BOQ is marked
  `ANALYSIS_FAILED` (or `EXTRACTED` if matching stalled with rows) so **Analyse**
  can be clicked again. Task timeouts/crashes also fail the BOQ.
- Status: `PROCESSING` → `EXTRACTED`
- Flow per product:
  1. AI extract product fields/attributes from the **BOQ row as source of truth**
     (always includes `category` + `sub_category` from BOQ meaning; DB context lists
     **categories**, **sub_categories_by_category**, and
     **classes_by_category_sub_category** plus a deduped ``classes`` list so AI
     maps onto existing Rate_Master_Output labels; values are snapped to DB
     labels after extract — e.g. PIPE material MS stays in sub_category, Class
     snaps to catalog Class such as C or ``0`` for sluice valves)
  2. Retrieve nearest Product_Helper neighbors from Chroma (complete catalog
     row embeddings; discontinued Status excluded at embed time), take Product_ID,
     then load Rate_Master_Output rows for that Product_ID (AI validates up to
     **5** neighbors; UI shows top **3**). Synonym-aware SQL remains a fallback.
     Initial Analyse also uses BOQ section text in recall and runs one weak
     product rematch pass (&lt;50%). Wrong nominal sizes are penalized when extract
     size is filled; candidates are deduped by Product_ID; Class ``0`` is a real
     score token. Description-vs-catalog type checks use **Category + Sub_Category
     + Class** (not Sub alone) and apply a soft penalty — they must not hard-floor
     correct PIPE matches at 29% when Sub is ``MS``. Blank category/sub still get
     partial credit from ``description_hint``. System names like ``Yard Hydrant
     System`` must not override pipe/valve product nouns for size-only slots.
  3. **AI mapping layer** (`ProductAIMappingService`) selects the best candidate when
     blended confidence ≥ 30%; otherwise status is `provisional` (schema for
     gap-fill, no confirmed `db_product_id` / Product_ID) or `unmatched`
  4. After a confirmed match with confidence **≥ 50%**, **category / sub_category /
     class / size / unit / capacity are filled from the matched Rate_Master row**
     into the Analysis UI columns (so experts see the fetched product details).
     When confidence is **below 50%**, those inputs (and Attribute values) stay
     **empty** for expert fill or candidate Select; a warning explains that no
     confident match was found and points to the top **3** selectable database
     candidates (or manual entry + Re-analyse). The suggestion banner and top
     candidates remain visible. Attributes from BOQ evidence still map onto the
     DB schema when confidence is ≥ 50%.
  5. Attribute UI uses the selected candidate’s Attribute schema; values are filled
     only from BOQ-extracted evidence the AI can map (empty keys stay blank for experts)
  6. If the wrong product was picked, the reviewer edits fields/attributes (blank
     or wrong columns, including **AI Description** / ``description_hint``) and
     clicks **Re-analyse** on **that product**. AI Description is composed as
     ``Category / Sub-category / Class / Size / Unit / Capacity`` plus key
     attributes (IS, Type, Material, …). Experts may rewrite it in plain language
     for rematch; rematch uses that text first plus the **full BOQ section**,
     refreshes database candidates, and AI picks the best Rate_Master neighbor
     (`rematch_product`). System titles (e.g. Yard Hydrant System) must not
     override slot products (pipe/valve).
     Expert-filled inputs (including Class ``0``) are kept; one-product rematch
     does not change sibling products. Empty sections with no products still
     **re-extract** from the workbook.
  7. Experts can **Select** any of the top 3 database candidates to confirm that
     Rate_Master_Output product (override AI pick). Selecting keeps that candidate’s
     listed match % (does not invent a new score) and loads its Rate_Master details
     into the UI columns.
- Analysis UI shows matched / suggested / unmatched status, top **3** candidates
  (selectable) as ``Product ID / Category / Sub / Class / Size /
  Unit / Capacity`` then attributes after a tab (``0``, ``null``, ``NA``,
  ``NB`` are shown as stored). **Rate_ID is not shown** — Analysis identifies
  catalog products by ``Product_ID`` only. Confidence badge and DB
  attribute fields (empty when missing). Experts add
  more attributes with **+** beside the Attributes heading (no separate
  Additional Attributes section). Top database candidates stay **collapsed**
  by default (click the summary to expand). When a product is unmatched or
  low-confidence (“Unable to match…”), the top candidates list opens automatically
  so experts can Select without hunting for it.
- **Multi-product review:** when extracted product count and Unit/Qty row count
  disagree in a section — e.g. **1 qty row → 2+ products**, or **2 qty rows →
  only 1 product** — the card is flagged **Multi-product review** for expert
  check. Matching counts (1↔1, 2↔2, 3↔3, …) are not flagged. Hollow
  slot-fallback products (AI omitted a slot) stay visible for expert fill but
  do **not** use the Multi-product review badge when counts already match.
  Initial extraction treats Unit/Qty slots
  as a **minimum**, not a cap: every filled slot must produce at least one
  product, while separately evidenced extra products are retained. Identical
  copies of the same product on one slot are collapsed (one Set / one panel). If AI omits a
  slot, extraction retries that section once with explicit slot coverage. If it
  still omits the slot, a BOQ-evidence review product preserves that line rather
  than silently dropping it. Section-only header rows are hidden (products live
  with the Unit/Qty groups).
- **Candidate match %:** each top database candidate is scored from filled product
  fields against that Rate_Master row (fixed field weights — size+unit alone
  cannot normalize to 100%). Scores use extract/expert fields, not fields copied
  from Rate_Master after a pick. Unrelated product types stay below the 30%
  confirm threshold even if category/size were overwritten.
- **Per-slot details:** each lettered Unit/Qty slot carries a ``size_hint`` and
  local evidence. After AI extract, code rebinds size/unit from that slot,
  prefers BOQ PN rating for capacity, keeps catalog Class ``0``,
  and copies shared parent attributes (IS, seat, connection) onto every product
  in the section so later letter products are not left thinner than product 1.
- **Product match percentage** on each Analysis Product tab/card uses
  `db_match_confidence` (fallback: attribute confidence) with client bands based on
  the **rounded** percentage shown in the UI: **≥95% green**, **90–94% orange**,
  **<90% red**. Section left border is green only when every product in that
  section is ≥95%.
- Attribute-fill helper band (schema completeness) remains ≥80 / >70 / >50 for
  internal fill scoring; the tab/card UI shows the product match percentage above.
- Analysis confidence is **product-only** (category, sub-category, class, size,
  unit, capacity, attributes). Make / vendor / brand fields are excluded from the
  score, Chroma query, and AI mapping payload — Make & Vendor owns vendor selection.
- **Interactive review:** all product fields (class, size, capacity, unit, etc.) are
  optional — products differ in which properties apply. Users can edit filled fields.
  Saves via `POST /boqs/<id>/extraction/edit/`
  (`BOQExtractionEditService`). Edits persist in `analysis_data` before Make & Vendor.
- **Unit vs quantity_unit:** product ``unit`` is the Rate_Master_Output measurement unit
  (mm, cm, NB, inch, …) used for matching; BOQ row UOM (Each, Nos, Mtr) maps to
  ``quantity`` / ``quantity_unit`` only — never into product ``unit``.
  Quantity comes from filled Unit/Qty **slots** inside the section
  (including ``0`` and ``Rate Only`` / ``RO``); for Rate Only the BOQ rate cell is
  stored as ``boq_rate``. Each product binds to its own slot. Analysis, Make &
  Vendor, Labour, and Review show the active product's quantity/unit in the
  section header; switching Product tabs updates that header. Blank stored
  quantities are rehydrated from BOQ slots on display and after Analyse /
  Re-analyse / Labour Apply.
- **Pricing:** normal lines use ``(material_rate + labour_rate)`` via amounts
  ``material_rate × qty`` and ``labour_rate × qty``. For qty ``0`` or Rate Only / RO,
  Review/Export show the **sum of unit rates only** (no quantity multiply), flagged
  with ``amount_is_rate_sum``.
- **Class vs material:** product ``class`` maps to Rate_Master_Output ``Class``.
  Use the listed Class for that category / sub-category (``0`` is real for
  valves). Body material (DI, ductile iron) stays in ``attributes.material``
  unless that token is itself the listed Class (e.g. NRV Class ``CI``).

**Step 2 — Make & Vendor** (BOQ detail → **Make & Vendor** tab, after Analyse):

- From Analysis, toolbar **Next** (blue) requires every product to have a loaded
  or selected **Product Id**. If any are missing, Next shows a warning to
  **Confirm Manually** / Select a candidate, or remove the product from Analysis.
  When all Product Ids are present, Next sends each ``catalog_product_id`` into
  Make & Vendor, queries PostgreSQL Rate_Master_Output by that Product_ID, and
  prefills the **lowest-price** row among **approved makes** when a make list
  exists (or among all makes for that Product_ID when none was uploaded / no
  approved make), then opens **Make & Vendor** and sets status `MAKE_VENDOR`.
- Analysis shows a view-only **Product Id** column before Category for the
  matched or selected catalog id.
- After full Analyse completes, the page **stays on Analysis** (review first;
  use Next to continue).
- Enabled when `analysis_data.rows` exist and Make & Vendor defaults have been
  applied (`MAKE_VENDOR` / later pipeline statuses).
- Analysis attaches **`catalog_product_id`** (Product_Helper `Product_ID`) when
  the matched Rate_Master_Output row (or structured Product_Helper match) resolves.
- Make and Vendor ``<select>`` dropdowns list Rate_Master_Output combinations for
  that Product_ID. The Make list always shows every available make. Selecting a
  Make scopes Vendor to that make's vendors; clearing Make shows all vendors.
  Product rate = **`Final_Material_Amount`**.
- Line headers show a soft badge **Auto** (lowest-price default) or **filtered**
  (any product has an expert make-list pick), after “N lines grouped” when present.
- **Not found** / **No match** keep the same Make/Vendor dropdowns (options from
  Product_ID → Rate_Master on page load). Selecting a pair **previews** the product
  rate only; the card stays red until **Apply**, which commits the match (green)
  and reloads in place on that card. Free-text Make/Vendor is only used when no
  dropdown options exist.
- **Sub-category makes:** top panel lists **category → sub-category → make → vendor**
  (only categories/sub-categories present in Analysis extraction). **Apply to sub-category**
  sets make/vendor on every product in that sub-category and loads rates. When a
  **sub-category is selected**, Approved make lists only makes for that sub
  (make-list mapping for the sub, else approved ∩ Rate_Master makes for the sub) —
  not the full category / whole make-list dump. Default make is
  **Lowest price** (approved-make constrained when a make list exists). The cascade
  panel shows **Price** for the selected category / sub-category / make /
  vendor before Apply. Empty vendor also
  picks the lowest-priced Rate_Master_Output row for the chosen make. Changing Make on a
  product or the cascade panel reloads **all** Rate_Master_Output vendors for that make
  (scoped to Product_ID when known). When two or more
  Rate_Master_Output rows for that make share the same lowest price (typically different
  vendors), the product is flagged **Multiple product detected in same price** and
  the expert must choose one. Applied filters list shows manual cascade applies.
  Removing one filter (×) or **Clear all** restores those sub-category products
  to the **lowest-price** Rate_Master make/vendor combination.
- Selection persisted per product as `selected_make`, `selected_vendor`, `vendor_selection`;
  sub-category choices stored in `analysis_data.subcategory_make_selections`.
- AI does not choose make/vendor or calculate prices — rates are read from the master DB.
- Make & Vendor UI shows **product rate only** in a view-only field beside
  Make/Vendor (labour charges belong on the Labour tab). Confidence / product
  display key are not emphasized on this tab — `Product_ID` is stored on
  `vendor_selection` for Labour.
- When two or more matched products share the **same material rate** but use
  **different make/vendor** pairs, those cards are highlighted for **vendor
  review/confirmation** (summary count included).
- Toolbar **Next** (on Make & Vendor) unlocks **Labour** (Match rematch is retired from the UI).
- **Client approach (experimental):** full narrative, business rules, demo script, and
  decision checklist for stakeholder review — [`docs/MAKE_VENDOR_APPROACH.md`](MAKE_VENDOR_APPROACH.md).

**Step 3 — Labour** (Labour tab, after Make & Vendor → Next):

- Status `LABOUR`. Product_ID is resolved from Analysis `catalog_product_id` /
  `suggested_catalog_product_id`, Make & Vendor `vendor_selection.product_id`,
  or `rate_detail.product_id` (same join key as rates — PostgreSQL only).
- Make & Vendor **Next** unlocks Labour **and auto-loads** Labour_master_Output
  charges by Product_ID (`BOQLabourService.unlock` → `apply_auto`).
- **Auto:** for each product, load Labour_master_Output by Product_ID and fill labour rate/amount
  from **`Labour_With_State_Multiplier`** (fallback: `Total_Labour_Per_Unit`,
  then `Labour_Rate_Per_unit`)
  (`BOQLabourService.apply_auto` → `LabourDetailRetrievalService`).
  Toolbar **Apply labour** re-runs this load (Auto or after switching back from Manual).
- **Manual:** enter a percentage per extraction category; labour =
  material × (percent / 100) for every product in that category
  (`BOQLabourService.apply_manual`).
- Line pricing: **(material + labour) × quantity** after Labour → Next
  (`BOQPriceCalculationService`).
- Persist `analysis_data.labour_config` (`mode`, `category_percentages`, `labour_ready`).
- Toolbar **Next** runs row pricing aggregate and sets `READY_EXPORT`
  (`BOQLabourService.complete` → `BOQPriceCalculationService`).
- Apply / Next UI gates allow `MAKE_VENDOR` as well as `LABOUR` (and later
  pipeline statuses) so labour remains editable if status has not yet advanced.
- **Client progress report:** [`docs/LABOUR_CLIENT_REPORT.md`](LABOUR_CLIENT_REPORT.md)
  (capabilities, UX delivered, demo script, confirmation checklist).

**Step 4 — Review + Export** (Review tab):

- Product-wise cards (same line / product-tab pattern as Make & Vendor and
  Labour), including serial-lineage “View N grouped lines” when a section spans
  multiple BOQ rows. On-screen cards show Ser no, Description, AI Interpretation,
  Make, Vendor, Final Material Amount, Labour, Qty, TOTAL MATERIAL, TOTAL LABOUR,
  and Amount (material breakdown columns stay on the Excel Review export only).
- Line cards on Make & Vendor / Labour / Review use the same white /
  `--card-stripe` zebra as Analysis, and the same **inset 3px** left status
  stripe format as Analysis confidence borders (`box-shadow: inset 3px 0 0`).
- **UI reference:** Analysis is the visual/format source of truth for shared BOQ
  detail patterns (cards, stripes, badges, tabs). Make & Vendor, Labour, and
  Review must follow Analysis when adding or changing shared chrome.
- **One export** (`GET /boqs/<id>/export/?kind=review|boq` — both return the same
  file): ``{uploaded_boq}_result.xlsx`` with two tabs:
  - **Review** — client Output format columns (one row per product). Red template
    headers stay red. **Ser no of BOQ** uses each row's S.No exactly as the
    uploaded BOQ sheet (``1.1`` on section rows, ``a)`` / ``b)`` on Unit/Qty
    rows). Shared serials use ``1.7(A)``, ``1.7(B)``. Blank spacer rows follow
    gaps in the original workbook row numbers. Structural section rows do **not**
    copy the first child's quantity.
  - **Original BOQ** — uploaded layout. Qty is written only on Unit/Qty slot
    rows. **Rate** is an Excel formula to Review **Final Rate** (summed when
    several products share one slot). **Amount** is an Excel formula to Review
    **Amount**. Rate/Amount columns are detected across client header formats
    (`RATE (Rs.)`, `Amount`, etc.).
  - Review Excel formulas: **Net_Material_Rate** (Base × (1 − Discount)),
    **Sub_Total** (Commercial + Accessories + Handling + Wastage),
    **Final_Material_Amount**, **Final Rate**, TOTAL MATERIAL / TOTAL LABOUR /
    **Amount**. Procurement through Wastage and Profit stay as Rate_Master values.
    The BOQ tab Rate/Amount formulas follow those Review cells.
  - Row fills (muted): **green** = amount found, **orange** = zero qty / Rate
    Only, **red** = missing product.
- Download sets status `EXPORTED`.
- Gate: `READY_EXPORT` / `pricing_ready` after Labour → Next.

Poll `GET /boqs/<id>/status/?expect=extract` while `PROCESSING`.

**Output:** `media/extract_json/{boq_name}/boq_analysis.json` plus `BOQ.analysis_data`
JSONField (`phase`: `extracted`).

**Services:**

| Service | Role |
| --- | --- |
| `BOQExtractionService` | AI multi-product extraction from grouped anchor rows (`boq_extraction_fields` / `boq_extraction_slots` / `boq_extraction_groups`; public `normalize_product_fields`) |
| `BOQExtractionDisplayService` | Analysis tab product cards (active UI) |
| `MakeListCategoryMappingService` | Map make-list descriptions → Rate_Master_Output categories |
| `MakeListConstraintService` | Approved-makes filter by category / description |
| `ProductAIMappingService` | After extract: candidate recall + AI product/attribute mapping + confidence (`product_ai_common` / `product_ai_candidates` / `product_ai_apply` mixins) |
| `ProductAttributeEnrichmentService` | Attribute confidence helpers / schema fill utilities |
| `ProductHelperMatchingService` | Match BOQ extract → Product_Helper → Product_ID |
| `MakeVendorSelectionService` | After Analyse: make/vendor pick → Rate_Master_Output by Product_ID → Final_Material_Amount (`make_vendor_display` / `make_vendor_cascade` / `make_vendor_rates` / `make_vendor_common` mixins) |
| `ProductMatchingService` | Chroma recall + structured `Rate_Master_Output` scoring |
| `MakeListConstraintService` | Map BOQ lines to `approved_makes_list`; hard Make filter |
| `BOQLabourService` | Auto/Manual labour charges; unlock Review |
| `BOQReviewDisplayService` | Review/export lines from vendor_selection + labour |
| `BOQPriceCalculationService` | Aggregate line amounts onto original rows; unlock export |
| `BOQExportService` | Combined Excel export: Review + original BOQ tabs (formulas) |
| `BOQAnalysisService` | Orchestrator |
| `boq_row_fields` | Shared description/qty/unit keys + `field_from_map` / `is_filled` / `normalize_text` |
| `utils/attribute_parser.py` | Parse/normalize dynamic `Attribute` key-value text |

**Input:** `boq_data.json` → `rows_tree` (`fields` per row).

**Decisions (2026-07-13):**

| Topic | Decision |
| --- | --- |
| Products per BOQ row | **Multiple** — one row may yield several extracted products |
| Make list constraint | **Hard filter** when a make-list material maps to the row |
| Section rows | **Skip matching** (context only) when depth 0 / no qty |
| Attribute keys | **Learn aliases from DB** over time; normalize `Attribute` text in code |
| Matching | **Structured product match** on `Rate_Master_Output` columns + attributes, not vector/text alone |

**Make list:** column roles are inferred from headers **and** cell content (not a
fixed name list). Material/description may be labeled Material, Description,
Item, etc.; makes may be Make, Name, Make/Manufacturers Name, Brand, etc.
Approved makes are split on `/`, `,`, `;`, or `|` into `approved_makes_list`
(spaces inside a token are kept, e.g. `ESS ESS`). Resolved roles are stored as
`column_roles` and rebuilt on load when missing.

**Make-list → category mapping:** each make-list description is mapped onto
Rate_Master_Output taxonomy by **AI understanding** of the free text
(``map_make_list_categories``), not fixed phrase lists. Output stores
``mapped_targets`` (one or more ``{category, sub_category}``) plus primary
``mapped_category`` / ``mapped_sub_category`` for compatibility. Compound lines
can assign multiple categories/subs (e.g. sprinklers **and** rosette plates).
Null ``sub_category`` means approved makes apply to the whole category.
Heuristics / synonym expand are soft hints only. Make List UI shows joined
Category / Subcategory display strings. ``category_mapping_version`` (v11)
triggers a full remap when rules change. Only **pending** stubs (written when
the Rate_Master_Output taxonomy was empty) are remapped for incompleteness; a
material recorded as `unmapped` matched no category and is a final answer for
that version — otherwise every BOQ open would re-run the AI pass. Analysis make
dropdown and Match hard-filter prefer approved makes for the product's category
(`MakeListConstraintService.approved_makes_for_category`), including multi-target
and category-wide null-sub rows.

**Matching layer (three passes):**

1. **Retrieval** — Chroma narrows candidates from description (recall).
2. **Structured scoring** — rank by Category, Sub_Category, Class, Size, Unit, Make,
   and parsed Attribute key-value overlap (precision).
3. **Make list filter** — drop candidates whose `Make` is not in `approved_makes_list`
   when the row maps to a make-list material.

Confidence &lt; 30% → pending product, no auto selection. Analyse uses AI
to validate product/attribute mapping for expert review, plus structured
scoring and Rate_Master candidate recall. Make-list approved-make filters
apply on Make & Vendor, not as a separate Match job.

### BOQ analysis phase 2 — enrichment, confirmation, export

```text
matched products → rate + labour lookup → line output → Excel export
```

**After phase 1 matching:**

1. `RateDetailRetrievalService` — read precomputed `Rate_Master_Output` values for selected product.
2. `LabourDetailRetrievalService` — link labour via `Product_ID` (size-aware when possible).
3. `BOQLineOutputService` — qty × per-unit material/labour from master DB (no formula
   recalculation).
4. `BOQExtractionDisplayService` — shapes extracted products for the **Analysis** tab.

**Expert confirmation (Analysis tab):**

- Experts **Select** a top candidate or **Confirm Manually** (locks match % at 100%).
- **Re-analyse with AI** rematches from the expert’s inputs and BOQ section.
- Those edits persist in `analysis_data` (PostgreSQL), not in the browser session.

**Labour charges:** `LabourDetailRetrievalService` links `Product_ID` →
`Labour_master_Output` (size-aware when multiple rows share a key). Per-unit
labour prefers **`Labour_With_State_Multiplier`** (model
`Total_Labour_per_unit_with_labour_Multipler`), then `Total_Labour_Per_Unit`,
then `Labour_Rate_Per_unit`.
Component breakdown (testing, scaffolding, consumables, painting, buffer) is exposed for export.

**Export:** After Labour → Next (`READY_EXPORT`), Review tab **Export** downloads
one workbook (`{upload}_result.xlsx`) via `BOQExportService`:

- **Review** tab — Output format columns (one row per product).
- **BOQ** tab — original layout; Rate = Review Final material + Labour; Amount =
  Review Amount (Excel formulas). Muted green / orange / red row fills.

Successful download sets `EXPORTED`.

## Business Rules (stable)

- **No recalculation** of client workbook formulas — read precomputed values from
  `Rate_Master_Output` / `Labour_master_Output` when the pipeline returns.
- **Confidence below 30%** → no auto product selection; user must pick a candidate (Select) or Confirm on Analysis.
- **AI** may understand descriptions, extract products, validate matches.
  AI must **not** calculate costs, profits, select vendors, or set pricing.
  Labour/installation activities are **not** extracted on Analysis — labour comes
  from Labour_master_Output (or Manual %) on the Labour tab after Make & Vendor confirms
  Product_ID.
- Do **not** use deprecated `match_key` / `source_key` for matching or imports.
- Use **`Product_ID`** for labour linkage (one labour row per product). Multiple
  Make/Vendor prices share the same `Product_ID` as separate `Rate_Master_Output`
  rows (`Rate_ID`).

---

## Architecture

```text
Browser → Django (templates + Alpine/fetch) → Services → PostgreSQL
                                      ↘ AI (OpenAI) + Chroma (embeddings)
```

| Layer | Location | Responsibility |
| --- | --- | --- |
| Views | `apps/*/views.py` | HTTP, forms, redirects — **no business logic** |
| Services | `apps/*/services/` | All business logic |
| Models | `apps/*/models.py` | Data shape only |
| Templates | `templates/` | Presentation only |
| AI | `backend/ai/` | Prompts, context, embeddings |
| Shared Django | `backend/common/` | Choices, exceptions, middleware, mixins |
| Helpers | `backend/utils/` | Excel, text, files, IST timestamps — no Django models |

Celery + Redis are configured; BOQ analysis runs via `apps/boq/tasks.py`
(`process_boq_extraction_task`). Worker concurrency defaults to 8 parallel
analyses (`CELERY_WORKER_CONCURRENCY`).

---

## Code Structure

```text
BOQ_AI/
├── backend/
│   ├── config/           # settings, urls, celery, wsgi, gunicorn.conf.py
│   ├── apps/
│   │   ├── accounts/     # auth, sessions
│   │   ├── users/        # user CRUD
│   │   ├── database_manager/  # master DB import, versioning
│   │   ├── boq/          # BOQ upload, Analyse, Make & Vendor, Labour, Review, Export
│   │   ├── dashboard/
│   │   ├── notifications/
│   │   └── audit/
│   ├── ai/               # OpenAI client + Chroma embeddings
│   ├── common/           # choices, constants, exceptions, middleware, mixins
│   ├── utils/            # excel, text, files
├── tests/                # Django test suite (repo root)
├── templates/
├── static/
├── media/                # uploads, chroma index (gitignored)
├── docs/
├── requirements.txt
└── .env
```

**Removed (2026-07-10):** `workflows/`, `tasks/`, `exports/`, `ai/extractors/`, and Django apps
`processing`, `matching`, `costing`, `review`, `exports`, `make_list`, `pending_products`.

---

## Key Files

| Path | Purpose |
| --- | --- |
| `apps/database_manager/services/importer.py` | Master DB import |
| `apps/database_manager/services/activation.py` | Single active upload |
| `apps/database_manager/views.py` | DB upload UI |
| `apps/boq/services/boq_service.py` | BOQ file persistence |
| `apps/boq/services/xls_upload_conversion_service.py` | Convert legacy `.xls` → `.xlsx` on upload |
| `utils/xls_convert.py` | xlrd → openpyxl workbook conversion |
| `apps/boq/services/boq_row_fields.py` | Shared BOQ field keys and tiny value helpers |
| `apps/boq/services/boq_analysis_service.py` | Analysis orchestrator |
| `apps/boq/services/rate_detail_retrieval_service.py` | Rate_Master_Output snapshot by id |
| `apps/boq/services/labour_detail_retrieval_service.py` | Labour_master_Output by Product_ID |
| `apps/boq/services/product_helper_matching_service.py` | Product_Helper → Product_ID |
| `apps/boq/services/boq_extraction_service.py` | Extraction facade (`extract` / `extract_anchor`) |
| `apps/boq/services/boq_extraction_fields.py` | `normalize_product_fields` + quantity display/rehydrate |
| `apps/boq/services/boq_extraction_slots.py` | Slot evidence + section attribute fill |
| `apps/boq/services/boq_extraction_groups.py` | Anchor grouping / batch packing / skip |
| `apps/boq/services/product_ai_mapping_service.py` | Product AI mapping facade (Analyse / rematch) |
| `apps/boq/services/product_ai_common.py` | Shared Product AI constants and helpers |
| `apps/boq/services/product_ai_candidates.py` | Candidate recall / seed mixin |
| `apps/boq/services/product_ai_apply.py` | AI batch apply + confidence finalize mixin |
| `apps/boq/services/make_vendor_selection_service.py` | Make/Vendor facade (views call this) |
| `apps/boq/services/make_vendor_display.py` | Make & Vendor tab line/product shaping |
| `apps/boq/services/make_vendor_cascade.py` | Cascade Apply / lowest defaults / catalog |
| `apps/boq/services/make_vendor_rates.py` | Rate_Master options + exact match |
| `apps/boq/services/make_vendor_common.py` | Shared Make & Vendor helpers |
| `apps/boq/services/boq_labour_service.py` | Labour Auto/Manual + complete → Review |
| `apps/boq/services/boq_review_display_service.py` | Review/export from vendor_selection |
| `apps/boq/services/boq_price_calculation_service.py` | Labour → Next row pricing / ready to export |
| `apps/boq/services/boq_export_service.py` | Combined Excel export (Review + BOQ tabs) |
| `ai/openai_client.py` | OpenAI client + API key check |
| `ai/embeddings/` | Chroma product index |
| `config/settings.py` | Single settings module |

---

## Development Rules

**Do:**

- Small, isolated changes; logic in services.
- Update `docs/SESSION_STATE.md` and `docs/CHANGELOG.md` each session.
- Update `docs/PRODUCT.md` when scope/structure changes; `docs/DATABASE.md` when
  models change; `docs/OPS.md` when run/deploy steps change.

**Do not:**

- Put business logic in views or templates.
- Call OpenAI from views.
- Modify the database outside services/migrations.
- Commit secrets, `.env`, logs, or `media/` uploads.

**Tests:** `cd backend && ../.venv/Scripts/python manage.py test tests`

---

## Runtime

- Settings: `config.settings` (PostgreSQL only in production). `DEBUG=False`
  requires a strong `SECRET_KEY`, `DATABASE_URL`, explicit `ALLOWED_HOSTS`, and
  Celery (not eager). CSRF origins follow `CSRF_TRUSTED_ORIGINS` or `ALLOWED_HOSTS`.
  Gunicorn config: `backend/config/gunicorn.conf.py`.
- **Timezone:** `TIME_ZONE = Asia/Kolkata` (IST). UI, logs, JSON ISO
  timestamps, and Celery use IST. PostgreSQL still stores UTC (`USE_TZ=True`);
  display/serialization converts via `utils.timestamps` / Django localtime.
- Local `.env` at project root; production `/srv/boq_ai/.env`.
- OpenAI default chat model: `gpt-4o-mini` (temperature 0 + seed 42 for stable
  Analyse). Extract/match prompts stay compact for that model; candidates are
  sorted by confidence then id before AI so the same BOQ tends to pick the same
  Product_ID.
- Embeddings: `text-embedding-3-small` → Chroma at `media/chroma`.
- **Go live:** `docs/OPS.md` section **Go live on EC2** (packages → `.env` →
  migrate → systemd → Nginx → Superadmin → **upload master database**).
  Subsequent `git pull` steps are under **Subsequent deploys**.
