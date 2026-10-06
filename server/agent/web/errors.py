"""Errors of the web tools. Messages are fixed text: only the type name is ever logged."""

from __future__ import annotations


class WebError(Exception):
    """A web request failed or was refused."""


class MissingKey(WebError):
    """The Tavily API key is not in the keyring."""


class WebHttpError(WebError):
    """The server answered with an unusable status."""


class WebParseError(WebError):
    """The response was not the expected shape or content type."""


class WebTooLarge(WebError):
    """The response exceeded its size cap."""


class WebRefused(WebError):
    """A URL or redirect was refused before or while fetching."""
