"""Dynamic text heuristics for splitting descriptions and brand/make tokens.

Uses structural signals (case, length, punctuation, slash position) instead of
hardcoded domain word lists so PDF/Excel-derived text works across clients.
"""
from __future__ import annotations

import re

_SPEC_PUNCTUATION = re.compile(r"[&\-/()]")
_ABBREVIATION = re.compile(r"(?:\b[A-Z]\.)+[A-Z]?|\b[A-Z]\.[A-Z]\b")
_HYPHEN_SPACE = re.compile(r"\s*-\s*")

# Common material nouns that look Title Case in PDFs but are not brand names.
_MAKE_STOPWORDS = frozenset(
    {
        "pipe",
        "pipes",
        "fitting",
        "fittings",
        "valve",
        "valves",
        "sink",
        "steel",
        "brass",
        "system",
        "systems",
        "type",
        "class",
        "heavy",
        "brand",
        "make",
        "makes",
        "material",
        "materials",
        "item",
        "items",
        "unit",
        "units",
        "size",
        "dia",
        "china",
        "iron",
        "copper",
        "alloy",
        "rubber",
        "paint",
        "primer",
        "pump",
        "pumps",
        "hose",
        "box",
        "door",
        "plate",
        "plates",
        "head",
        "heads",
        "water",
        "fire",
        "installation",
        "installations",
        "automatic",
        "hand",
        "soap",
        "infrared",
        "sensor",
        "operated",
        "faucets",
        "faucet",
        "dispenser",
        "dryer",
        "cistern",
        "geyser",
        "towel",
        "paper",
        "sanitaryware",
        "wastes",
        "spreaders",
        "urinal",
        "flush",
        "angle",
        "ball",
        "lever",
        "traps",
        "trap",
        "sink",
        "approved",
        "quality",
        "marked",
        "complete",
        "including",
        "connection",
        "connections",
        "flexible",
        "braided",
        "portable",
        "external",
        "internal",
        "hanger",
        "hangers",
        "adjustable",
        "technologies",
        "solutions",
        "environmental",
        "enviromental",
        "bolts",
        "bolt",
        "rods",
        "rod",
        "extinguisher",
        "extinguishers",
        "accessories",
        "accessory",
        "expansion",
        "welding",
        "portable",
        "quartozoid",
        "bulb",
        "sprinkler",
        "sprinklers",
        "drops",
        "rosette",
        "gauges",
        "gauge",
        "switches",
        "switch",
        "landing",
        "nozzle",
        "nozzles",
        "couplings",
        "coupling",
        "branch",
        "pipe",
        "ul",
        "fm",
    }
)

# Tokens that are never approved makes on their own.
_REJECT_MAKE_ALONE = frozenset(
    {
        "pvt",
        "pvt.",
        "ltd",
        "ltd.",
        "limited",
        "co",
        "co.",
        "company",
        "accessories",
        "accessory",
        "fm",
        "ul",
        "isi",
        "approved",
        "and",
        "&",
    }
)


def uppercase_letter_ratio(text: str) -> float:
    letters = [char for char in text if char.isalpha()]
    if not letters:
        return 0.0
    return sum(char.isupper() for char in letters) / len(letters)


def has_lowercase_letters(text: str) -> bool:
    return any(char.islower() for char in text)


def word_count(text: str) -> int:
    return len(text.split())


def normalize_make_segment(segment: str) -> str:
    """Normalize common PDF artefacts in make segments (``ARCO- Spain`` → ``ARCO-Spain``)."""
    text = str(segment or "").strip().strip(".,;:")
    text = _HYPHEN_SPACE.sub("-", text)
    text = re.sub(r"\s*,\s*", ", ", text)
    text = re.sub(r"\s*\(\s*", " (", text)
    text = re.sub(r"\s*\)\s*", ") ", text)
    return re.sub(r"\s+", " ", text).strip().strip(".,;:")


_FUSED_BRAND_TAIL = re.compile(r"^(.*[a-z0-9).:])([A-Z][A-Za-z]{1,20})$")
_MATERIAL_LINE_HINTS = re.compile(
    r"(?:\bmm\b|\bdia\b|\bclass\b|\bconforming\b|\bis\s*:?\s*\d|\bproviding\b|"
    r"\bincluding\b|\bpaint(?:ing)?\b|\bpipework\b|\bfittings?\b)",
    re.IGNORECASE,
)


