# BOQ_AI — Product & Technical Reference

Single source of truth for what the system does, how it is built, and the rules
agents and developers must follow. Update this file when product scope, structure,
or architecture changes.

---

## Overview

BOQ_AI is an AI-assisted BOQ estimation platform for Fire Protection and MEP
work. It imports a client master workbook, stores uploaded BOQ files, and will
rebuild processing (matching, review, export) on a fresh design.

**Current scope (2026-07-10):**

| Feature | Status |
| --- | --- |
| User auth, roles, dashboard | Active |
| Master database upload / history / embeddings | Active |
| Product embeddings (Chroma) after DB import | Active |
| BOQ workbook + make-list upload | Active |
| BOQ parsing, processing, matching, review, export | Phase 1–2 active (analysis, review, export); pending-products flow pending |

**Planned BOQ pipeline (not implemented):** parse workbook → AI extraction →
product matching → rate/labour retrieval → expert review → Excel export.

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
Upload workbook → Validate → Import sheets → Activate version → Generate embeddings
```

- Runs **synchronously** in the upload request (no Celery).
- Only `Rate_Master` is required; other master sheets are optional if absent.
- Exactly **one** active `DatabaseVersion` at a time; Chroma holds embeddings for
  the active database only.
- Last **10** uploads remain visible for view/download (metadata + workbook file).
- Master sheet rows are stored in PostgreSQL only for the **active** upload.
- No rollback — new upload replaces the active database.
- Embeddings skip cleanly when OpenAI is not configured.

Entry point: `DatabaseImportService` in `apps/database_manager/services/importer.py`.
Views call the service directly (thin views).

### BOQ upload

```text
Upload BOQ (+ optional make list) → parse to JSON → store files + hierarchy
```

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
  Rate_Master row for each product’s category/sub-category across **all** makes.
- **Make list uploaded:** cascade approved makes come only from the make list for
  that scope — if none map, UI shows “No Approved Make Found in Make List”
  (no fallback to all makes). Cascade: Category required; Sub-category optional
  (blank = entire category).
- Make-list ↔ Rate_Master make comparison uses optimal matching (normalize,
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
  passed to AI. Extract batches are also packed by payload size so huge sections are
  not dropped in one OpenAI call. Amounts still come only from filled Unit/Qty cells
  inside each section (``0`` kept as 0; ``Rate Only`` keeps that marker and copies
  BOQ ``boq_rate``).
- Hierarchy also nests Operating Temp / roman-numeral continuation lines under the
  nearest lettered product, supports indent fallback when serials are sparse, and
  merges multi-sheet workbooks that look like BOQ tables (`sheets` on payload;
  sheet-prefixed `row_id` only when more than one sheet is merged).
- Empty / unrecognizable parses **fail the upload** (no silent empty JSON).
- Normalized JSON is also written to `media/extract_json/{boq_name}/` as
  `boq_data.json` and `make_list_data.json` for downstream AI analysis.
- View page shows **BOQ** and **Make List** tabs with indented sheet layout.
- Attribute value synonyms (e.g. MS→mild steel, DI→ductile iron) are applied during
  Analyse attribute comparison via `utils/attribute_parser.py`.

Entry point: `BOQCreationService` in `apps/boq/services/boq_service.py`.

### BOQ analysis — pipeline

```text
Step 1 — Analyse:       rows → AI extract products only → attributes (Analysis tab)
Step 2 — Make & Vendor: select Make + Supplier → exact Rate_Master + Tech_Key
Step 3 — Labour:        Auto (Labour_Master by Tech_Key) or Manual (% of material by category)
Step 4 — Review:        (material + labour) × quantity → Export Excel
```

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

**Step 1 — Analyse** (BOQ detail → **Analysis** tab):

- Extracts **products only** (no labour/installation activities). Labour charges
  come later from Labour_Master by Tech_Key on the Labour tab.
- Button: **Analyse BOQ** (toolbar, first run only) → `POST /boqs/<id>/extract/`
  via `dispatch_boq_extraction`. Full-BOQ re-analyse is not offered in the toolbar;
  use per-row **Re-analyse**.
- Per-row: **Re-analyse** (Analysis tab) → `POST /boqs/<id>/rows/<row_id>/extract/`
  (`BOQAnalysisService.rematch_row`) rematches existing products against Rate_Master
  using current fields + filled attributes (does not wipe expert edits). Falls back
  to `re_extract_row` only when the row has no products yet.
- Celery task: `boq.process_extraction` (full BOQ only)
- Status: `PROCESSING` → `EXTRACTED`
- Flow per product:
  1. AI extract product fields/attributes from the BOQ line (always includes
     `category` + `sub_category` from BOQ meaning; DB context lists
     **categories and sub-categories** (`sub_categories_by_category`) so AI maps onto
     existing Rate_Master labels; values are snapped to DB labels after extract)
  2. After DB candidate mapping, **category / sub_category are aligned** to the matched
     or suggested Rate_Master row so Make & Vendor uses the same taxonomy as the DB
     product (e.g. ACCESSORIES / Air Cushion Tank instead of a looser AI label like TANK)
  3. Retrieve Rate_Master candidates (Chroma + structured/SQL) with important
     columns + Attribute schema/values — never invent catalog rows or Tech_Key
  4. **AI mapping layer** (`ProductAIMappingService`) selects a candidate only when
     blended confidence ≥ 30%; otherwise status is `provisional` (schema for
     gap-fill, no confirmed `db_product_id` / Tech_Key) or `unmatched`
  5. **Automatic rematch** (same path as Re-analyse): after first mapping, every
     product is rematched with wider recall (taxonomy/schema aligned), then weak
     matches (unmatched / provisional / confidence < 70) get up to 2 more refine
     passes so initial Analyse approaches repeated Re-analyse accuracy
  6. Missing DB Attribute keys are listed for expert fill; filling raises attribute
     confidence; **Re-analyse** rematches with those attributes
  7. Experts can **Select** any top database candidate to confirm that Rate_Master
     product (override AI pick)
- Analysis UI shows matched / suggested / unmatched status, top candidates
  (selectable), confidence badge, and DB attribute fields (empty when missing). Experts add
  more attributes with **+** beside the Attributes heading (no separate
  Additional Attributes section).
- **Multi-product review:** when a group has more extracted products than rows
  with Unit/Qty filled (e.g. 1 qty row → 2 products, or n qty rows → n+1 products),
  the card is flagged **Multi-product review** for expert check. Section-only
  header rows are hidden (products live with the Unit/Qty groups).
- Attribute / match confidence badge colors: ≥80 green, >70 yellow, >50 orange,
  else red
- Analysis confidence is **product-only** (category, sub-category, class, size,
  unit, capacity, attributes). Make / vendor / brand fields are excluded from the
  score, Chroma query, and AI mapping payload — Make & Vendor owns vendor selection.
- **Interactive review:** all product fields (class, size, capacity, unit, etc.) are
  optional — products differ in which properties apply. Users can edit filled fields.
  Saves via `POST /boqs/<id>/extraction/edit/`
  (`BOQExtractionEditService`). Edits persist in `analysis_data` before Make & Vendor.
- **Unit vs quantity_unit:** product ``unit`` is the Rate_Master measurement unit
  (mm, cm, NB, inch, …) used for matching; BOQ row UOM (Each, Nos, Mtr) maps to
  ``quantity`` / ``quantity_unit`` only — never into product ``unit``.
  Quantity comes from filled Unit/Qty cells inside the lineage section
  (including ``0`` and ``Rate Only``); for Rate Only the BOQ rate cell is stored
  as ``boq_rate``. When several children have qty, each product gets its own.
- **Class vs material:** product ``class`` maps to Rate_Master ``Class`` (often
  material: MS, SS, CI, GI, …). Material from BOQ goes into ``class``, not
  free-text attribute keys.

**Step 2 — Make & Vendor** (BOQ detail → **Make & Vendor** tab, after Analyse):

- From Analysis, toolbar **Next** (blue) prefills every product with the
  **lowest-price** Rate_Master row for its category / sub-category (among
  **approved makes** when a make list exists; among **all makes** when none was
  uploaded), then opens **Make & Vendor** and sets status `MAKE_VENDOR`.
- After full Analyse completes, the page **stays on Analysis** (review first;
  use Next to continue).
- Enabled when `analysis_data.rows` exist and Make & Vendor defaults have been
  applied (`MAKE_VENDOR` / later pipeline statuses).
- For each analysed product, expert selects **Make** and/or **Supplier** from options
  (make-list approved makes when present; otherwise Rate_Master makes for the
  product category/spec).
- When the make list has **no approved make** for a product's category/sub-category
  (**Not found**), Make and Supplier become free-text inputs so the expert can type
  values and run **Find rates** against Rate_Master. The cascade panel also accepts
  typed make/supplier for that scope. After a manual entry, the product leaves the
  not-found summary bucket (counts as filtered/manual). Free-text fields stay
  editable so make/supplier can be changed and Find rates re-run (also for
  **No match**).
- **Sub-category makes:** top panel lists **category → sub-category → make → supplier**
  (only categories/sub-categories present in Analysis extraction). **Apply to sub-category**
  sets make/supplier on every product in that sub-category and loads rates. Default make is
  **Lowest price** (approved-make constrained when a make list exists). Empty supplier also
  picks the lowest-priced Rate_Master row for the chosen make. Applied filters list
  shows manual cascade applies.
- Selection persisted per product as `selected_make`, `selected_supplier`, `vendor_selection`;
  sub-category choices stored in `analysis_data.subcategory_make_selections`.
- AI does not choose make/supplier or calculate prices — rates are read from the master DB.
- Make & Vendor UI shows **material rate only** (labour charges belong on the Labour tab).
- When two or more matched products share the **same material rate** but use
  **different make/supplier** pairs, those cards are highlighted for **supplier
  review/confirmation** (summary count included).
- Toolbar **Next** (on Make & Vendor) unlocks **Labour** (Match rematch is retired from the UI).
- **Client approach (experimental):** full narrative, business rules, demo script, and
  decision checklist for stakeholder review — [`docs/MAKE_VENDOR_APPROACH.md`](MAKE_VENDOR_APPROACH.md).

**Step 3 — Labour** (Labour tab, after Make & Vendor → Next):

- Status `LABOUR`. Tech_Key comes from Make & Vendor `vendor_selection` (exact product).
- **Auto:** for each product, load Labour_Master by Tech_Key and fill labour rate/amount
  (`BOQLabourService.apply_auto` → `LabourDetailRetrievalService`).
- **Manual:** enter a percentage per extraction category; labour =
  material × (percent / 100) for every product in that category
  (`BOQLabourService.apply_manual`).
- Line pricing: **(material + labour) × quantity** after Labour → Next
  (`BOQPriceCalculationService`).
- Persist `analysis_data.labour_config` (`mode`, `category_percentages`, `labour_ready`).
- Toolbar **Next** runs row pricing aggregate and sets `READY_EXPORT`
  (`BOQLabourService.complete` → `BOQPriceCalculationService`).
- **Client progress report:** [`docs/LABOUR_CLIENT_REPORT.md`](LABOUR_CLIENT_REPORT.md)
  (capabilities, UX delivered, demo script, confirmation checklist).

**Step 4 — Review + Export** (Review tab):

- Shows product details from Make & Vendor + Labour (`BOQReviewDisplayService`),
  not fuzzy Match `product_matches`.
- **Export Excel** (`GET /boqs/<id>/export/`) writes the original BOQ sheet columns
  plus a **Charge Breakdown** sheet; sets status `EXPORTED`.
- Gate: `READY_EXPORT` / `pricing_ready` after Labour → Next.

Poll `GET /boqs/<id>/status/?expect=extract` while `PROCESSING`.

**Output:** `media/extract_json/{boq_name}/boq_analysis.json` plus `BOQ.analysis_data`
JSONField (`phase`: `extracted` | `matched`). After matching, a dedicated
`boq_match_results.json` in the same folder stores full `product_matches` snapshots
(candidates, scores, rate/labour enrichment) for internal tracking even when the
live analysis is edited before re-match.

**Services:**

| Service | Role |
| --- | --- |
| `BOQExtractionService` | AI multi-product extraction from grouped anchor rows (full lineage text) |
| `MakeListCategoryMappingService` | Map make-list descriptions → Rate_Master categories |
| `MakeListConstraintService` | Approved-makes filter by category / description |
| `ProductAIMappingService` | After extract: candidate recall + AI product/attribute mapping + confidence |
| `ProductAttributeEnrichmentService` | Attribute confidence helpers / schema fill utilities |
| `MakeVendorSelectionService` | After Analyse: make/supplier pick → exact Rate_Master → rates by Tech_Key |
| `ProductMatchingService` | Chroma recall + structured `Rate_Master` scoring |
| `MakeListConstraintService` | Map BOQ lines to `approved_makes_list`; hard Make filter |
| `BOQLabourService` | Auto/Manual labour charges; unlock Review |
| `BOQReviewDisplayService` | Review/export lines from vendor_selection + labour |
| `BOQPriceCalculationService` | Aggregate line amounts onto original rows; unlock export |
| `BOQExportService` | Excel export (original BOQ format + breakdown) |
| `BOQAnalysisService` | Orchestrator |
| `utils/attribute_parser.py` | Parse/normalize dynamic `Attribute` key-value text |

**Input:** `boq_data.json` → `rows_tree` (`fields` per row).

**Decisions (2026-07-13):**

| Topic | Decision |
| --- | --- |
| Products per BOQ row | **Multiple** — one row may yield several extracted products |
| Make list constraint | **Hard filter** when a make-list material maps to the row |
| Section rows | **Skip matching** (context only) when depth 0 / no qty |
| Attribute keys | **Learn aliases from DB** over time; normalize `Attribute` text in code |
| Matching | **Structured product match** on `Rate_Master` columns + attributes, not vector/text alone |

**Make list:** column roles are inferred from headers **and** cell content (not a
fixed name list). Material/description may be labeled Material, Description,
Item, etc.; makes may be Make, Name, Make/Manufacturers Name, Brand, etc.
Approved makes are split on `/`, `,`, `;`, or `|` into `approved_makes_list`
(spaces inside a token are kept, e.g. `ESS ESS`). Resolved roles are stored as
`column_roles` and rebuilt on load when missing.

**Make-list → category mapping:** each make-list description (free text / synonym)
is mapped onto Rate_Master ``Category`` and ``Sub_Category`` (heuristic + AI
``map_make_list_categories`` using the full taxonomy). Stored as ``category_mappings``
on `make_list_data` and shown as separate **Mapped Category** and **Mapped Sub-category**
columns on the Make List tab. Analysis make dropdown and Match hard-filter prefer approved makes for the
product's category (`MakeListConstraintService.approved_makes_for_category`).

**Matching layer (three passes):**

1. **Retrieval** — Chroma narrows candidates from description (recall).
2. **Structured scoring** — rank by Category, Sub_Category, Class, Size, Unit, Make,
   and parsed Attribute key-value overlap (precision).
3. **Make list filter** — drop candidates whose `Make` is not in `approved_makes_list`
   when the row maps to a make-list material.

Confidence &lt; 30% → pending product, no auto selection on **Match**. Analyse uses AI
to validate product/attribute mapping for expert review; Match still applies
structured scoring, make-list filters, and rate/labour enrichment.

### BOQ analysis phase 2 — enrichment, confirmation, export

```text
matched products → rate + labour lookup → line output → session confirm → Excel export
```

**After phase 1 matching:**

1. `RateDetailRetrievalService` — read precomputed `Rate_Master` values for selected product.
2. `LabourDetailRetrievalService` — link labour via `Tech_Key` (size-aware when possible).
3. `BOQLineOutputService` — qty × per-unit material/labour from master DB (no formula
   recalculation).
4. `BOQAnalysisDisplayService` — shapes rows for the **Analysis** tab.

**Expert confirmation (session only):**

- Any logged-in user with access to the BOQ can **Confirm** lines on the Analysis tab.
- Confirmations are stored in the **user session only** — not written to PostgreSQL.
- Pending lines require picking a candidate product before confirm; matched lines confirm the auto-selection.
- Re-running analysis does not clear session confirmations (user may undo per line).

**Labour charges:** `LabourDetailRetrievalService` links `Rate_Master.Tech_Key` → `Labour_Master`
rows (size-aware when multiple rows share a key). Per-unit labour uses precomputed workbook columns:
`Total_Labour_per_unit_with_labour_Multipler` → `Total_Labour_per_Unit` → `Labour_Rate_Per_unit`.
Component breakdown (testing, scaffolding, consumables, painting, buffer) is exposed for export.

**Export:** After Labour → Next (`READY_EXPORT`), `BOQExportService` → Excel
download with two sheets: **BOQ** (original upload layout with rate/amount filled
only on rows that already have quantity; top/left aligned, wrapped text, dark
borders; blank row after each section) and **Charge Breakdown** (detailed
material/labour lines). Successful download sets `EXPORTED`.

## Business Rules (stable)

- **No recalculation** of client workbook formulas — read precomputed values from
  `Rate_Master` / `Labour_Master` when the pipeline returns.
- **Session confirmation** on the Analysis tab before export (not stored in PostgreSQL).
- **Confidence below 30%** → no auto product selection; user must pick a candidate and confirm.
- **AI** may understand descriptions, extract products, validate matches.
  AI must **not** calculate costs, profits, select suppliers, or set pricing.
  Labour/installation activities are **not** extracted on Analysis — labour comes
  from Labour_Master (or Manual %) on the Labour tab after Make & Vendor confirms
  Tech_Key.
- Do **not** use deprecated `match_key` / `source_key` for matching or imports.
- Use **`Tech_Key`** for labour linkage; it is indexed but not globally unique
  (multi-supplier variants).

---

## Architecture

```text
Browser → Django (templates + HTMX) → Services → PostgreSQL
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
(`process_boq_analysis_task`).

