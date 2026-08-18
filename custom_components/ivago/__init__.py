"""The IVAGO Afvalkalender integration."""

from __future__ import annotations

import logging

import aiohttp

from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.aiohttp_client import async_create_clientsession
from homeassistant.helpers.event import async_track_time_change

from .api import IvagoApi
from .const import CONF_NUMBER, CONF_STREET
from .coordinator import IvagoConfigEntry, IvagoCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.SENSOR, Platform.CALENDAR]


async def async_setup_entry(hass: HomeAssistant, entry: IvagoConfigEntry) -> bool:
    """Set up IVAGO from a config entry."""
    # Every address needs its own cookie jar: IVAGO binds the address to the
    # server-side session referenced by the cookie.
    session = async_create_clientsession(hass, cookie_jar=aiohttp.CookieJar())
    api = IvagoApi(session, entry.data[CONF_STREET], str(entry.data[CONF_NUMBER]))

    coordinator = IvagoCoordinator(hass, entry, api)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator

    # Re-evaluate "today / tomorrow / days until" right after midnight without
    # hitting the API again.
    @callback
    def _midnight(_now) -> None:
        coordinator.async_update_listeners()

    entry.async_on_unload(
        async_track_time_change(hass, _midnight, hour=0, minute=0, second=10)
    )

    # Options (interval / lookahead) are read at setup -> reload on change.
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def _async_update_listener(hass: HomeAssistant, entry: IvagoConfigEntry) -> None:
    """Reload the entry when options change."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: IvagoConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
