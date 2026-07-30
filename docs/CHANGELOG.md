# Changelog

Meaningful product and technical changes. Day-by-day micro-entries older than
the summaries below live in **git history** (`git log -- docs/`).

---

## 2026-07-30

**Docs**
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
