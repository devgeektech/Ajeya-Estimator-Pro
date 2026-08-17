"""Shared synonym helpers for Analysis matching and Make List mapping.

Covers materials (DI ↔ ductile iron), product phrases (NRV ↔ non return valve),
and make-list category/sub-category phrase hints.
"""
from __future__ import annotations

import re
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

# Product / taxonomy phrase groups (different words, same meaning).
# First entry is the canonical key used for equivalence.
_PHRASE_GROUPS: tuple[tuple[str, ...], ...] = (
    (
        "non return valve",
        "non-return valve",
        "non return",
        "non-return",
        "nrv",
        "check valve",
        "n r v",
        "reflex valve",
        "reflex",
    ),
    ("sluice valve", "sluice", "gate valve", "gate"),
    ("butterfly valve", "butterfly"),
    ("ball valve", "ball"),
    ("air release valve", "air release", "air relief", "arv"),
    ("pressure reducing valve", "pressure reducing", "prv", "pressure reducer"),
    ("y strainer", "y-type strainer", "y type strainer", "y-strainer", "strainer y"),
    ("foot valve", "foot"),
    ("landing valve", "landing"),
    ("hose reel", "hose reel drum", "first aid hose reel", "first-aid hose reel"),
    (
        "hose box",
        "hose cabinet",
        "hydrant box",
        "fire hose box",
        "fire hose cabinet",
    ),
    (
        "sand bucket set",
        "sand bucket",
        "sand buckets",
        "bucket set",
        "sandbucket",
        "sand bucket with stand",
    ),
    ("branch pipe", "branchpipe", "branch"),
    ("fire brigade inlet", "fire brigade", "breeching inlet", "collective inlet"),
    ("flow switch", "flow indicator", "flow indicator switch", "water flow switch"),
    ("alarm valve", "installation control valve", "installation control", "icv"),
    ("inspector test", "inspecting test", "test and drain", "inspector's test"),
    ("flexible drop", "sprinkler flexible", "flexible connector", "flexible pipe", "flex drop"),
    ("jockey pump", "jockey"),
    ("diesel pump", "diesel engine pump", "diesel driven pump"),
    ("hydrant pump", "main hydrant pump"),
    ("sprinkler pump", "main sprinkler pump"),
    ("pressure gauge", "pressure gauges", "pg"),
    ("pressure switch", "pressure switches"),
    ("air cushion tank", "air cushion", "air vessel", "pressure vessel"),
    ("extinguisher", "fire extinguisher", "fire extinguishers"),
    ("abc", "abc powder", "dry chemical", "dcp"),
    ("co2", "carbon dioxide", "co 2"),
    ("foam", "afff", "foam type"),
    ("rosette", "rosette plate", "ceiling plate", "cover plate"),
)

_PHRASE_TO_CANONICAL: dict[str, str] = {}
_PHRASE_EXPANSIONS: dict[str, tuple[str, ...]] = {}
for _group in _PHRASE_GROUPS:
    _canon = _group[0]
    _PHRASE_EXPANSIONS[_canon] = _group
    for _phrase in _group:
        _PHRASE_TO_CANONICAL[_phrase] = _canon

