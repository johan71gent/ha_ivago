"""Config, reconfigure and options flow for the IVAGO integration."""

from __future__ import annotations

import logging
from typing import Any

import aiohttp
import voluptuous as vol

from homeassistant.config_entries import (
    SOURCE_RECONFIGURE,
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import callback
from homeassistant.data_entry_flow import AbortFlow
from homeassistant.helpers.aiohttp_client import (
    async_create_clientsession,
    async_get_clientsession,
)
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .api import (
    IvagoApi,
    IvagoConnectionError,
    IvagoError,
    IvagoInvalidAddress,
    IvagoNoData,
)
from .const import (
    CONF_LOOKAHEAD_DAYS,
    CONF_NUMBER,
    CONF_SCAN_INTERVAL_HOURS,
    CONF_STREET,
    CONF_STREET_QUERY,
    CONF_UPCOMING_DAYS,
    DEFAULT_LOOKAHEAD_DAYS,
    DEFAULT_SCAN_INTERVAL_HOURS,
    DEFAULT_UPCOMING_DAYS,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)

STEP_ADDRESS_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_STREET_QUERY): TextSelector(
            TextSelectorConfig(type=TextSelectorType.TEXT, autocomplete="street-address")
        ),
        vol.Required(CONF_NUMBER): TextSelector(
            TextSelectorConfig(type=TextSelectorType.TEXT)
        ),
    }
)


def _unique_id(street: str, number: str) -> str:
    return f"{street}|{number}".casefold()


class IvagoConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the config flow for IVAGO (initial setup + reconfigure)."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialise."""
        self._number: str = ""
        self._matches: list[str] = []

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> IvagoOptionsFlow:
        """Return the options flow."""
        return IvagoOptionsFlow()

    # ------------------------------------------------------------------ #
    # Entry points
    # ------------------------------------------------------------------ #
    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Initial setup: ask for street + house number."""
        return await self._async_step_address("user", user_input)

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Reconfigure: change the address of an existing entry."""
        return await self._async_step_address("reconfigure", user_input)

    # ------------------------------------------------------------------ #
    # Shared address step
    # ------------------------------------------------------------------ #
    @property
    def _is_reconfigure(self) -> bool:
        return self.source == SOURCE_RECONFIGURE

    def _address_defaults(self) -> dict[str, Any]:
        """Prefill values (current address when reconfiguring)."""
        if self._is_reconfigure:
            entry = self._get_reconfigure_entry()
            return {
                CONF_STREET_QUERY: entry.data[CONF_STREET],
                CONF_NUMBER: entry.data[CONF_NUMBER],
            }
        return {}

    def _show_address_form(
        self,
        step_id: str,
        errors: dict[str, str],
        values: dict[str, Any] | None = None,
    ) -> ConfigFlowResult:
        return self.async_show_form(
            step_id=step_id,
            data_schema=self.add_suggested_values_to_schema(
                STEP_ADDRESS_SCHEMA, values or self._address_defaults()
            ),
            errors=errors,
        )

    async def _async_step_address(
        self, step_id: str, user_input: dict[str, Any] | None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            query = user_input[CONF_STREET_QUERY].strip()
            self._number = str(user_input[CONF_NUMBER]).strip()
            # The autocomplete endpoint only matches on the part before "(".
            search_term = query.split("(")[0].strip()

            try:
                matches = await IvagoApi.async_search_streets(
                    async_get_clientsession(self.hass), search_term
                )
            except IvagoConnectionError:
                errors["base"] = "cannot_connect"
            else:
                if not matches:
                    errors[CONF_STREET_QUERY] = "street_not_found"
                else:
                    exact = [m for m in matches if m.casefold() == query.casefold()]
                    if len(exact) == 1 or len(matches) == 1:
                        street = exact[0] if exact else matches[0]
                        if await self._async_validate(street, errors):
                            return self._async_finish(street)
                        return self._show_address_form(step_id, errors, user_input)
                    self._matches = matches
                    return await self.async_step_select_street()

        return self._show_address_form(step_id, errors, user_input)

    async def async_step_select_street(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Let the user pick one of several matching streets."""
        errors: dict[str, str] = {}
        if user_input is not None:
            street = user_input[CONF_STREET]
            if await self._async_validate(street, errors):
                return self._async_finish(street)

        schema = vol.Schema(
            {
                vol.Required(CONF_STREET): SelectSelector(
                    SelectSelectorConfig(
                        options=[
                            SelectOptionDict(value=m, label=m) for m in self._matches
                        ],
                        mode=SelectSelectorMode.DROPDOWN,
                    )
                )
            }
        )
        return self.async_show_form(
            step_id="select_street",
            data_schema=schema,
            errors=errors,
            description_placeholders={"number": self._number},
        )

    # ------------------------------------------------------------------ #
    # Validation / finish
    # ------------------------------------------------------------------ #
    async def _async_validate(self, street: str, errors: dict[str, str]) -> bool:
        """Check uniqueness and validate the address against IVAGO.

        Fills ``errors`` and returns False on failure. May raise AbortFlow
        when the address is already configured by another entry.
        """
        uid = _unique_id(street, self._number)
        await self.async_set_unique_id(uid)
        if self._is_reconfigure:
            current = self._get_reconfigure_entry()
            for entry in self._async_current_entries(include_ignore=False):
                if entry.entry_id != current.entry_id and entry.unique_id == uid:
                    raise AbortFlow("already_configured")
        else:
            self._abort_if_unique_id_configured()

        session = async_create_clientsession(
            self.hass, cookie_jar=aiohttp.CookieJar()
        )
        try:
            await IvagoApi(session, street, self._number).async_validate()
        except IvagoInvalidAddress:
            errors["base"] = "invalid_address"
        except IvagoNoData:
            errors["base"] = "no_data"
        except IvagoConnectionError:
            errors["base"] = "cannot_connect"
        except IvagoError:  # pragma: no cover - defensive
            _LOGGER.exception("Unexpected IVAGO error")
            errors["base"] = "unknown"
        finally:
            await session.close()
        return not errors

    @callback
    def _async_finish(self, street: str) -> ConfigFlowResult:
        """Create the entry, or update + reload it when reconfiguring."""
        title = f"{street} {self._number}"
        data = {CONF_STREET: street, CONF_NUMBER: self._number}
        if self._is_reconfigure:
            return self.async_update_reload_and_abort(
                self._get_reconfigure_entry(),
                unique_id=_unique_id(street, self._number),
                title=title,
                data=data,
            )
        return self.async_create_entry(title=title, data=data)


class IvagoOptionsFlow(OptionsFlow):
    """Options: update interval and how far ahead to fetch."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show / save the options."""
        if user_input is not None:
            return self.async_create_entry(
                data={
                    CONF_SCAN_INTERVAL_HOURS: int(user_input[CONF_SCAN_INTERVAL_HOURS]),
                    CONF_LOOKAHEAD_DAYS: int(user_input[CONF_LOOKAHEAD_DAYS]),
                    CONF_UPCOMING_DAYS: int(user_input[CONF_UPCOMING_DAYS]),
                }
            )

        options = self.config_entry.options
        schema = vol.Schema(
            {
                vol.Required(
                    CONF_SCAN_INTERVAL_HOURS,
                    default=options.get(
                        CONF_SCAN_INTERVAL_HOURS, DEFAULT_SCAN_INTERVAL_HOURS
                    ),
                ): NumberSelector(
                    NumberSelectorConfig(
                        min=1, max=48, step=1, mode=NumberSelectorMode.BOX,
                        unit_of_measurement="h",
                    )
                ),
                vol.Required(
                    CONF_LOOKAHEAD_DAYS,
                    default=options.get(CONF_LOOKAHEAD_DAYS, DEFAULT_LOOKAHEAD_DAYS),
                ): NumberSelector(
                    NumberSelectorConfig(
                        min=14, max=365, step=1, mode=NumberSelectorMode.BOX,
                        unit_of_measurement="d",
                    )
                ),
                vol.Required(
                    CONF_UPCOMING_DAYS,
                    default=options.get(CONF_UPCOMING_DAYS, DEFAULT_UPCOMING_DAYS),
                ): NumberSelector(
                    NumberSelectorConfig(
                        min=1, max=14, step=1, mode=NumberSelectorMode.BOX,
                        unit_of_measurement="d",
                    )
                ),
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)