def peel_fused_case_brand(token: str) -> tuple[str, str | None]:
    """
    Split a token where a brand is glued onto specs: ``IS:1239Tata``, ``pipeASR``.

    Returns ``(prefix, brand)`` or ``(token, None)`` when no fusion is found.
    """
    core = normalize_make_segment(token)
    if not core or " " in core:
        # Keep punctuation that marks fusion boundaries (``Approved)Tyco``).
        core = str(token or "").strip().strip(".,;")
        core = _HYPHEN_SPACE.sub("-", core)
        core = re.sub(r"\s+", " ", core).strip()
    if not core or " " in core:
        return token, None
    match = _FUSED_BRAND_TAIL.match(core)
    if not match:
        return token, None
    prefix, brand = match.group(1), match.group(2)
    if not looks_like_make_word(brand):
        return token, None
    if len(prefix) < 2:
        return token, None
    return prefix, brand


def peel_fused_case_makes(segment: str) -> tuple[str, list[str]]:
    """Peel case-fused trailing brands from any token (``pipeASR``, ``IS:1239Tata``)."""
    text = str(segment or "").strip()
    if not text:
        return text, []
    words = text.split()
    makes: list[str] = []
    # Rightmost fused token first (brand glued onto a prior word).
    for index in range(len(words) - 1, -1, -1):
        prefix, brand = peel_fused_case_brand(words[index])
        if not brand:
            continue
        make = normalize_make_segment(brand)
        following = words[index + 1 :]
        # Keep a short place qualifier with the brand: ``ASR, Italy``.
        if following:
            place = following[0].strip(".,;:()")
            if place and place[:1].isupper() and word_count(place) == 1 and len(place) <= 12:
                make = f"{make}, {place}"
                following = following[1:]
        # Drop parenthetical marketing tails after the brand.
        cleaned_following: list[str] = []
        for word in following:
            if word.startswith("(") or word.casefold() in {"marketed", "by"}:
                break
            cleaned_following.append(word)
        makes.insert(0, make)
        words = words[:index] + ([prefix] if prefix else []) + cleaned_following
        # Continue scanning left for additional fusions.
    remainder = " ".join(words).strip().rstrip(",;")
    return remainder, makes


_LEGAL_SUFFIX = re.compile(
    r"(?:\s|,)+(?:pvt\.?\s*ltd\.?|private\s+limited|ltd\.?|limited|co\.?|company)\s*$",
    re.IGNORECASE,
)


def looks_like_standalone_manufacturer(text: str) -> bool:
    """
    True when a whole numbered-line body is a manufacturer name, not a material.

    Examples: ``Grundfoss``, ``KSB``, ``Mather Platt``, ``Kavya water technologies``.
    """
    segment = normalize_make_segment(text)
    if not segment or _MATERIAL_LINE_HINTS.search(segment):
        return False
    segment = _LEGAL_SUFFIX.sub("", segment).strip(" ,")
    if not segment:
        return False
    if looks_like_make_token(segment):
        return True
    words = segment.split()
    if not words or len(words) > 5:
        return False
    # Company-style lines: leading brand token + short generic tail.
    first = words[0].strip(".,;:")
    if not looks_like_make_word(first):
        return False
    if len(words) == 1:
        return True
    # Allow mild fillers (water, and, &) between brand-like tokens.
    fillers = {"and", "&", "of", "the", "water", "pvt", "ltd", "limited", "co", "company"}
    significant = [word for word in words[1:] if word.casefold().strip(".,;") not in fillers]
    if not significant:
        return True
    if len(significant) <= 2 and all(
        word[:1].isupper() or word.casefold() in {"technologies", "solutions", "industries"}
        for word in significant
    ):
        return True
    return False


def _normalize_make_key(text: str) -> str:
    return normalize_make_segment(text).casefold().rstrip(".")


def is_valid_approved_make(make: str) -> bool:
    """False for material nouns / legal suffixes wrongly captured as makes."""
    text = normalize_make_segment(make)
    if not text:
        return False
    key = _normalize_make_key(text)
    if key in _REJECT_MAKE_ALONE:
        return False
    # Single material stopword is never a make.
    if key in _MAKE_STOPWORDS and len(text.split()) == 1:
        return False
    words = [word.strip(".,;:()") for word in text.split() if word.strip(".,;:()")]
    if not words:
        return False
    if all(_normalize_make_key(word) in _REJECT_MAKE_ALONE for word in words):
        return False
    # ``PVT. LTD`` / ``Ltd`` company suffixes alone are not brands.
    if all(_normalize_make_key(word) in {"pvt", "ltd", "limited", "co", "company"} for word in words):
        return False
    # Multi-word tokens already accepted as make tokens (e.g. System Sensor).
    if looks_like_make_token(text):
        return True
    if all(_normalize_make_key(word) in _REJECT_MAKE_ALONE | _MAKE_STOPWORDS for word in words):
        return False
    return bool(looks_like_make_word(words[0]))


