"""Dynamic text heuristics for splitting descriptions and brand/make tokens.

Uses structural signals (case, length, punctuation, slash position) instead of
hardcoded domain word lists so PDF/Excel-derived text works across clients.
"""
from __future__ import annotations

import re

_SPEC_PUNCTUATION = re.compile(r"[&\-/()]")
_ABBREVIATION = re.compile(r"(?:\b[A-Z]\.)+[A-Z]?|\b[A-Z]\.[A-Z]\b")


def uppercase_letter_ratio(text: str) -> float:
    letters = [char for char in text if char.isalpha()]
    if not letters:
        return 0.0
    return sum(char.isupper() for char in letters) / len(letters)


def has_lowercase_letters(text: str) -> bool:
    return any(char.islower() for char in text)


def word_count(text: str) -> int:
    return len(text.split())


def looks_like_make_word(word: str) -> bool:
    """Return True when a single token is likely a brand/make name."""
    token = word.strip(".,;:")
    if not token or len(token) > 24:
        return False
    if has_lowercase_letters(token):
        return False
    letters = [char for char in token if char.isalpha()]
    if not letters:
        return False
    if all(char.isupper() for char in letters) and len(token) <= 5:
        return True
    if len(token) <= 3:
        return token.isalpha()
    return uppercase_letter_ratio(token) >= 0.75


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
    """Peel one trailing brand word from a description segment."""
    words = segment.split()
    if len(words) < 2:
        return segment, []
    last_word = words[-1].strip(".,;:")
    if not looks_like_make_word(last_word):
        return segment, []
    remainder = " ".join(words[:-1]).strip()
    if not remainder or not _looks_like_remainder_after_peel(remainder):
        return segment, []
    return remainder, [last_word]


def peel_fused_segment_boundary(segment: str) -> tuple[str, list[str]]:
    """Peel one trailing brand from a slash segment fused with description text."""
    words = segment.split()
    if len(words) < 2:
        return segment, []
    last_word = words[-1].strip(".,;:")
    if not looks_like_make_word(last_word):
        return segment, []
    remainder = " ".join(words[:-1]).strip()
    if not remainder or not _looks_like_remainder_after_peel(remainder):
        return segment, []
    return remainder, [last_word]


def looks_like_make_token(segment: str) -> bool:
    """Return True when a slash segment is likely one approved make."""
    segment = segment.strip()
    if not segment or len(segment) > 40:
        return False
    words = segment.split()
    if not words or len(words) > 3:
        return False
    if len(words) == 2:
        first = words[0].strip(".,;:")
        second = words[1].strip(".,;:")
        if max(len(first), len(second)) <= 7:
            return looks_like_make_word(first) and looks_like_make_word(second)
        peeled_description, peeled_makes = peel_fused_segment_boundary(segment)
        if peeled_makes and peeled_description != segment:
            return False
        return False
    if len(words) == 1:
        return looks_like_make_word(words[0])
    if has_lowercase_letters(segment):
        return False
    return uppercase_letter_ratio(segment) >= 0.85 and all(
        looks_like_make_word(word) for word in words
    )


def looks_like_description_segment(segment: str) -> bool:
    """Return True when text is more likely a material description than a make."""
    segment = segment.strip()
    if not segment:
        return False
    if has_lowercase_letters(segment):
        return True
    if word_count(segment) >= 4:
        return True
    if _SPEC_PUNCTUATION.search(segment):
        return True
    if _ABBREVIATION.search(segment):
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
