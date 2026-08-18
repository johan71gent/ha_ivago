"""DataUpdateCoordinator for IVAGO."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import IvagoApi, IvagoError, IvagoInvalidAddress, Pickup
from .const import (
    CONF_LOOKAHEAD_DAYS,
    CONF_SCAN_INTERVAL_HOURS,
    DEFAULT_LOOKAHEAD_DAYS,
    DEFAULT_SCAN_INTERVAL_HOURS,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)

type IvagoConfigEntry = ConfigEntry[IvagoCoordinator]


@dataclass
class IvagoData:
    """Processed pickup data."""

    pickups: list[Pickup] = field(default_factory=list)

    @property
    def waste_types(self) -> set[str]:
        """All waste types seen in the fetched window."""
        return {p.waste_type for p in self.pickups}

    def today(self) -> date:
        """Today's date in the HA local time zone."""
        return dt_util.now().date()

    def pickups_on(self, day: date) -> list[Pickup]:
        """Pickups on a given day."""
        return [p for p in self.pickups if p.date == day]

    def next_pickup_for(self, waste_type: str, from_day: date | None = None) -> Pickup | None:
        """Next (today or later) pickup of a waste type."""
        from_day = from_day or self.today()
        for p in self.pickups:  # sorted by date
            if p.waste_type == waste_type and p.date >= from_day:
                return p
        return None

    def next_pickups(self, from_day: date | None = None) -> list[Pickup]:
        """All pickups on the next collection day (today or later)."""
        from_day = from_day or self.today()
        upcoming = [p for p in self.pickups if p.date >= from_day]
        if not upcoming:
            return []
        first = upcoming[0].date
        return [p for p in upcoming if p.date == first]


class IvagoCoordinator(DataUpdateCoordinator[IvagoData]):
    """Fetches the IVAGO calendar periodically."""

    config_entry: IvagoConfigEntry

    def __init__(
        self, hass: HomeAssistant, entry: IvagoConfigEntry, api: IvagoApi
    ) -> None:
        """Initialise."""
        hours = int(entry.options.get(CONF_SCAN_INTERVAL_HOURS, DEFAULT_SCAN_INTERVAL_HOURS))
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN} {api.street} {api.number}",
            update_interval=timedelta(hours=hours),
        )
        self.api = api
        self.lookahead_days = int(
            entry.options.get(CONF_LOOKAHEAD_DAYS, DEFAULT_LOOKAHEAD_DAYS)
        )

    async def _async_update_data(self) -> IvagoData:
        today = dt_util.now().date()
        start = today - timedelta(days=1)
        end = today + timedelta(days=self.lookahead_days)
        try:
            pickups = await self.api.async_get_pickups(start, end)
        except IvagoInvalidAddress as err:
            raise UpdateFailed(f"IVAGO rejected the address: {err}") from err
        except IvagoError as err:
            raise UpdateFailed(f"Error talking to IVAGO: {err}") from err
        _LOGGER.debug("Fetched %d IVAGO pickups", len(pickups))
        return IvagoData(pickups=pickups)
