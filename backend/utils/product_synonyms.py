"""Shared synonym helpers for Analysis matching and Make List mapping.

Covers materials (DI ↔ ductile iron), product phrases (NRV ↔ non return valve),
and make-list category/sub-category phrase hints.
"""
from __future__ import annotations

import re
from collections.abc import Collection, Mapping
from typing import Any

# ---------------------------------------------------------------------------
# Material / Class abbreviations → canonical short code (lowercase)
# ---------------------------------------------------------------------------
_MATERIAL_CANONICAL: dict[str, str] = {
    "ms": "ms",
    "m.s": "ms",
    "m.s.": "ms",
    "m s": "ms",
    "mild steel": "ms",
    "ms sheet": "ms sheet",
    "ss": "ss",
    "s.s": "ss",
    "s.s.": "ss",
    "s s": "ss",
    "stainless": "ss",
    "stainless steel": "ss",
    "ci": "ci",
    "c.i": "ci",
    "c.i.": "ci",
    "c i": "ci",
    "cast iron": "ci",
    "di": "di",
    "d.i": "di",
    "d.i.": "di",
    "d i": "di",
    "ductile iron": "di",
    "ductile": "di",
    "gi": "gi",
    "g.i": "gi",
    "g.i.": "gi",
    "g i": "gi",
    "galvanised iron": "gi",
    "galvanized iron": "gi",
    "galvanised": "gi",
    "galvanized": "gi",
    "cs": "cs",
    "c.s": "cs",
    "c.s.": "cs",
    "carbon steel": "cs",
    "brass": "brass",
    "grp": "grp",
    "rubber": "rubber",
    "forged steel": "forged steel",
    "upvc": "upvc",
    "u pvc": "upvc",
    "cpvc": "cpvc",
    "c pvc": "cpvc",
    "hdpe": "hdpe",
    "pvc": "pvc",
}

_CANONICAL_DISPLAY: dict[str, str] = {
    "ms": "MS",
    "ms sheet": "MS Sheet",
    "ss": "SS",
    "ci": "CI",
    "di": "DI",
    "gi": "GI",
    "cs": "CS",
    "brass": "Brass",
    "grp": "GRP",
    "rubber": "Rubber",
    "forged steel": "Forged Steel",
    "upvc": "UPVC",
    "cpvc": "CPVC",
    "hdpe": "HDPE",
    "pvc": "PVC",
}

_CANONICAL_QUERY_EXPANSIONS: dict[str, tuple[str, ...]] = {
    "ms": ("MS", "mild steel", "M.S."),
    "ss": ("SS", "stainless steel", "S.S."),
    "ci": ("CI", "cast iron", "C.I."),
    "di": ("DI", "ductile iron", "D.I."),
    "gi": ("GI", "galvanised iron", "galvanized iron", "G.I."),
    "cs": ("CS", "carbon steel", "C.S."),
    "upvc": ("UPVC", "uPVC", "U-PVC"),
    "cpvc": ("CPVC", "cPVC", "C-PVC"),
    "hdpe": ("HDPE",),
    "pvc": ("PVC",),
}

# Dynamic hint builders replace hardcoded lists
def get_standard_abbreviations() -> dict[str, tuple[str, ...]]:
    base = {
        "non return valve": ("nrv", "check valve", "reflux", "reflux type", "reflex valve", "reflex", "non-return"),
        "sluice valve": ("gate valve", "gv", "sluice"),
        "butterfly valve": ("bfv", "bf valve"),
        "ball valve": ("bv",),
        "air release valve": ("arv", "air release", "air relief"),
        "y strainer": ("y-type", "strainer"),
        "pressure reducing valve": ("prv", "pressure reducing"),
        "galvanized iron": ("gi", "g.i.", "galvanised iron"),
        "mild steel": ("ms", "m.s."),
        "stainless steel": ("ss", "s.s."),
        "cast iron": ("ci", "c.i."),
        "ductile iron": ("di", "d.i."),
        "jockey pump": ("jockey",),
        "diesel fire pump": ("diesel pump",),
        "fire hydrant pump": ("hydrant pump",),
        "fire sprinkler pump": ("sprinkler pump",),
        "pressure gauge": ("pressure indicator",),
        "air cushion tank": ("air cushion", "air vessel"),
        "grp water tank": ("grp tank",),
        "frp water tank": ("frp tank",),
        "abc extinguisher": ("abc",),
        "co2 extinguisher": ("co2",),
        "foam extinguisher": ("foam",),
        "dcp extinguisher": ("dcp",),
    }
    
    bidirectional = {}
    for key, syns in base.items():
        all_terms = (key,) + syns
        for term in all_terms:
            bidirectional[term] = all_terms
            
    return bidirectional