def repair_description_and_makes(
    description: str,
    makes: list[str],
) -> tuple[str, list[str]]:
    """
    Move material words wrongly captured in makes back into the description.

    Examples: ``Bolts Hilti`` → description gains ``Bolts``, make becomes ``Hilti``.
    """
    desc_parts = [str(description or "").strip()] if str(description or "").strip() else []
    cleaned_makes: list[str] = []
    seen: set[str] = set()

    for raw in makes or []:
        text = normalize_make_segment(raw)
        if not text:
            continue
        words = text.split()
        # Material noun stuck ahead of a real brand: ``Bolts Hilti``, ``Rods Advani``.
        # Keep intact trade names that are valid make tokens (``System Sensor``).
        if (
            len(words) >= 2
            and words[0].casefold().strip(".,;:") in _MAKE_STOPWORDS
            and not looks_like_make_token(text)
        ):
            material = words[0].strip(".,;:")
            brand = normalize_make_segment(" ".join(words[1:]))
            if material:
                desc_parts.append(material)
            text = brand
        if not text or not is_valid_approved_make(text):
            # Keep rejected multi-word material text in the description.
            if text and text.casefold() not in {_normalize_make_key(part) for part in desc_parts}:
                if any(word.casefold() in _MAKE_STOPWORDS for word in text.split()):
                    desc_parts.append(text)
            continue
        key = _normalize_make_key(text)
        if key in seen:
            continue
        seen.add(key)
        cleaned_makes.append(text)

    description_text = re.sub(r"\s+", " ", " ".join(desc_parts)).strip()
    return description_text, cleaned_makes


def looks_like_make_word(word: str) -> bool:
    """Return True when a single token is likely a brand/make name."""
    token = normalize_make_segment(word)
    if not token or len(token) > 28:
        return False
    if token.casefold() in _MAKE_STOPWORDS:
        return False
    # Spec fragments and fused leftovers are not brands (``IS:1239``, ``DN150``).
    if any(char.isdigit() for char in token) or ":" in token:
        return False

    # Brand-Country / Brand-Place: Schell-Germany, CIM-Italy, ARCO-Spain.
    if "-" in token:
        parts = [part for part in token.split("-") if part]
        if 2 <= len(parts) <= 3 and all(looks_like_make_word(part) for part in parts):
            return True
        return False

    letters = [char for char in token if char.isalpha()]
    if not letters:
        return False

    # ALL CAPS brands: TATA, DLINE, ESS, KSB, GMGR.
    if all(char.isupper() for char in letters) and 2 <= len(letters) <= 12:
        return True

    # Title Case brands from PDF text: Jaquar, Kohler, Euronics, Nirali.
    if token[0].isupper() and has_lowercase_letters(token):
        core = token.replace(".", "")
        if not core.replace("&", "").isalnum():
            return False
        rest = token[1:]
        if rest.islower() and 3 <= len(token) <= 20:
            return True
        # Camel / mixed brands with at most one extra capital (McDonald-style).
        if sum(char.isupper() for char in rest) <= 1 and 3 <= len(token) <= 20:
            return True
        return False

    if len(token) <= 3 and token.isalpha():
        return token.isupper() or token[0].isupper()

    return uppercase_letter_ratio(token) >= 0.75 and not has_lowercase_letters(token)


def _looks_like_remainder_after_peel(remainder: str) -> bool:
    remainder = remainder.strip()
    if not remainder:
        return False
    if has_lowercase_letters(remainder):
        return True
    if word_count(remainder) >= 4:
        return True
    if _SPEC_PUNCTUATION.search(remainder):
        return True
    if _ABBREVIATION.search(remainder):
        return True
    if len(remainder) >= 8:
        return True
    return False


def peel_trailing_make_word(segment: str) -> tuple[str, list[str]]:
    """Peel one trailing brand token from a description segment."""
    # First undo PDF fusions like ``IS:1239Tata`` / ``pipeASR``.
    fused_remainder, fused_makes = peel_fused_case_makes(segment)
    if fused_makes:
        if fused_remainder:
            deeper_remainder, deeper_makes = peel_trailing_make_word(fused_remainder)
            return deeper_remainder, deeper_makes + fused_makes
        return fused_remainder, fused_makes

    words = segment.split()
    if len(words) < 2:
        return segment, []

    # Two-word peels only for strong brand patterns (``ESS ESS``, ``Unik Brand``),
    # not Title-Case noun + brand (``Sanitaryware Jaquar``, ``Dispenser Euronics``).
    if len(words) >= 3:
        first, second = words[-2], words[-1]
        strong_two = (
            first.isupper() and second.isupper()
        ) or second.casefold() in {
            "brand",
            "ltd",
            "limited",
            "pvt",
            "co",
            "company",
            "italy",
            "spain",
            "germany",
        }
        if strong_two:
            tail = " ".join(words[-2:])
            if looks_like_make_token(tail):
                remainder = " ".join(words[:-2]).strip()
                if remainder and _looks_like_remainder_after_peel(remainder):
                    return remainder, [normalize_make_segment(tail)]

    # Prefer peeling a trailing two-word brand (``Mather Platt``), but never
    # when the first tail word is a material stopword (``Hanger Chilly``).
    if len(words) >= 3:
        tail = " ".join(words[-2:])
        first_tail = words[-2].strip(".,;:").casefold()
        if first_tail not in _MAKE_STOPWORDS and looks_like_make_token(tail):
            remainder = " ".join(words[:-2]).strip()
            if remainder and _looks_like_remainder_after_peel(remainder):
                return remainder, [normalize_make_segment(tail)]

    last_word = words[-1].strip(".,;:")
    if not looks_like_make_word(last_word):
        return segment, []
    remainder = " ".join(words[:-1]).strip()
    if not remainder or not _looks_like_remainder_after_peel(remainder):
        return segment, []
    return remainder, [normalize_make_segment(last_word)]


