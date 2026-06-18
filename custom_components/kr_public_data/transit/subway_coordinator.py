"""Subway arrival coordinator - uses bulk API, shared per station."""
from __future__ import annotations
import logging
from datetime import timedelta
from typing import Any
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from . import SUBWAY_SCAN_INTERVAL
from .subway_api import fetch_bulk_arrivals, filter_arrivals

_LOGGER = logging.getLogger(__name__)

class SubwayCoordinator(DataUpdateCoordinator[dict[str, list[dict[str, Any]]]]):
    """One coordinator per station - fetches bulk, filters per direction/line."""
    def __init__(self, hass: HomeAssistant, api_key: str, station: str,
                 subscriptions: list[dict]) -> None:
        super().__init__(hass, _LOGGER, name=f"subway_{station}",
                         update_interval=timedelta(seconds=SUBWAY_SCAN_INTERVAL))
        self._api_key = api_key
        self._station = station
        self._session = async_get_clientsession(hass)
        self.subscriptions = subscriptions  # [{"direction": ..., "line_id": ...}, ...]

    async def _async_update_data(self):
        try:
            raw = await fetch_bulk_arrivals(self._session, self._api_key, self._station)
        except Exception as err:
            raise UpdateFailed(f"Subway API error: {err}") from err

        result = {}
        for sub in self.subscriptions:
            direction = sub.get("direction")
            if not direction:
                continue
            key = f"{direction}_{sub.get('line_id', '')}"
            result[key] = filter_arrivals(raw, direction, sub.get("line_id"))
        return result
