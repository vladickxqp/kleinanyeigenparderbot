"""Central registry mapping :class:`SiteName` to a parser instance.

Parsers register themselves via the :func:`register_parser` class decorator, so
adding a new marketplace is a single-file change with zero edits to the core.
"""

from __future__ import annotations

from collections.abc import Iterator

from loguru import logger

from app.database.models.enums import SiteName
from app.parsers.base import BaseParser


class ParserRegistry:
    """Holds one singleton parser instance per registered site."""

    def __init__(self) -> None:
        self._parsers: dict[SiteName, BaseParser] = {}

    def register(self, parser_cls: type[BaseParser]) -> type[BaseParser]:
        instance = parser_cls()
        if instance.site in self._parsers:
            logger.warning("Parser for {} already registered; overriding", instance.site)
        self._parsers[instance.site] = instance
        logger.debug("Registered parser {} ({})", parser_cls.__name__, instance.site)
        return parser_cls

    def get(self, site: SiteName) -> BaseParser | None:
        return self._parsers.get(site)

    def resolve(self, sites: list[SiteName] | None) -> list[BaseParser]:
        """Return parsers for the given sites, or all parsers if empty/None."""
        if not sites:
            return list(self._parsers.values())
        return [self._parsers[s] for s in sites if s in self._parsers]

    def __iter__(self) -> Iterator[BaseParser]:
        return iter(self._parsers.values())

    def __len__(self) -> int:
        return len(self._parsers)

    @property
    def available_sites(self) -> list[SiteName]:
        return list(self._parsers.keys())


#: Module-level singleton registry.
registry = ParserRegistry()


def register_parser(parser_cls: type[BaseParser]) -> type[BaseParser]:
    """Class decorator that registers a parser on the global registry."""
    return registry.register(parser_cls)


def get_parser(site: SiteName) -> BaseParser | None:
    return registry.get(site)


def site_label(site: SiteName | str) -> str:
    """The marketplace's own spelling of its name, for anything a user reads.

    Title-casing the slug turns "autoscout24" into "Autoscout24" and
    "ebay" into "Ebay" — every parser already carries how its site writes
    itself, so ask it rather than guess.
    """
    if not isinstance(site, SiteName):
        try:
            site = SiteName(site)
        except ValueError:
            return str(site).title()
    parser = registry.get(site)
    return parser.label if parser is not None else site.value.title()


def iter_parsers() -> Iterator[BaseParser]:
    return iter(registry)