# Make-list heuristic hints (phrase → category / sub-category). Order: specific first.
MAKE_LIST_DESCRIPTION_HINTS: tuple[tuple[str, str], ...] = (
    ("extinguisher", "EXTINGUISHER"),
    ("sprinkler flexible", "PIPE"),
    ("flexible connector", "PIPE"),
    ("flexible pipe", "PIPE"),
    ("flex drop", "PIPE"),
    ("flexible drop", "PIPE"),
    ("flow switch", "SPRINKLER"),
    ("flow indicator", "SPRINKLER"),
    ("water flow switch", "SPRINKLER"),
    ("inspector test", "SPRINKLER"),
    ("alarm valve", "SPRINKLER"),
    ("installation control", "SPRINKLER"),
    ("icv", "SPRINKLER"),
    ("sprinkler", "SPRINKLER"),
    ("rosette", "ACCESSORIES"),
    ("landing valve", "HYDRANT"),
    ("breeching inlet", "HYDRANT"),
    ("collective inlet", "HYDRANT"),
    ("hydrant", "HYDRANT"),
    ("hose reel", "HYDRANT"),
    ("hose box", "HYDRANT"),
    ("hose cabinet", "HYDRANT"),
    ("sand bucket set", "HYDRANT"),
    ("sand buckets", "HYDRANT"),
    ("sand bucket", "HYDRANT"),
    ("branch pipe", "HYDRANT"),
    ("fire brigade", "HYDRANT"),
    ("hose", "HYDRANT"),
    ("butterfly valve", "VALVE"),
    ("ball valve", "VALVE"),
    ("sluice", "VALVE"),
    ("gate valve", "VALVE"),
    ("non-return", "VALVE"),
    ("non return", "VALVE"),
    ("nrv", "VALVE"),
    ("check valve", "VALVE"),
    ("reflex valve", "VALVE"),
    ("reflex", "VALVE"),
    ("air release", "VALVE"),
    ("air relief", "VALVE"),
    ("y strainer", "VALVE"),
    ("y-type", "VALVE"),
    ("strainer", "VALVE"),
    ("foot valve", "VALVE"),
    ("pressure reducing", "VALVE"),
    ("prv", "VALVE"),
    ("valve", "VALVE"),
    ("jockey", "PUMP"),
    ("diesel pump", "PUMP"),
    ("hydrant pump", "PUMP"),
    ("sprinkler pump", "PUMP"),
    ("fire pump", "PUMP"),
    ("pump", "PUMP"),
    ("diesel tank", "PUMP ACCESSORIES"),
    ("exhaust", "PUMP ACCESSORIES"),
    ("air cushion", "PUMP ACCESSORIES"),
    ("pressure vessel", "PUMP ACCESSORIES"),
    ("air vessel", "PUMP ACCESSORIES"),
    ("pressure gauge", "INSTRUMENT"),
    ("pressure switch", "INSTRUMENT"),
    ("m.s pipe", "PIPE"),
    ("ms pipe", "PIPE"),
    ("m s pipe", "PIPE"),
    ("d.i", "PIPE"),
    ("d i", "PIPE"),
    ("di pipe", "PIPE"),
    ("c.i", "PIPE"),
    ("c i", "PIPE"),
    ("g.i", "PIPE"),
    ("g i", "PIPE"),
    ("ductile iron", "PIPE"),
    ("cast iron", "PIPE"),
    ("mild steel", "PIPE"),
    ("stainless steel", "PIPE"),
    ("upvc", "PIPE"),
    ("cpvc", "PIPE"),
    ("hdpe", "PIPE"),
    ("pipe", "PIPE"),
    ("fitting", "PIPE"),
    ("coupling", "PIPE"),
    ("tank", "TANK"),
    ("cable tray", "ACCESSORIES"),
    ("rosette plate", "ACCESSORIES"),
)

MAKE_LIST_SUB_CATEGORY_HINTS: tuple[tuple[str, str], ...] = (
    ("ball valve", "ball"),
    ("butterfly", "butterfly"),
    ("sluice", "sluice"),
    ("gate valve", "sluice"),
    ("non return", "non return"),
    ("non-return", "non return"),
    ("nrv", "non return"),
    ("check valve", "non return"),
    ("reflex valve", "non return"),
    ("reflex", "non return"),
    ("air release", "air release"),
    ("air relief", "air release"),
    ("y strainer", "y strainer"),
    ("y-type", "y strainer"),
    ("y type", "y strainer"),
    ("pressure reducing", "pressure reducing"),
    ("prv", "pressure reducing"),
    ("jockey", "jockey"),
    ("diesel pump", "diesel"),
    ("hydrant pump", "hydrant"),
    ("sprinkler pump", "sprinkler"),
    ("flow switch", "flow indicator"),
    ("flow indicator", "flow indicator"),
    ("water flow switch", "flow indicator"),
    ("inspector test", "inspecting"),
    ("alarm valve", "installation control"),
    ("installation control", "installation control"),
    ("icv", "installation control"),
    ("hose reel", "hose reel"),
    ("fire hose box", "hose box"),
    ("fire hose cabinet", "hose box"),
    ("hose box", "hose box"),
    ("hose cabinet", "hose box"),
    ("sand bucket set", "sand bucket set"),
    ("sand buckets", "sand bucket set"),
    ("sand bucket", "sand bucket set"),
    ("fire hose", "fire hose"),
    ("branch pipe", "branch"),
    ("landing valve", "landing"),
    ("fire brigade", "fire brigade"),
    ("breeching inlet", "fire brigade"),
    ("collective inlet", "fire brigade"),
    ("flexible", "sprinkler flexible"),
    ("flex drop", "sprinkler flexible"),
    ("flexible drop", "sprinkler flexible"),
    ("rosette", "rosette"),
    ("pressure gauge", "pressure gauge"),
    ("air cushion", "air cushion"),
    ("air vessel", "air cushion"),
    ("pressure vessel", "pressure vessel"),
    ("mild steel", "ms"),
    ("m s", "ms"),
    ("m.s", "ms"),
    ("ductile iron", "di"),
    ("cast iron", "ci"),
    ("galvan", "gi"),
    ("g i", "gi"),
    ("g.i", "gi"),
    ("upvc", "upvc"),
    ("cpvc", "cpvc"),
    ("hdpe", "hdpe"),
    ("abc", "abc"),
    ("dry chemical", "abc"),
    ("co2", "co2"),
    ("carbon dioxide", "co2"),
    ("foam", "foam"),
    ("afff", "foam"),
    ("dcp", "dcp"),
    ("wet chemical", "wet chemical"),
    ("water based", "water based"),
    ("fe36", "fe36"),
)


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
    if text in _PHRASE_TO_CANONICAL:
        return _PHRASE_TO_CANONICAL[text]
    if compact in _PHRASE_TO_CANONICAL:
        return _PHRASE_TO_CANONICAL[compact]
    for phrase_key, canon in sorted(_PHRASE_TO_CANONICAL.items(), key=lambda item: -len(item[0])):
        if phrase_key and phrase_key in text:
            return canon
    for mat_key, canon in sorted(_MATERIAL_CANONICAL.items(), key=lambda item: -len(item[0])):
        if len(mat_key) >= 2 and mat_key in text.split():
            return canon
        if len(mat_key) > 3 and mat_key in text:
            return canon
    return text