---

## Code Structure

```text
BOQ_AI/
├── backend/
│   ├── config/           # settings, urls, celery, wsgi
│   ├── apps/
│   │   ├── accounts/     # auth, sessions
│   │   ├── users/        # user CRUD
│   │   ├── database_manager/  # master DB import, versioning
│   │   ├── boq/          # BOQ upload only
│   │   ├── dashboard/
│   │   ├── notifications/
│   │   └── audit/
│   ├── ai/               # OpenAI client + Chroma embeddings
│   ├── common/           # choices, constants, exceptions, middleware, mixins
│   ├── utils/            # excel, text, files
│   └── tests/
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
| `apps/boq/services/boq_analysis_service.py` | Analysis orchestrator |
| `apps/boq/services/rate_detail_retrieval_service.py` | Rate_Master snapshot by id |
| `apps/boq/services/labour_detail_retrieval_service.py` | Labour_Master by Tech_Key |
| `apps/boq/services/boq_labour_service.py` | Labour Auto/Manual + complete → Review |
| `apps/boq/services/boq_review_display_service.py` | Review/export from vendor_selection |
| `apps/boq/services/boq_price_calculation_service.py` | Labour → Next row pricing / ready to export |
| `apps/boq/services/boq_export_service.py` | Excel export |
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

- Settings: `config.settings` (PostgreSQL only in production).
- **Timezone:** `TIME_ZONE = Asia/Kolkata` (IST). UI, logs, JSON ISO
  timestamps, and Celery use IST. PostgreSQL still stores UTC (`USE_TZ=True`);
  display/serialization converts via `utils.timestamps` / Django localtime.
- Local `.env` at project root; production `/srv/boq_ai/.env`.
- OpenAI default chat model: `gpt-4o-mini` (temperature 0 for deterministic extraction).
- Embeddings: `text-embedding-3-small` → Chroma at `media/chroma`.
- See `docs/OPS.md` for setup and deployment commands.