def get_dynamic_taxonomy_hints(by_category: Mapping[str, Collection[str]]) -> tuple[list[tuple[str, str]], list[tuple[str, str]]]:
    """
    Build category and subcategory extraction phrases from the active taxonomy,
    falling back to standard abbreviations where necessary.
    """
    cat_hints: list[tuple[str, str]] = []
    sub_hints: list[tuple[str, str]] = []
    
    abbrevs = get_standard_abbreviations()
    exclude = {"ms", "gi", "ss", "ci", "di", "pipe", "valve", "pump", "tank", "hose", "system"}

    for cat, subs in by_category.items():
        cat = cat.strip().upper()
        for sub in subs:
            sub_lower = sub.strip().lower()
            if not sub_lower:
                continue
                
            if sub_lower not in exclude and len(sub_lower) > 2:
                cat_hints.append((sub_lower, cat))
                sub_hints.append((sub_lower, sub.strip().upper()))
                
            if cat == "PIPE" and sub_lower in ("gi", "ms", "ci", "di"):
                cat_hints.append((f"{sub_lower} pipe", cat))
                sub_hints.append((f"{sub_lower} pipe", sub.strip().upper()))
                for syn in abbrevs.get(sub_lower, ()):
                    cat_hints.append((f"{syn} pipe", cat))
                    sub_hints.append((f"{syn} pipe", sub.strip().upper()))
                
            for syn in abbrevs.get(sub_lower, ()):
                syn_lower = syn.lower()
                if syn_lower not in exclude and len(syn_lower) > 2:
                    cat_hints.append((syn_lower, cat))
                    sub_hints.append((syn_lower, sub.strip().upper()))
                    
    cat_hints.extend([
        ("pipework", "PIPE"), ("piping", "PIPE"), ("dia pipe", "PIPE"),
        ("fire hose box", "HYDRANT"), ("external fire hose box", "HYDRANT"),
        ("hose box", "HYDRANT"), ("hose cabinet", "HYDRANT"),
        ("sand bucket set", "HYDRANT"), ("sand buckets", "HYDRANT"), ("sand bucket", "HYDRANT"),
    ])
    sub_hints.extend([
        ("fire hose box", "FIRE HOSE BOX"), ("external fire hose box", "FIRE HOSE BOX"),
        ("hose box", "FIRE HOSE BOX"), ("hose cabinet", "FIRE HOSE BOX"),
        ("sand bucket set", "SAND BUCKET SET"), ("sand buckets", "SAND BUCKET SET"), ("sand bucket", "SAND BUCKET SET"),
    ])

    unique_cat = list(set(cat_hints))
    unique_sub = list(set(sub_hints))
    
    # Priority: PIPE/VALVE > HYDRANT/SPRINKLER (to avoid chapter title noise like "External Hydrant System" overshadowing pipes)
    def _priority(item: tuple[str, str]) -> int:
        cat = item[1]
        if cat in ("PIPE", "VALVE"):
            return 2
        if cat in ("HYDRANT", "SPRINKLER", "FIRE EXTINGUISHER"):
            return 1
        return 0

    unique_cat.sort(key=lambda x: (_priority(x), len(x[0])), reverse=True)
    unique_sub.sort(key=lambda x: (_priority(x), len(x[0])), reverse=True)
    
    return unique_cat, unique_sub



