"""Weather warning coordinator."""
from __future__ import annotations
import logging
from datetime import timedelta
from typing import Any
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from . import WARNING_SCAN_SEC, WARNING_TYPES, EVENT_TYPE_NONE
from .api import fetch_warning

_LOGGER = logging.getLogger(__name__)

class WeatherWarningCoordinator(DataUpdateCoordinator[dict[str, dict[int, dict[str, Any]]]]):
    """Fetches warnings for ALL configured areas in one coordinator."""
    def __init__(self, hass: HomeAssistant, api_key: str, area_codes: list[str]) -> None:
        super().__init__(hass, _LOGGER, name="kr_weather",
                         update_interval=timedelta(seconds=WARNING_SCAN_SEC))
        self._api_key = api_key
        self._area_codes = area_codes
        self._session = async_get_clientsession(hass)

    async def _async_update_data(self):
        results: dict[str, dict[int, dict[str, Any]]] = {}
        total = 0
        failed = 0
        last_err: Exception | None = None
        for ac in self._area_codes:
            results[ac] = {}
            for wt in WARNING_TYPES:
                total += 1
                try:
                    results[ac][wt] = await fetch_warning(self._session, self._api_key, ac, wt)
                except Exception as e:
                    failed += 1
                    last_err = e
                    _LOGGER.debug("Weather warning fetch failed area=%s type=%s: %s", ac, wt, e)
                    results[ac][wt] = {"event_type": EVENT_TYPE_NONE, "raw": None}
        # If every single fetch failed, surface a real error so the entry
        # shows "unavailable" instead of pretending all warnings are clear.
        if total > 0 and failed == total:
            raise UpdateFailed(f"기상특보 API 호출 실패: {last_err}") from last_err
        return results