def peel_fused_segment_boundary(segment: str) -> tuple[str, list[str]]:
    """Peel one trailing brand from a slash segment fused with description text."""
    return peel_trailing_make_word(segment)


def looks_like_make_token(segment: str) -> bool:
    """Return True when a slash segment is likely one approved make."""
    segment = normalize_make_segment(segment)
    if not segment or len(segment) > 48:
        return False

    # ``Jindal (Hissar)`` / ``ASR, Italy`` — brand plus short place qualifier.
    if "," in segment or "(" in segment:
        cleaned = re.sub(r"[()]", " ", segment)
        parts = [part.strip() for part in re.split(r"[;,]", cleaned) if part.strip()]
        if not parts:
            parts = [cleaned.strip()]
        if len(parts) == 1:
            words = parts[0].split()
            if (
                2 <= len(words) <= 3
                and looks_like_make_word(words[0])
                and all(word[:1].isupper() or word.isupper() for word in words[1:])
            ):
                return True
        if len(parts) == 2 and looks_like_make_word(parts[0].split()[0]) and word_count(parts[1]) <= 3:
            return True

    words = segment.split()
    if not words or len(words) > 3:
        return False
    if len(words) == 1:
        return looks_like_make_word(words[0])
    if len(words) == 2:
        first = words[0].strip(".,;:")
        second = words[1].strip(".,;:")
        # ``ESS ESS``, ``H Guru``, ``Mather Platt``, ``Unik Brand``
        if looks_like_make_word(first) and looks_like_make_word(second):
            return True
        # Trade-name pair used in fire make lists.
        if first.casefold() == "system" and second.casefold() == "sensor":
            return True
        if looks_like_make_word(first) and second.casefold() in {
            "brand",
            "ltd",
            "limited",
            "pvt",
            "co",
            "company",
            "italy",
            "spain",
            "germany",
        }:
            return True
        if max(len(first), len(second)) <= 8 and looks_like_make_word(first):
            return looks_like_make_word(second) or second[:1].isupper()
        peeled_description, peeled_makes = peel_fused_segment_boundary(segment)
        if peeled_makes and peeled_description != segment:
            return False
        return False
    if has_lowercase_letters(segment) and uppercase_letter_ratio(segment) < 0.7:
        return False
    return uppercase_letter_ratio(segment) >= 0.7 and all(
        looks_like_make_word(word) for word in words
    )


def looks_like_description_segment(segment: str) -> bool:
    """Return True when text is more likely a material description than a make."""
    segment = segment.strip()
    if not segment:
        return False
    if has_lowercase_letters(segment) and word_count(segment) >= 2:
        return True
    if word_count(segment) >= 4:
        return True
    if _SPEC_PUNCTUATION.search(segment) and word_count(segment) >= 3:
        return True
    if _ABBREVIATION.search(segment) and word_count(segment) >= 2:
        return True
    if word_count(segment) >= 2 and uppercase_letter_ratio(segment) < 0.95:
        return True
    return not looks_like_make_token(segment)


def peel_boundary_segment(segment: str, *, allow_long_segment: bool = False) -> tuple[str, list[str]]:
    """Split the last description segment from the first make at a slash boundary."""
    words = segment.split()
    if len(words) < 2:
        return segment, []

    if not allow_long_segment and len(words) >= 4:
        if not (
            looks_like_make_word(words[-1].strip(".,;:"))
            and looks_like_description_segment(" ".join(words[:-1]))
        ):
            return segment, []
        return peel_trailing_make_word(segment)

    if allow_long_segment:
        remainder, makes = peel_trailing_make_word(segment)
        if makes:
            return remainder, makes
        return segment, []

    return peel_trailing_make_word(segment)