def _normalize_label(value: Any) -> str:
    text = str(value or "").strip().lower()
    text = text.replace("-", " ")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def canonicalize_material_label(value: Any) -> str:
    """Return lowercase canonical material/class code, or normalized text."""
    text = _normalize_label(value)
    if not text:
        return ""
    if text in _MATERIAL_CANONICAL:
        return _MATERIAL_CANONICAL[text]
    compact = text.replace(".", "").replace(" ", "")
    if compact in _MATERIAL_CANONICAL:
        return _MATERIAL_CANONICAL[compact]
    return text


def canonicalize_label(value: Any) -> str:
    """Canonicalize material or product phrase; else normalized text."""
    text = _normalize_label(value)
    if not text:
        return ""
    if text in _MATERIAL_CANONICAL:
        return _MATERIAL_CANONICAL[text]
    compact = text.replace(".", "").replace(" ", "")
    if compact in _MATERIAL_CANONICAL:
        return _MATERIAL_CANONICAL[compact]
    return text


def display_material_label(value: Any) -> str:
    """Map free text onto the Rate_Master-style Class token when known."""
    if not value:
        return ""
    canon = canonicalize_material_label(value)
    if canon in _CANONICAL_DISPLAY:
        return _CANONICAL_DISPLAY[canon]
    return str(value).strip()


def is_known_material_label(value: Any) -> bool:
    """True for DI / ductile iron / MS / … — not for Class tokens like 0 or 9."""
    if not value:
        return False
    return canonicalize_material_label(value) in _CANONICAL_DISPLAY


def labels_equivalent(left: Any, right: Any) -> bool:
    """True when labels mean the same after material + phrase synonym folding."""
    left_text = _normalize_label(left)
    right_text = _normalize_label(right)
    if not left_text or not right_text:
        return False
    if left_text == right_text:
        return True
    left_c = canonicalize_label(left)
    right_c = canonicalize_label(right)
    if left_c and right_c and left_c == right_c:
        return True
    left_terms = {_normalize_label(term) for term in expand_query_terms(left)}
    right_terms = {_normalize_label(term) for term in expand_query_terms(right)}
    return bool(left_terms & right_terms)


def expand_query_terms(value: Any) -> list[str]:
    """Original value plus material/phrase synonym expansions for recall."""
    raw = str(value or "").strip()
    if not raw:
        return []
    terms: list[str] = [raw]
    mat_canon = canonicalize_material_label(raw)
    if mat_canon in _CANONICAL_QUERY_EXPANSIONS:
        for item in _CANONICAL_QUERY_EXPANSIONS[mat_canon]:
            if item not in terms:
                terms.append(item)
    display = display_material_label(raw)
    if display and display not in terms:
        terms.append(display)
    
    # We no longer use _PHRASE_EXPANSIONS. The dynamic abbrevs can be used instead.
    phrase_canon = canonicalize_label(raw)
    abbrevs = get_standard_abbreviations()
    if phrase_canon in abbrevs:
        for item in abbrevs[phrase_canon]:
            if item not in terms:
                terms.append(item)
                
    text = _normalize_label(raw)
    for phrase_key, phrase_items in abbrevs.items():
        if phrase_key in text:
            for item in phrase_items:
                if item not in terms:
                    terms.append(item)
    return terms


def expand_make_list_search_text(description: str) -> str:
    """Build a synonym-expanded search blob for make-list category heuristics.

    Fold material abbreviations (``M.S`` / ``D.I.`` / ``C.I``) and product
    phrases (NRV / hose reel / …) so free-text make-list lines map to taxonomy.
    """
    raw = description or "".strip()
    if not raw:
        return ""
    parts: list[str] = []

    def _add(value: str) -> None:
        text = _normalize_label(value)
        if text and text not in parts:
            parts.append(text)

    _add(raw)
    for term in expand_query_terms(raw):
        _add(term)

    # Strip punctuation so ``M.S`` / ``D.I.`` become ``m s`` / ``d i``.
    folded = re.sub(r"[^0-9a-zA-Z]+", " ", raw.lower())
    folded = re.sub(r"\s+", " ", folded).strip()
    _add(folded)

    for pattern, expansion in (
        (r"\bm\s*s\b", "ms mild steel"),
        (r"\bd\s*i\b", "di ductile iron"),
        (r"\bc\s*i\b", "ci cast iron"),
        (r"\bg\s*i\b", "gi galvanized"),
        (r"\bs\s*s\b", "ss stainless steel"),
    ):
        if re.search(pattern, folded):
            _add(expansion)

    return " ".join(parts)


