"""Integration-level actions, registered once in async_setup.

Handlers resolve their config entry at call time (never capturing one
entry's API key at registration) and import the per-service implementation
lazily, so an unconfigured service costs nothing at startup.
"""
from __future__ import annotations

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.core import (
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
    callback,
)
from homeassistant.exceptions import ServiceValidationError

from .const import CONF_ENTRY_TYPE, DOMAIN, ENTRY_AIRKOREA, ENTRY_PHARMACY


def _loaded_entry(hass: HomeAssistant, etype: str) -> ConfigEntry:
    for entry in hass.config_entries.async_entries(DOMAIN):
        if (entry.data.get(CONF_ENTRY_TYPE) == etype
                and entry.state is ConfigEntryState.LOADED):
            return entry
    raise ServiceValidationError(f"No loaded {etype} entry is configured")


async def _search_pharmacy(call: ServiceCall) -> ServiceResponse:
    from .pharmacy.services import async_search_pharmacy
    return await async_search_pharmacy(call, _loaded_entry(call.hass, ENTRY_PHARMACY))


async def _list_nearby_pharmacies(call: ServiceCall) -> ServiceResponse:
    from .pharmacy.services import async_list_nearby_pharmacies
    return await async_list_nearby_pharmacies(call)


async def _living_index_forecast(call: ServiceCall) -> ServiceResponse:
    from .airkorea.services import async_living_index_forecast
    return await async_living_index_forecast(call, _loaded_entry(call.hass, ENTRY_AIRKOREA))


@callback
def async_setup_services(hass: HomeAssistant) -> None:
    hass.services.async_register(
        DOMAIN, "search_pharmacy", _search_pharmacy,
        schema=vol.Schema({
            vol.Required("region"): str,
            vol.Optional("district", default=""): str,
            vol.Optional("count", default=10): vol.Coerce(int),
        }),
        supports_response=SupportsResponse.ONLY,
    )
    hass.services.async_register(
        DOMAIN, "list_nearby_pharmacies", _list_nearby_pharmacies,
        schema=vol.Schema({}),
        supports_response=SupportsResponse.ONLY,
    )
    hass.services.async_register(
        DOMAIN, "get_living_index_forecast", _living_index_forecast,
        schema=vol.Schema({
            vol.Required("index_type", default="uv"): vol.In(
                {"uv": "자외선지수", "stagnation": "대기정체지수"}),
            vol.Optional("region", default=""): str,
        }),
        supports_response=SupportsResponse.ONLY,
    )
