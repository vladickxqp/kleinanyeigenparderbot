"""Pluggable marketplace parsers.

Importing this package eagerly imports every module under ``sites/`` so that the
``@register_parser`` decorators run and populate the registry.
"""

from __future__ import annotations

import importlib
import pkgutil

from app.parsers.base import BaseParser
from app.parsers.registry import (
    ParserRegistry,
    get_parser,
    iter_parsers,
    register_parser,
    registry,
)
from app.parsers.schemas import ParsedListing, SearchQuery


def _autodiscover_sites() -> None:
    """Import all modules in ``app.parsers.sites`` to trigger registration."""
    from app.parsers import sites  # local import to avoid cycles

    for module_info in pkgutil.iter_modules(sites.__path__):
        importlib.import_module(f"{sites.__name__}.{module_info.name}")


_autodiscover_sites()

__all__ = [
    "BaseParser",
    "ParsedListing",
    "ParserRegistry",
    "SearchQuery",
    "get_parser",
    "iter_parsers",
    "register_parser",
    "registry",
]
