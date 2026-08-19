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

# Phrase groups are auto-derived from _AI_SYNONYM_CATALOG (defined below).
# Forward declaration — populated after _AI_SYNONYM_CATALOG is defined.
_PHRASE_TO_CANONICAL: dict[str, str] = {}
_PHRASE_EXPANSIONS: dict[str, tuple[str, ...]] = {}

# Make-list heuristic hints (phrase → category / sub-category). Order: specific first.
MAKE_LIST_DESCRIPTION_HINTS: tuple[tuple[str, str], ...] = (
    # EXTINGUISHER (before generic terms)
    ("abc extinguisher", "EXTINGUISHER"),
    ("co2 extinguisher", "EXTINGUISHER"),
    ("foam extinguisher", "EXTINGUISHER"),
    ("dcp extinguisher", "EXTINGUISHER"),
    ("fe36 extinguisher", "EXTINGUISHER"),
    ("wet chemical extinguisher", "EXTINGUISHER"),
    ("water based extinguisher", "EXTINGUISHER"),
    ("extinguisher", "EXTINGUISHER"),
    # PIPE (specific first)
    ("sprinkler flexible", "PIPE"),
    ("flexible connector", "PIPE"),
    ("flexible pipe", "PIPE"),
    ("flex drop", "PIPE"),
    ("flexible drop", "PIPE"),
    ("ms pipe", "PIPE"),
    ("m.s. pipe", "PIPE"),
    ("m.s pipe", "PIPE"),
    ("m s pipe", "PIPE"),
    ("gi pipe", "PIPE"),
    ("g.i. pipe", "PIPE"),
    ("mild steel pipe", "PIPE"),
    ("galvanized iron pipe", "PIPE"),
    ("galvanised iron pipe", "PIPE"),
    # SPRINKLER
    ("upright sprinkler", "SPRINKLER"),
    ("sidewall sprinkler", "SPRINKLER"),
    ("side wall sprinkler", "SPRINKLER"),
    ("pendant sprinkler", "SPRINKLER"),
    ("pendent sprinkler", "SPRINKLER"),
    ("flow switch", "SPRINKLER"),
    ("flow indicator", "SPRINKLER"),
    ("water flow switch", "SPRINKLER"),
    ("vane type flow switch", "SPRINKLER"),
    ("inspector test", "SPRINKLER"),
    ("inspecting and testing", "SPRINKLER"),
    ("inspection and testing", "SPRINKLER"),
    ("alarm valve", "SPRINKLER"),
    ("installation control", "SPRINKLER"),
    ("icv", "SPRINKLER"),
    ("sprinkler", "SPRINKLER"),
    # ACCESSORIES
    ("rosette", "ACCESSORIES"),
    ("rosette plate", "ACCESSORIES"),
    ("escutcheon", "ACCESSORIES"),
    ("fire pump panel", "ACCESSORIES"),
    ("fire pump pannel", "ACCESSORIES"),
    ("fire pump control panel", "ACCESSORIES"),
    ("pump controller", "ACCESSORIES"),
    ("cable tray", "ACCESSORIES"),
    # HYDRANT (specific sub-products first)
    ("external hydrant", "HYDRANT"),
    ("pillar hydrant", "HYDRANT"),
    ("yard hydrant", "HYDRANT"),
    ("fire hydrant pillar", "HYDRANT"),
    ("landing valve", "HYDRANT"),
    ("fire landing valve", "HYDRANT"),
    ("short branch pipe", "HYDRANT"),
    ("branch pipe", "HYDRANT"),
    ("fire nozzle", "HYDRANT"),
    ("fire hose reel", "HYDRANT"),
    ("hose reel", "HYDRANT"),
    ("fire hose box", "HYDRANT"),
    ("hose box", "HYDRANT"),
    ("hose cabinet", "HYDRANT"),
    ("fire hose", "HYDRANT"),
    ("fire man axe", "HYDRANT"),
    ("fire axe", "HYDRANT"),
    ("fireman's axe", "HYDRANT"),
    ("fire brigade inlet", "HYDRANT"),
    ("breeching inlet", "HYDRANT"),
    ("fbc inlet", "HYDRANT"),
    ("fire brigade delivery head", "HYDRANT"),
    ("fire brigade suction hose coupling", "HYDRANT"),
    ("suction hose coupling", "HYDRANT"),
    ("sand bucket set", "HYDRANT"),
    ("sand buckets", "HYDRANT"),
    ("sand bucket", "HYDRANT"),
    ("fire door", "HYDRANT"),
    ("fire brigade", "HYDRANT"),
    ("collective inlet", "HYDRANT"),
    ("hydrant", "HYDRANT"),
    ("hose", "HYDRANT"),
    # VALVE
    ("butterfly valve", "VALVE"),
    ("bfv", "VALVE"),
    ("bf valve", "VALVE"),
    ("ball valve", "VALVE"),
    ("bv", "VALVE"),
    ("sluice", "VALVE"),
    ("gate valve", "VALVE"),
    ("gv", "VALVE"),
    ("non-return", "VALVE"),
    ("non return", "VALVE"),
    ("nrv", "VALVE"),
    ("nr valve", "VALVE"),
    ("check valve", "VALVE"),
    ("reflex valve", "VALVE"),
    ("reflex", "VALVE"),
    ("air release", "VALVE"),
    ("air relief", "VALVE"),
    ("arv", "VALVE"),
    ("y strainer", "VALVE"),
    ("y-type", "VALVE"),
    ("strainer", "VALVE"),
    ("foot valve", "VALVE"),
    ("pressure reducing", "VALVE"),
    ("prv", "VALVE"),
    ("valve", "VALVE"),
    # PUMP
    ("jockey pump", "PUMP"),
    ("jockey", "PUMP"),
    ("diesel pump", "PUMP"),
    ("diesel fire pump", "PUMP"),
    ("hydrant pump", "PUMP"),
    ("fire hydrant pump", "PUMP"),
    ("sprinkler pump", "PUMP"),
    ("fire sprinkler pump", "PUMP"),
    ("fire pump", "PUMP"),
    ("pump", "PUMP"),
    # PUMP ACCESSORIES
    ("exhaust piping system", "PUMP ACCESSORIES"),
    ("engine exhaust", "PUMP ACCESSORIES"),
    ("diesel tank", "PUMP ACCESSORIES"),
    ("diesel fuel tank", "PUMP ACCESSORIES"),
    ("fuel tank", "PUMP ACCESSORIES"),
    ("rubber expansion joint", "PUMP ACCESSORIES"),
    ("vibration eliminator", "PUMP ACCESSORIES"),
    ("exhaust", "PUMP ACCESSORIES"),
    # TANK
    ("air cushion tank", "TANK"),
    ("air cushion", "TANK"),
    ("air vessel", "TANK"),
    ("pressure vessel", "TANK"),
    ("grp water tank", "TANK"),
    ("grp tank", "TANK"),
    ("frp water tank", "TANK"),
    ("frp tank", "TANK"),
    ("tank", "TANK"),
    # INSTRUMENT
    ("pressure gauge", "INSTRUMENT"),
    ("pressure indicator", "INSTRUMENT"),
    ("pressure switch", "INSTRUMENT"),
    # PIPE (generic — last)
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
)