def display_material_label(value: Any) -> str:
    """Map free text onto the Rate_Master-style Class token when known."""
    if value is None or (isinstance(value, str) and not value.strip()):
        return ""
    canon = canonicalize_material_label(value)
    if canon in _CANONICAL_DISPLAY:
        return _CANONICAL_DISPLAY[canon]
    return str(value).strip()


def is_known_material_label(value: Any) -> bool:
    """True for DI / ductile iron / MS / … — not for Class tokens like 0 or 9."""
    if value is None or (isinstance(value, str) and not value.strip()):
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
    for item in _CANONICAL_QUERY_EXPANSIONS.get(mat_canon, ()):
        if item not in terms:
            terms.append(item)
    display = display_material_label(raw)
    if display and display not in terms:
        terms.append(display)
    phrase_canon = canonicalize_label(raw)
    for item in _PHRASE_EXPANSIONS.get(phrase_canon, ()):
        if item not in terms:
            terms.append(item)
    text = _normalize_label(raw)
    for phrase_key, canon in _PHRASE_TO_CANONICAL.items():
        if phrase_key in text:
            for item in _PHRASE_EXPANSIONS.get(canon, ()):
                if item not in terms:
                    terms.append(item)
    return terms


def expand_make_list_search_text(description: str) -> str:
    """Build a synonym-expanded search blob for make-list category heuristics.

    Fold material abbreviations (``M.S`` / ``D.I.`` / ``C.I``) and product
    phrases (NRV / hose reel / …) so free-text make-list lines map to taxonomy.
    """
    raw = str(description or "").strip()
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


def format_synonym_map_for_ai() -> str:
    """Render the shared material + product synonym map for AI prompt injection.

    Single source of truth with code matching/recall — keep prompts in sync by
    substituting ``{{SYNONYM_MAP}}`` rather than hardcoding synonym lists.
    """
    lines: list[str] = [
        "Approved synonym map (treat every term on a line as the SAME meaning).",
        "Do not lower match confidence only because BOQ text uses a synonym or",
        "short form from this map instead of the catalog wording.",
        "",
        "Materials / Class abbreviations:",
    ]
    for canon in sorted(_CANONICAL_QUERY_EXPANSIONS.keys()):
        expansions = list(_CANONICAL_QUERY_EXPANSIONS[canon])
        display = _CANONICAL_DISPLAY.get(canon)
        terms: list[str] = []
        if display and display not in terms:
            terms.append(display)
        for item in expansions:
            if item not in terms:
                terms.append(item)
        if not terms:
            continue
        lines.append(f"- {' = '.join(terms)}")

    lines.append("")
    lines.append("Product phrases / short forms:")
    for group in _PHRASE_GROUPS:
        # Preserve group order; drop empties.
        terms = [str(item).strip() for item in group if str(item).strip()]
        if len(terms) < 2:
            continue
        lines.append(f"- {' = '.join(terms)}")

    return "\n".join(lines)
