"""Minimal async client for the (unofficial) IVAGO pickup calendar API.

Flow (reverse engineered from https://www.ivago.be/nl/particulier/afval/ophaling):

1. ``POST /nl/particulier/afval/ophaling`` with the street + house number.
   The server stores the address in a Drupal session (``SSESS…`` cookie) and
   answers with a 303 redirect.  A 200 means the address was rejected.
2. ``GET /nl/particulier/garbage/pick-up/pickups?_format=json&start=<unix>&end=<unix>``
   using that session cookie returns a JSON list of pickups::

       [{"date": "2026-08-17", "label": "PMD",
         "classes": "PMD ivago-pmd", "url": "/nl/particulier/afval/gids/pmd"}, ...]

Streets can be looked up with ``GET /nl/particulier/autocomplete/garbage/streets?q=``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
import logging
from typing import Any

import aiohttp

from .const import URL_PICKUP_PAGE, URL_PICKUPS, URL_STREETS, USER_AGENT

_LOGGER = logging.getLogger(__name__)


class IvagoError(Exception):
    """Base error."""


class IvagoConnectionError(IvagoError):
    """Network / HTTP level error."""


class IvagoInvalidAddress(IvagoError):
    """The address was rejected by IVAGO."""


class IvagoNoData(IvagoError):
    """The address was accepted but no pickups were returned."""


@dataclass(frozen=True, slots=True)
class Pickup:
    """A single waste pickup."""

    date: date
    waste_type: str  # e.g. "PMD" (upper-case label from the API)
    url: str | None = None

    @classmethod
    def from_api(cls, item: dict[str, Any]) -> Pickup:
        """Create from an API dict."""
        return cls(
            date=date.fromisoformat(item["date"]),
            waste_type=str(item.get("label", "")).strip().upper(),
            url=item.get("url"),
        )


class IvagoApi:
    """Client bound to one address, keeping its own cookie session."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        street: str,
        number: str,
    ) -> None:
        """Initialise the client.

        ``session`` must have its own cookie jar (the address is stored
        server-side against the session cookie).
        """
        self._session = session
        self.street = street
        self.number = number
        self._has_session = False

    # ------------------------------------------------------------------ #
    # Streets
    # ------------------------------------------------------------------ #
    @staticmethod
    async def async_search_streets(
        session: aiohttp.ClientSession, query: str
    ) -> list[str]:
        """Return matching street names, e.g. ``["Veldstraat (GENT)"]``."""
        try:
            async with session.get(
                URL_STREETS,
                params={"q": query},
                headers={"User-Agent": USER_AGENT},
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                resp.raise_for_status()
                data = await resp.json(content_type=None)
        except (aiohttp.ClientError, TimeoutError) as err:
            raise IvagoConnectionError(str(err)) from err
        if not isinstance(data, list):
            return []
        return [str(item["value"]) for item in data if "value" in item]

    # ------------------------------------------------------------------ #
    # Session / address
    # ------------------------------------------------------------------ #
    async def async_set_address(self) -> None:
        """Submit the address so the server binds it to our session cookie."""
        payload = {
            "garbage_type": "",
            "ivago_loc": self.street,
            "number": self.number,
            "form_id": "garbage_address_form",
            "op": "Bekijk",
        }
        try:
            async with self._session.post(
                URL_PICKUP_PAGE,
                data=payload,
                headers={
                    "User-Agent": USER_AGENT,
                    "Referer": URL_PICKUP_PAGE,
                    "Origin": "https://www.ivago.be",
                },
                allow_redirects=False,
                timeout=aiohttp.ClientTimeout(total=20),
            ) as resp:
                status = resp.status
                if status >= 400:
                    raise IvagoConnectionError(f"HTTP {status} while setting address")
        except (aiohttp.ClientError, TimeoutError) as err:
            raise IvagoConnectionError(str(err)) from err

        # A successful submit answers with a 303 redirect back to the page.
        # A 200 means Drupal re-rendered the form with a validation error.
        if status != 303:
            self._has_session = False
            raise IvagoInvalidAddress(
                f"IVAGO rejected address {self.street!r} {self.number!r} (HTTP {status})"
            )
        self._has_session = True

    # ------------------------------------------------------------------ #
    # Pickups
    # ------------------------------------------------------------------ #
    async def _async_get_pickups_raw(
        self, start: date, end: date, waste_type: str = ""
    ) -> list[dict[str, Any]] | None:
        """GET pickups; return None on 403 (no/expired session)."""
        params = {
            "_format": "json",
            "type": waste_type,
            "start": str(_to_unix(start)),
            "end": str(_to_unix(end)),
        }
        try:
            async with self._session.get(
                URL_PICKUPS,
                params=params,
                headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
                timeout=aiohttp.ClientTimeout(total=20),
            ) as resp:
                if resp.status == 403:
                    return None
                if resp.status >= 400:
                    raise IvagoConnectionError(
                        f"HTTP {resp.status} while fetching pickups"
                    )
                data = await resp.json(content_type=None)
        except (aiohttp.ClientError, TimeoutError) as err:
            raise IvagoConnectionError(str(err)) from err
        if not isinstance(data, list):
            raise IvagoConnectionError(f"Unexpected payload: {data!r}")
        return data

    async def async_get_pickups(
        self, start: date, end: date, waste_type: str = ""
    ) -> list[Pickup]:
        """Return the pickups between ``start`` and ``end`` (inclusive)."""
        if not self._has_session:
            await self.async_set_address()

        data = await self._async_get_pickups_raw(start, end, waste_type)
        if not data:
            # 403 (session expired) or empty list (address dropped from the
            # session) -> re-submit the address once and retry.
            _LOGGER.debug(
                "Re-submitting IVAGO address for %s %s", self.street, self.number
            )
            await self.async_set_address()
            data = await self._async_get_pickups_raw(start, end, waste_type)
            if data is None:
                raise IvagoInvalidAddress("Session could not be established")

        pickups: list[Pickup] = []
        for item in data:
            try:
                pickups.append(Pickup.from_api(item))
            except (KeyError, ValueError, TypeError):
                _LOGGER.debug("Skipping unparsable pickup item: %r", item)
        pickups.sort(key=lambda p: (p.date, p.waste_type))
        return pickups

    async def async_validate(self) -> list[Pickup]:
        """Validate the address; raise IvagoNoData if it yields no pickups."""
        today = date.today()
        pickups = await self.async_get_pickups(
            today - timedelta(days=7), today + timedelta(days=120)
        )
        if not pickups:
            raise IvagoNoData("No pickups returned for this address")
        return pickups


def _to_unix(d: date) -> int:
    """Midnight UTC of ``d`` as unix timestamp (what the site's JS sends)."""
    return int(datetime.combine(d, time.min, tzinfo=timezone.utc).timestamp())