MAKE_LIST_SUB_CATEGORY_HINTS: tuple[tuple[str, str], ...] = (
    # VALVE
    ("ball valve", "ball valve"),
    ("bv", "ball valve"),
    ("butterfly valve", "butterfly"),
    ("butterfly", "butterfly"),
    ("bfv", "butterfly"),
    ("bf valve", "butterfly"),
    ("sluice valve", "sluice valve"),
    ("sluice", "sluice valve"),
    ("gate valve", "sluice valve"),
    ("gv", "sluice valve"),
    ("non return valve", "non return valve"),
    ("non-return", "non return valve"),
    ("non return", "non return valve"),
    ("nrv", "non return valve"),
    ("nr valve", "non return valve"),
    ("check valve", "non return valve"),
    ("reflex valve", "non return valve"),
    ("reflex", "non return valve"),
    ("air release valve", "air release valve"),
    ("air release", "air release valve"),
    ("air relief", "air release valve"),
    ("arv", "air release valve"),
    ("air valve", "air release valve"),
    ("y strainer", "y strainer"),
    ("y-type strainer", "y strainer"),
    ("y type strainer", "y strainer"),
    ("y filter", "y strainer"),
    ("pressure reducing", "pressure reducing"),
    ("prv", "pressure reducing"),
    # HYDRANT
    ("external hydrant", "external hydrant"),
    ("pillar hydrant", "external hydrant"),
    ("yard hydrant", "external hydrant"),
    ("fire hydrant pillar", "external hydrant"),
    ("landing valve", "landing valve"),
    ("fire landing valve", "landing valve"),
    ("hydrant landing valve", "landing valve"),
    ("hydrant valve", "landing valve"),
    ("branch pipe", "branch pipe"),
    ("fire branch pipe", "branch pipe"),
    ("fire nozzle", "branch pipe"),
    ("short branch pipe", "short branch pipe"),
    ("short branch nozzle", "short branch pipe"),
    ("is 903 branch pipe", "short branch pipe"),
    ("hose reel", "fire hose reel"),
    ("fire hose reel", "fire hose reel"),
    ("hose reel drum", "fire hose reel"),
    ("swinging hose reel", "fire hose reel"),
    ("fire hose", "fire hose"),
    ("delivery hose", "fire hose"),
    ("rrl hose", "fire hose"),
    ("fire man axe", "fire man axe"),
    ("fire axe", "fire man axe"),
    ("fireman's axe", "fire man axe"),
    ("fire brigade inlet", "fire brigade inlet connection"),
    ("breeching inlet", "fire brigade inlet connection"),
    ("fbc inlet", "fire brigade inlet connection"),
    ("fire brigade", "fire brigade inlet connection"),
    ("collective inlet", "fire brigade inlet connection"),
    ("fire brigade delivery head", "fire brigade delivery head"),
    ("fire brigade outlet", "fire brigade delivery head"),
    ("fire brigade suction hose coupling", "fire brigade suction hose coupling"),
    ("suction hose coupling", "fire brigade suction hose coupling"),
    ("sand bucket set", "sand bucket set"),
    ("sand buckets", "sand bucket set"),
    ("sand bucket", "sand bucket set"),
    ("fire buckets", "sand bucket set"),
    ("fire hose box", "fire hose box"),
    ("hose box", "fire hose box"),
    ("fire hose cabinet", "fire hose box"),
    ("hose cabinet", "fire hose box"),
    ("fire door", "fire door"),
    ("fire rated door", "fire door"),
    # PIPE
    ("ms pipe", "ms"),
    ("mild steel pipe", "ms"),
    ("m.s. pipe", "ms"),
    ("mild steel", "ms"),
    ("m s", "ms"),
    ("m.s", "ms"),
    ("gi pipe", "gi"),
    ("g.i. pipe", "gi"),
    ("galvanized iron pipe", "gi"),
    ("galvanised iron pipe", "gi"),
    ("galvan", "gi"),
    ("g i", "gi"),
    ("g.i", "gi"),
    ("ductile iron", "di"),
    ("cast iron", "ci"),
    ("upvc", "upvc"),
    ("cpvc", "cpvc"),
    ("hdpe", "hdpe"),
    ("sprinkler flexible pipe", "sprinkler flexible pipe"),
    ("flexible sprinkler pipe", "sprinkler flexible pipe"),
    ("sprinkler flexible", "sprinkler flexible pipe"),
    ("flexible", "sprinkler flexible pipe"),
    ("flex drop", "sprinkler flexible pipe"),
    ("flexible drop", "sprinkler flexible pipe"),
    # SPRINKLER
    ("upright sprinkler", "upright"),
    ("upright", "upright"),
    ("sidewall sprinkler", "side wall"),
    ("side wall", "side wall"),
    ("pendant sprinkler", "pendant"),
    ("pendent sprinkler", "pendant"),
    ("pendant", "pendant"),
    ("flow switch", "flow indicator switch"),
    ("flow indicator", "flow indicator switch"),
    ("water flow switch", "flow indicator switch"),
    ("vane type flow switch", "flow indicator switch"),
    ("inspector test", "inspecting and testing assembly"),
    ("inspecting and testing", "inspecting and testing assembly"),
    ("inspection and testing", "inspecting and testing assembly"),
    ("ita", "inspecting and testing assembly"),
    ("test and drain", "inspecting and testing assembly"),
    ("alarm valve", "installation control valve"),
    ("installation control valve", "installation control valve"),
    ("installation control", "installation control valve"),
    ("icv", "installation control valve"),
    ("zone control valve", "installation control valve"),
    # PUMP
    ("jockey pump", "jockey pump"),
    ("jockey", "jockey pump"),
    ("diesel pump", "diesel pump"),
    ("diesel fire pump", "diesel pump"),
    ("hydrant pump", "hydrant pump"),
    ("fire hydrant pump", "hydrant pump"),
    ("sprinkler pump", "sprinkler pump"),
    ("fire sprinkler pump", "sprinkler pump"),
    # PUMP ACCESSORIES
    ("exhaust piping system", "exhaust piping system"),
    ("engine exhaust", "exhaust piping system"),
    ("diesel pump exhaust", "exhaust piping system"),
    ("diesel tank", "diesel tank"),
    ("diesel fuel tank", "diesel tank"),
    ("fuel tank", "diesel tank"),
    ("rubber expansion joint", "rubber expansion joints"),
    ("vibration eliminator", "rubber expansion joints"),
    ("rubber bellows", "rubber expansion joints"),
    # TANK
    ("air cushion tank", "air cushion tank"),
    ("air cushion", "air cushion tank"),
    ("air vessel", "air cushion tank"),
    ("plain air vessel", "air cushion tank"),
    ("pressure vessel", "pressure vessel"),
    ("pressure tank", "pressure vessel"),
    ("grp water tank", "grp water tank"),
    ("grp tank", "grp water tank"),
    ("frp water tank", "grp water tank"),
    ("frp tank", "grp water tank"),
    # ACCESSORIES
    ("rosette", "rosettee plate"),
    ("rosette plate", "rosettee plate"),
    ("escutcheon", "rosettee plate"),
    ("fire pump panel", "fire pump pannel"),
    ("fire pump pannel", "fire pump pannel"),
    ("fire pump control panel", "fire pump pannel"),
    ("pump controller", "fire pump pannel"),
    # INSTRUMENT
    ("pressure gauge", "pressure gauge"),
    ("pressure indicator", "pressure gauge"),
    ("pressure meter", "pressure gauge"),
    # EXTINGUISHER
    ("abc", "abc"),
    ("abc extinguisher", "abc"),
    ("dry chemical", "abc"),
    ("abc dcp", "abc"),
    ("co2", "co2"),
    ("carbon dioxide", "co2"),
    ("co2 extinguisher", "co2"),
    ("foam", "foam"),
    ("afff", "foam"),
    ("foam extinguisher", "foam"),
    ("dcp", "dcp"),
    ("dcp extinguisher", "dcp"),
    ("dry powder", "dcp"),
    ("wet chemical", "wet chemical"),
    ("water based", "water based"),
    ("fe36", "fe36"),
    ("fe-36", "fe36"),
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


# ── AI synonym catalog: (Category, Sub_Category) → list of BOQ synonyms ──
# This is the single source of truth for prompt injection. Add new rows here.
_AI_SYNONYM_CATALOG: dict[tuple[str, str], tuple[str, ...]] = {
    # PIPE
    ("PIPE", "MS"): ("Mild Steel Pipe", "MS Pipe", "M.S. Pipe", "MS Fire Fighting Pipe", "MS Black Steel Pipe"),
    ("PIPE", "GI"): ("GI Pipe", "G.I. Pipe", "Galvanized Iron Pipe", "Galvanised Iron Pipe", "GI Fire Pipe"),
    ("PIPE", "SPRINKLER FLEXIBLE PIPE"): ("Sprinkler Flexible Pipe", "Flexible Sprinkler Pipe", "Sprinkler Drop Hose", "Flex Drop"),
    # VALVE
    ("VALVE", "SLUICE VALVE"): ("Sluice Valve", "Gate Valve", "Gate Isolation Valve", "GV", "Fire Sluice Valve"),
    ("VALVE", "BUTTERFLY"): ("Butterfly Valve", "BFV", "BF Valve", "Gear Operated Butterfly Valve"),
    ("VALVE", "BALL VALVE"): ("Ball Valve", "BV", "Ball Isolation Valve", "Full Port Ball Valve"),
    ("VALVE", "NON RETURN VALVE"): ("Non Return Valve", "NRV", "NR Valve", "Check Valve", "Non-Return Valve", "Reflex Valve"),
    ("VALVE", "AIR RELEASE VALVE"): ("Air Release Valve", "ARV", "Air Valve"),
    ("VALVE", "Y STRAINER"): ("Y Strainer", "Y-Type Strainer", "Y Filter"),
    # HYDRANT
    ("HYDRANT", "EXTERNAL HYDRANT"): ("External Hydrant", "Pillar Hydrant", "Yard Hydrant", "Fire Hydrant Pillar"),
    ("HYDRANT", "LANDING VALVE"): ("Landing Valve", "Fire Landing Valve", "Hydrant Landing Valve", "Hydrant Valve"),
    ("HYDRANT", "BRANCH PIPE"): ("Branch Pipe", "Fire Branch Pipe", "Branch Pipe Nozzle", "Fire Nozzle"),
    ("HYDRANT", "SHORT BRANCH PIPE"): ("Short Branch Pipe", "Short Branch Nozzle", "IS 903 Branch Pipe"),
    ("HYDRANT", "FIRE HOSE REEL"): ("Fire Hose Reel", "Hose Reel", "Hose Reel Drum", "Swinging Hose Reel"),
    ("HYDRANT", "FIRE HOSE"): ("Fire Hose", "Delivery Hose", "Hydrant Hose", "RRL Hose", "Synthetic Fire Hose"),
    ("HYDRANT", "FIRE MAN AXE"): ("Fire Axe", "Fireman's Axe", "Fire Man Axe", "Fire Fighting Axe"),
    ("HYDRANT", "FIRE BRIGADE INLET CONNECTION"): ("Fire Brigade Inlet", "Breeching Inlet", "FBC Inlet", "Fire Brigade Breeching Inlet"),
    ("HYDRANT", "FIRE BRIGADE DELIVERY HEAD"): ("Fire Brigade Delivery Head", "Fire Brigade Outlet", "Delivery Head"),
    ("HYDRANT", "FIRE BRIGADE SUCTION HOSE COUPLING"): ("Suction Hose Coupling", "Fire Suction Coupling", "Pump Suction Hose Coupling"),
    ("HYDRANT", "SAND BUCKET SET"): ("Sand Bucket Set", "Fire Sand Bucket Set", "Fire Buckets", "Sand Buckets with Stand"),
    ("HYDRANT", "FIRE HOSE BOX"): ("Fire Hose Box", "Hose Box", "Fire Hose Cabinet", "Hose Cabinet", "Hydrant Hose Box"),
    ("HYDRANT", "FIRE DOOR"): ("Fire Door", "Fire Rated Door", "Fire Resistant Door", "Fire Check Door"),
    # SPRINKLER
    ("SPRINKLER", "UPRIGHT"): ("Upright Sprinkler", "Upright Sprinkler Head", "Upright Type Sprinkler"),
    ("SPRINKLER", "SIDE WALL"): ("Sidewall Sprinkler", "Side Wall Sprinkler", "Horizontal Sidewall Sprinkler"),
    ("SPRINKLER", "PENDANT"): ("Pendant Sprinkler", "Pendent Sprinkler", "Hanging Sprinkler"),
    ("SPRINKLER", "FLOW INDICATOR SWITCH"): ("Flow Switch", "Water Flow Switch", "Flow Indicator", "Vane Type Flow Switch"),
    ("SPRINKLER", "INSPECTING AND TESTING ASSEMBLY"): ("Inspection and Testing Assembly", "ITA", "Test and Drain Assembly", "Inspector Test"),
    ("SPRINKLER", "INSTALLATION CONTROL VALVE"): ("ICV", "Alarm Valve", "Zone Control Valve Assembly", "Sprinkler Control Valve"),
    # PUMP
    ("PUMP", "JOCKEY PUMP"): ("Jockey Pump", "Pressure Maintenance Pump", "Jockey Duty Pump"),
    ("PUMP", "DIESEL PUMP"): ("Diesel Pump", "Diesel Fire Pump", "Diesel Driven Fire Pump", "Diesel Engine Driven Pump"),
    ("PUMP", "HYDRANT PUMP"): ("Hydrant Pump", "Fire Hydrant Pump", "Hydrant Duty Pump"),
    ("PUMP", "SPRINKLER PUMP"): ("Sprinkler Pump", "Sprinkler Fire Pump", "Fire Sprinkler Pump"),
    # PUMP ACCESSORIES
    ("PUMP ACCESSORIES", "EXHAUST PIPING SYSTEM"): ("Exhaust Piping System", "Engine Exhaust System", "Diesel Pump Exhaust"),
    ("PUMP ACCESSORIES", "DIESEL TANK"): ("Diesel Tank", "Diesel Fuel Tank", "Fuel Tank", "Fire Pump Diesel Tank"),
    ("PUMP ACCESSORIES", "RUBBER EXPANSION JOINTS"): ("Rubber Expansion Joint", "Vibration Eliminator", "Rubber Bellows"),
    # TANK
    ("TANK", "AIR CUSHION TANK"): ("Air Cushion Tank", "Air Vessel", "Air Pressure Vessel", "Plain Air Vessel"),
    ("TANK", "PRESSURE VESSEL"): ("Pressure Vessel", "Pressure Tank", "Pressure Maintenance Vessel"),
    ("TANK", "GRP WATER TANK"): ("GRP Water Tank", "GRP Tank", "FRP Water Tank", "FRP Tank", "Fiberglass Water Tank"),
    # ACCESSORIES
    ("ACCESSORIES", "ROSETTEE PLATE"): ("Rosette Plate", "Rosette", "Escutcheon Plate", "Sprinkler Rosette"),
    ("ACCESSORIES", "FIRE PUMP PANNEL"): ("Fire Pump Panel", "Fire Pump Control Panel", "Fire Pump Controller", "Pump Controller"),
    # INSTRUMENT
    ("INSTRUMENT", "PRESSURE GAUGE"): ("Pressure Gauge", "Pressure Indicator", "Pressure Meter", "PG"),
    # EXTINGUISHER
    ("EXTINGUISHER", "ABC"): ("ABC Extinguisher", "ABC Fire Extinguisher", "ABC DCP Extinguisher", "Dry Chemical Powder Extinguisher"),
    ("EXTINGUISHER", "CO2"): ("CO2 Extinguisher", "Carbon Dioxide Extinguisher", "CO2 Fire Extinguisher"),
    ("EXTINGUISHER", "WATER BASED"): ("Water Based Extinguisher", "Water Fire Extinguisher", "Water Extinguisher"),
    ("EXTINGUISHER", "WET CHEMICAL"): ("Wet Chemical Extinguisher", "Wet Chemical Fire Extinguisher"),
    ("EXTINGUISHER", "FE36"): ("FE36 Extinguisher", "FE-36 Extinguisher", "Clean Agent FE36 Extinguisher"),
    ("EXTINGUISHER", "DCP"): ("DCP Extinguisher", "Dry Powder Extinguisher", "DCP Fire Extinguisher"),
    ("EXTINGUISHER", "FOAM"): ("Foam Extinguisher", "Mechanical Foam Extinguisher", "AFFF Extinguisher"),
}

# ── Build _PHRASE_TO_CANONICAL / _PHRASE_EXPANSIONS from _AI_SYNONYM_CATALOG ──
# Each catalog entry becomes a phrase group: (sub_category_lower, *synonyms_lower).
for (_cat, _sub), _synonyms in _AI_SYNONYM_CATALOG.items():
    _canon = _sub.lower()
    _group = tuple(dict.fromkeys(
        [_canon] + [s.lower() for s in _synonyms]
    ))
    _PHRASE_EXPANSIONS[_canon] = _group
    for _phrase in _group:
        _PHRASE_TO_CANONICAL.setdefault(_phrase, _canon)


def format_synonym_map_for_ai() -> str:
    """Compact synonym map for AI prompt injection.

    Groups synonyms by category → sub-category for context-aware matching.
    Single source of truth — substituted into prompts via ``{{SYNONYM_MAP}}``.
    """
    cat_sub: dict[str, dict[str, list[str]]] = {}
    for (cat, sub), synonyms in _AI_SYNONYM_CATALOG.items():
        cat_sub.setdefault(cat, {})[sub] = list(synonyms)

    lines: list[str] = [
        "Synonym guide — treat ALL terms on a line as the SAME product.",
        "Do not lower confidence when BOQ uses a synonym from this list.",
        "",
        "Material abbreviations:",
    ]
    for canon in sorted(_CANONICAL_QUERY_EXPANSIONS.keys()):
        terms = [_CANONICAL_DISPLAY.get(canon, canon)]
        for item in _CANONICAL_QUERY_EXPANSIONS[canon]:
            if item not in terms:
                terms.append(item)
        lines.append(f"  {' = '.join(terms)}")

    lines.append("")
    lines.append("Product synonyms (Category > Sub-category: synonyms):")
    for cat in sorted(cat_sub.keys()):
        for sub in sorted(cat_sub[cat].keys()):
            terms = cat_sub[cat][sub]
            if len(terms) < 1:
                continue
            lines.append(f"  {cat} > {sub}: {'; '.join(terms)}")

    return "\n".join(lines)
