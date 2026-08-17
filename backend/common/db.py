"""Small DB helpers with types that basedpyright accepts without django-stubs."""
from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any, cast

from django.db import transaction
from django.db.models import Q


@contextmanager
def atomic() -> Iterator[None]:
    """Run ``transaction.atomic`` with a context-manager type checkers accept."""
    with cast(Any, transaction.atomic()):
        yield


def q(**kwargs: Any) -> Q:
    """Build a ``Q`` object (avoids false ``_negated`` errors without stubs)."""
    return cast(Q, Q(**kwargs))  # type: ignore[arg-type]


def q_or(left: Q, right: Q) -> Q:
    return cast(Q, left | right)  # type: ignore[operator]


def q_and(left: Q, right: Q) -> Q:
    return cast(Q, left & right)  # type: ignore[operator]