# ── AI synonym catalog: (Category, Sub_Category) → list of BOQ synonyms ──
# This is the single source of truth for prompt injection. Add new rows here.

# Each catalog entry becomes a phrase group: (sub_category_lower, *synonyms_lower).


def format_synonym_rules_for_ai() -> str:
    """Short meaning-first rules for AI prompts (no product phrase catalog).

    Materials abbreviations stay listed so GI ≈ galvanized iron is explicit.
    snap, SQL) — the model must understand BOQ meaning and map onto
    DATABASE_CONTEXT / candidates, not look up a phrase list.
    """
    lines: list[str] = [
        "Meaning-first rules (do NOT require exact wording):",
        "- Understand the purchasable product from BOQ meaning (owning sentence,",
        "  slot, size/class/capacity). Map onto exact DATABASE_CONTEXT / candidate",
        "  labels. Never invent catalog rows or Product_IDs.",
        "- Treat common MEP material abbreviations as the SAME material, e.g.:",
    ]
    for canon in _CANONICAL_QUERY_EXPANSIONS:
        terms: list[str] = [canon]
        for item in _CANONICAL_QUERY_EXPANSIONS[canon]:
            if item not in terms:
                terms.append(item)
        lines.append(f"    {' = '.join(terms)}")
    lines.extend(
        [
            "- Abbreviations, spelling variants, and industry synonyms must NOT",
            "  lower confidence when the meaning matches (GI pipe = galvanized iron pipe).",
            "- Pipe class phrases map to Rate_Master Class when listed: Heavy Class",
            "  → C, Medium Class → B, Light Class → A (do not invent other classes).",
            "- Valve subtypes are distinct: sluice ≠ butterfly ≠ ball ≠ non-return",
            "  (check / reflux / NRV). Wrong subtype → reject even if both are VALVE.",
            "- Do NOT match by shared words alone. Wrong product family or wrong",
            "  nominal size → reject even if some tokens overlap (e.g. hose reel vs",
            "  hose box; sluice valve vs hydrant chapter title; sluice valve vs PIPE).",
            "- Indian Standard codes (IS:636, IS 903-1975) are NOT nominal size —",
            "  use the mm/dia/NB figure (e.g. 63 mm dia → size 63, is attribute 636).",
            "  If only an IS code is visible and nominal size is unclear, leave size null.",
            "- For every structured field (not only size): prefer null over guessing.",
            "  Do not fill Class, Capacity, make_hint, or attributes from chapter titles,",
            "  qty columns, or unrelated text — only from the owning slot / product_context.",
            "- Size/Unit follow DATABASE_CONTEXT size_unit_patterns: FIRE HOSE uses length",
            "  (m); PIPE/VALVE/branch pipe use nominal mm; never SWG gauge or WxHxD as Size.",
            "- Operating temperature (68 deg.C / °C), k-factor, response, speed, head,",
            "  flow, RPM are attributes — NEVER Size. Size is orifice/bore/dia (e.g. 15 mm).",
            "- When the BOQ states a measure unit next to Size (15 mm, 65 NB), fill Unit.",
            "- Prefer the candidate / taxonomy label that satisfies the BOQ",
            "  requirement, not the one with the most string overlap.",
            "- If no catalog row matches the product family/subtype, select null",
            "  (do not pick a wrong product at high confidence).",
        ]
    )
    return "\n".join(lines)


