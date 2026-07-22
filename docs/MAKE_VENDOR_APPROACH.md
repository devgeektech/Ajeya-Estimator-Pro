# Make & Vendor Selection — Client Approach (Experimental)

**Status:** Experimental — ready for client review  
**Audience:** Client stakeholders, estimators, technical reviewers  
**Related product docs:** [`PRODUCT.md`](PRODUCT.md) (Step 2), [`CHANGELOG.md`](CHANGELOG.md)

---

## Purpose

This document describes the complete business and technical approach for **Step 2 — Make & Vendor**, built as an experiment on top of Analysis extraction.

**Goal:** Let estimators apply approved make/supplier choices efficiently at **sub-category** level, then load material and labour rates from Rate_Master — without AI choosing vendors or calculating prices.

---

## Where it sits in the workflow

```text
Upload BOQ + Make List
        ↓
Step 1 — Analyse     (extract products; map to Rate_Master taxonomy)
        ↓
Step 2 — Make & Vendor   ← this experiment
        ↓
Step 3 — Match       (full match / review)
        ↓
Export
```

| Step | User action | Outcome |
|------|-------------|---------|
| 1 Analyse | Extract products + map to Rate_Master taxonomy | Each product has `category`, `sub_category`, specs |
| **2 Make & Vendor** | Cascade select make/supplier; apply to sub-category | Rates loaded; selection stored on products |
| 3 Match | Full match / review | Confirm and export |

**Important rule (unchanged):** AI does **not** select make, supplier, or price. Estimators select; the system reads rates from the master database.

---

## Problem this experiment solves

Without bulk selection, estimators must pick make/supplier **product by product**. Client make lists already define **approved makes** by material/category. The experiment introduces:

1. A cascade UI limited to **what Analysis actually found**
2. **One apply** that covers all products in a sub-category
3. **Lowest price** as the default pick among approved makes
4. Make list as the **first source of truth** for allowed makes; vendors/suppliers come from Rate_Master for the chosen make

---

## User experience (what the client will see)

### Top panel — cascade filter

```text
Category → Sub-category → Approved Make → Supplier (optional) → Apply to sub-category
```

1. **Category** — only categories present on extracted products (e.g. PIPE, VALVE, ACCESSORIES).
2. **Sub-category** — only sub-categories present under that category in this BOQ (e.g. MS, Air Cushion Tank).
3. **Approved make** — from the uploaded **make list** for that category/sub-category. Default option: **Lowest price**.
4. **Supplier** — suppliers available in Rate_Master for the selected make (+ category/sub-category filter). Empty / auto = pick lowest-priced Rate_Master row for that make.
5. **Apply to sub-category** — writes make/supplier onto **every analysed product** with that category + sub-category and loads rates.

### Product list (below)

- Each product card shows **Category / Sub-category** clearly (so users can see which bulk apply group the product belongs to).
- Per-product Make / Supplier + **Find rates** remains for overrides after bulk apply.

---

## Business rules (for client agreement)

### 1. Scope of apply

- Selection applies to **all products** sharing the same extracted `category` + `sub_category`.
- Products in other sub-categories are untouched.

### 2. Default pricing behaviour

| User choice | System behaviour |
|-------------|------------------|
| Make = **Lowest price** (default) | Among Rate_Master rows whose **Make** is in the **approved make list**, pick the **lowest** `Final_Amount_Excl_GST` (fallback: `Net_Material_Rate`). Structured match score is the tie-breaker. |
| Make = specific approved make, Supplier empty | Filter Rate_Master to that make; pick **lowest price** among matching product rows (same category/sub-category soft filter). |
| Make + specific Supplier | Filter by make + supplier; pick best structured match (not necessarily cheapest). |

### 3. Source of truth order

1. **Make list approved makes** — hard constraint for which makes are allowed in the cascade and for lowest-price filtering.
2. **Rate_Master** — suppliers listed for the selected make; material/labour rates via Tech_Key after a row is chosen.
3. **Structured product match** — uses Analysis fields (class, size, unit, capacity, attributes) to choose the correct Rate_Master row within the filtered set.

### 4. Taxonomy alignment (prerequisite)

After Analysis maps a product to a DB candidate, **category / sub_category on the product are aligned** to the matched/suggested Rate_Master labels (e.g. AI said `TANK` → aligned to `ACCESSORIES` when the nearest DB product is Accessories / Air Cushion Tank). This prevents Make & Vendor from looking up approved makes under the wrong category.

---

## Data persisted (audit trail)

Stored on the BOQ analysis JSON (`analysis_data`):

- **Per product:** `selected_make`, `selected_supplier`, `vendor_selection` (status, confidence, tech_key, rate/labour, line totals).
- **Bulk choices:** `subcategory_make_selections` keyed by `Category::Sub_category` with make, supplier, prefer_lowest_price, applied_at, product_count.

Rates are **read**, not calculated by AI.

---

## Technical outline (for technical stakeholders)

| Area | Implementation |
|------|----------------|
| UI | `templates/boq/_make_vendor_table.html` — cascade panel + product cards |
| Service | `backend/apps/boq/services/make_vendor_selection_service.py` — catalog, `apply_subcategory_make`, lowest-price match |
| Make list | `backend/apps/boq/services/make_list_constraint_service.py` — approved makes by category/sub-category |
| Endpoint | `POST /boqs/<id>/make-vendor/` — `action=apply_subcategory` or `select_product` |
| Taxonomy snap | `backend/ai/context.py` + `product_ai_mapping_service.py` after DB map |

---

## Demo script for client walkthrough

1. Upload BOQ + make list; run **Analyse**.
2. Confirm products show correct **Category / Sub-category** (aligned to DB where matched).
3. Open **Make & Vendor** via Analysis **Next** (auto-prefills lowest approved make/vendor).
4. Review **Applied filters**; use the cascade to change a sub-category, confirm the
   **Filter ready to apply** summary, then Apply.
5. Show product cards updated with rates.
6. Override one product with a specific make + supplier → Find rates.
7. Proceed to **Match** when ready.

---

## Known limits / open points for client feedback

These should be confirmed before treating the experiment as final product:

1. **Bulk apply is per sub-category**, not full category in one click (cascade requires sub-category). Confirm if “Apply all sub-categories at lowest price” is needed.
2. **Make list must be mapped** to Rate_Master categories/sub-categories; weak mapping → empty approved-make lists.
3. **Lowest price** uses Rate_Master amount fields only; labour is loaded after the row is chosen via Tech_Key — confirm if “lowest” should mean material-only or material+labour total.
4. Per-product override does not automatically update the stored sub-category cascade selection record (products diverge until re-apply).
5. Full Match (Step 3) still has its own pipeline; ensure client understands Step 2 `vendor_selection` vs Step 3 Match Results until they are fully unified for export.

---

## Proposed client decision checklist

- [ ] Approve cascade: Category → Sub-category → Make → Supplier
- [ ] Approve default: Lowest price among approved makes
- [ ] Approve make list as hard filter for makes
- [ ] Approve bulk apply to all products in a sub-category
- [ ] Confirm whether lowest price = material amount only or total with labour
- [ ] Confirm need for “Apply all sub-categories” one-click
- [ ] Confirm when Step 2 selections should drive export (before or after Step 3 Match)

---

## Status

**Experimental / ready for client review.** Implementation exists in the current codebase; treat feedback from this document as the gate before hardening UX, export wiring, and any one-click bulk behaviours.
