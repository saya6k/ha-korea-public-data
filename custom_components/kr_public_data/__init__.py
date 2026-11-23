"""한국 공공데이터 - unified Korean public data integration."""
from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.typing import ConfigType

from .const import (
    CONF_ENTRY_TYPE,
    DOMAIN,
    ENTRY_AIRKOREA,
    ENTRY_ARISU,
    ENTRY_BUS,
    ENTRY_DISASTER,
    ENTRY_EARTHQUAKE,
    ENTRY_FUEL,
    ENTRY_GASAPP,
    ENTRY_KEPCO,
    ENTRY_KMA_WEATHER,
    ENTRY_PHARMACY,
    ENTRY_SAFETY_ALERT,
    ENTRY_SCHOOL,
    ENTRY_TRANSIT,
    ENTRY_WEATHER,
)
from .llm_api import async_register_llm_api
from .services import async_setup_services

PLATFORM_MAP = {
    ENTRY_WEATHER: [Platform.EVENT, Platform.CALENDAR, Platform.BINARY_SENSOR],
    ENTRY_TRANSIT: [Platform.SENSOR, Platform.BINARY_SENSOR],
    ENTRY_FUEL: [Platform.SENSOR],
    ENTRY_SCHOOL: [Platform.SENSOR, Platform.CALENDAR],
    ENTRY_DISASTER: [Platform.SENSOR, Platform.EVENT, Platform.GEO_LOCATION],
    ENTRY_SAFETY_ALERT: [Platform.BINARY_SENSOR, Platform.SENSOR, Platform.EVENT],
    ENTRY_KEPCO: [Platform.SENSOR],
    ENTRY_GASAPP: [Platform.SENSOR],
    ENTRY_ARISU: [Platform.SENSOR],
    ENTRY_PHARMACY: [Platform.SENSOR, Platform.BINARY_SENSOR],
    ENTRY_AIRKOREA: [Platform.SENSOR, Platform.BINARY_SENSOR, Platform.EVENT, Platform.CALENDAR],
    ENTRY_KMA_WEATHER: [Platform.WEATHER],
    ENTRY_EARTHQUAKE: [Platform.EVENT],
    ENTRY_BUS: [Platform.SENSOR, Platform.BINARY_SENSOR],
}

_LOGGER = logging.getLogger(__name__)

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    async_setup_services(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    etype = entry.data[CONF_ENTRY_TYPE]
    store: dict = {}

    if etype == ENTRY_WEATHER:
        from .weather.cleanup import async_cleanup_stale_weather_entities
        from .weather.coordinator import WeatherWarningCoordinator
        api_key = entry.data["api_key"]
        # 특보구역 per subentry; legacy entries keep area_codes in entry data.
        areas = {sub_id: sub.data["area_code"]
                 for sub_id, sub in entry.subentries.items()}
        area_codes = list(areas.values()) or entry.data.get("area_codes", [])
        c = WeatherWarningCoordinator(hass, entry, api_key, area_codes)
        await c.async_config_entry_first_refresh()
        store = {"coordinator": c, "area_codes": area_codes, "areas": areas}
        async_cleanup_stale_weather_entities(hass, entry, area_codes)

    elif etype == ENTRY_TRANSIT:
        from .resilience import async_first_refresh_all
        from .transit import line_directions
        from .transit.subway_coordinator import SubwayCoordinator
        seoul_key = entry.data.get("seoul_api_key", "")
        # 역 per subentry: one coordinator per station, subscribed to both
        # directions of every selected line.
        station_subs: dict = {}
        for sub_id, sub in entry.subentries.items():
            station = sub.data["station"]
            subscriptions = [{"direction": d, "line_id": lid}
                             for lid in sub.data.get("lines", [])
                             for d in line_directions(lid)]
            station_subs[sub_id] = {
                "station": station, "lines": sub.data.get("lines", []),
                "coordinator": SubwayCoordinator(hass, entry, seoul_key, station,
                                                 subscriptions)}
        sc = {info["station"]: info["coordinator"]
              for info in station_subs.values()}
        legacy_items: list = []
        if not station_subs:
            # legacy entry: subway_items with direction/line filters
            legacy_items = entry.data.get("subway_items", [])
            sg: dict[str, list] = {}
            for item in legacy_items:
                sg.setdefault(item["station"], []).append(item)
            sc = {station: SubwayCoordinator(hass, entry, seoul_key, station, subs)
                  for station, subs in sg.items()}
        await async_first_refresh_all(list(sc.values()), "subway")
        store = {"subway_coords": sc, "station_subs": station_subs,
                 "subway_items": legacy_items}

    elif etype == ENTRY_FUEL:
        from .fuel.cleanup import async_cleanup_stale_fuel_entities
        from .fuel.coordinator import FuelCoordinator
        api_key = entry.data.get("opinet_api_key") or entry.data.get("api_key", "")
        # 지역(시도) per subentry, 유종은 그 안의 목록; 레거시 엔트리는 configs를 그대로 사용.
        configs = [{"sido_code": sub.data["sido_code"], "fuel_code": f}
                   for sub in entry.subentries.values()
                   for f in sub.data.get("fuel_codes", [])]
        if not configs:
            configs = entry.data.get("configs", [])
        if not configs and "sido_code" in entry.data:
            configs = [{"sido_code": entry.data["sido_code"], "fuel_code": entry.data["fuel_code"]}]
        c = FuelCoordinator(hass, entry, api_key, configs)
        await c.async_config_entry_first_refresh()
        store = {"coordinator": c, "configs": configs}
        async_cleanup_stale_fuel_entities(hass, entry, configs)

    elif etype == ENTRY_SCHOOL:
        from .resilience import async_first_refresh_all
        from .school.coordinator import SchoolCoordinator
        api_key = entry.data.get("neis_api_key") or entry.data.get("api_key", "")
        # 학교 per subentry: one coordinator per school.
        school_subs = {sub_id: {"data": sub.data,
                                 "coordinator": SchoolCoordinator(
                                     hass, entry, api_key, sub.data, sub_id)}
                       for sub_id, sub in entry.subentries.items()}
        if school_subs:
            await async_first_refresh_all(
                [info["coordinator"] for info in school_subs.values()], "school")
            # "coordinator" is a single-school fallback for callers that
            # don't disambiguate by name; llm/school_tool.py picks the
            # right one itself via store["school_subs"].
            first = next(iter(school_subs.values()))
            store = {"school_subs": school_subs, "coordinator": first["coordinator"]}
        else:
            # legacy entry: single school lives directly in entry.data
            c = SchoolCoordinator(hass, entry, api_key, entry.data, entry.entry_id)
            await c.async_config_entry_first_refresh()
            store = {"coordinator": c}

    elif etype == ENTRY_DISASTER:
        from .disaster.coordinator import DisasterCoordinator
        api_key = entry.data.get("safety_api_key") or entry.data["api_key"]
        c = DisasterCoordinator(hass, entry, api_key)
        await c.async_config_entry_first_refresh()
        # One shared fetch; each 시군구 subentry filters in its entities.
        regions = {sub_id: dict(sub.data) for sub_id, sub in entry.subentries.items()}
        store = {"coordinator": c, "regions": regions,
                 "region": entry.data.get("region_filter", "")}

    elif etype == ENTRY_SAFETY_ALERT:
        from .safety_alert.cleanup import async_cleanup_stale_safety_alert_entities
        from .safety_alert.coordinator import SafetyAlertCoordinator
        regions = entry.data.get("regions", [])
        if not regions and entry.data.get("area_code"):
            regions = [{"code": entry.data["area_code"], "name": entry.data.get("area_name", "")}]
        from .resilience import async_first_refresh_all
        coordinators = {region["code"]: SafetyAlertCoordinator(hass, entry, region["code"])
                        for region in regions}
        await async_first_refresh_all(list(coordinators.values()), "safety_alert")
        store = {"coordinators": coordinators, "regions": regions}
        async_cleanup_stale_safety_alert_entities(hass, entry, regions)

    elif etype == ENTRY_KEPCO:
        from homeassistant.exceptions import ConfigEntryAuthFailed

        from .kepco.coordinator import KepcoCoordinator
        from .kepco.exceptions import KepcoApiError, KepcoAuthError
        c = KepcoCoordinator(hass, entry, entry.data["username"], entry.data["password"])
        try:
            await c.async_login()
        except KepcoAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except (OSError, KepcoApiError) as err:
            # Network flakiness must not block the entry: the first refresh
            # logs in again and the coordinator retries on schedule.
            _LOGGER.debug("KEPCO login failed, leaving it to the first refresh: %s", err)
        await c.async_config_entry_first_refresh()
        store = {"coordinator": c}

    elif etype == ENTRY_GASAPP:
        from .gasapp.coordinator import GasAppCoordinator
        c = GasAppCoordinator(hass, entry, entry.data["token"],
                               entry.data["member_id"], entry.data["contract_num"])
        await c.async_config_entry_first_refresh()
        store = {"coordinator": c}

    elif etype == ENTRY_ARISU:
        from .arisu.coordinator import ArisuCoordinator
        c = ArisuCoordinator(
            hass, entry, entry.data["customer_number"], entry.data["customer_name"])
        await c.async_config_entry_first_refresh()
        store = {"coordinator": c}

    elif etype == ENTRY_PHARMACY:
        from .pharmacy.cleanup import async_cleanup_stale_pharmacy_entities
        from .pharmacy.coordinator import PharmacyCoordinator
        from .resilience import async_first_refresh_all
        api_key = entry.data["api_key"]
        # 지역은 entry.data["regions"]에 flat하게 저장 (subentry 없이 관리).
        regions = entry.data.get("regions")
        if regions is None:
            if entry.subentries:
                # 레거시: subentry 기반으로 만들어졌던 이전 버전의 약국 엔트리.
                regions = [dict(sub.data, subentry_id=sub_id)
                           for sub_id, sub in entry.subentries.items()]
            else:
                # 가장 오래된 레거시: 단일 지역(q0/q1) flat 엔트리.
                regions = [{"sido": entry.data.get("q0", ""), "sgg": entry.data.get("q1", "")}]
        coords = {i: PharmacyCoordinator(hass, entry, api_key, r.get("sido", ""), r.get("sgg", ""))
                  for i, r in enumerate(regions)}
        await async_first_refresh_all(list(coords.values()), "pharmacy")
        store = {"coordinators": coords, "coordinator": next(iter(coords.values())),
                 "regions": regions}
        async_cleanup_stale_pharmacy_entities(hass, entry, regions, coords)

    elif etype == ENTRY_AIRKOREA:
        from .airkorea.coordinator import AirKoreaCoordinator
        from .airkorea.repairs import async_check_stale_stations
        api_key = entry.data["api_key"]
        living_key = entry.data.get("living_api_key", "") or api_key
        # 측정소 per subentry; legacy entries keep stations in entry data.
        station_subs = {sub_id: dict(sub.data)
                        for sub_id, sub in entry.subentries.items()}
        stations = list(station_subs.values()) or entry.data.get("stations", [])
        sido = entry.data.get("sido", "서울")
        async_check_stale_stations(hass, entry, stations, sido)
        c = AirKoreaCoordinator(hass, entry, api_key, stations,
                                 living_api_key=living_key, sido=sido)
        await c.async_config_entry_first_refresh()
        store = {"coordinator": c, "stations": stations,
                 "station_subs": station_subs}

    elif etype == ENTRY_KMA_WEATHER:
        from .airkorea import SIDO_AREA_CODE
        from .kma_weather.coordinator import KMAWeatherCoordinator
        from .utils import sido_short_name
        api_key = entry.data["api_key"]
        # 시군구 region per subentry; legacy entries keep regions in entry data.
        region_subs = {sub_id: dict(sub.data)
                       for sub_id, sub in entry.subentries.items()}
        regions = list(region_subs.values()) or entry.data.get("regions", [])
        # Entries created while the config flow looked SIDO_AREA_CODE up by
        # full sido name stored area_no="" — recompute from the stored sido.
        area_no = entry.data.get("area_no", "") or SIDO_AREA_CODE.get(
            sido_short_name(entry.data.get("sido", "")), "")
        c = KMAWeatherCoordinator(hass, entry, api_key, regions,
            air_api_key=api_key,
            air_station=entry.data.get("air_station", ""),
            living_api_key=api_key,
            area_no=area_no,
        )
        await c.async_config_entry_first_refresh()
        store = {"coordinator": c, "regions": regions,
                 "region_subs": region_subs}

    elif etype == ENTRY_EARTHQUAKE:
        from .earthquake.coordinator import EarthquakeCoordinator
        api_key = entry.data["api_key"]
        c = EarthquakeCoordinator(hass, entry, api_key)
        await c.async_config_entry_first_refresh()
        store = {"coordinator": c}

    elif etype == ENTRY_BUS:
        from .bus.city_coordinator import CityBusCoordinator
        from .bus.intercity_coordinator import IntercityBusCoordinator
        from .bus.seoul_coordinator import SeoulBusCoordinator
        from .resilience import async_first_refresh_all
        service_key = entry.data.get("api_key") or entry.data.get("service_key", "")
        # 정류장 per subentry: one coordinator per stop, subscribed to every
        # selected route at that stop. All stops share the one "city_bus_stop"
        # subentry type; sub.data["source"] ("tago" | "seoul") — set by the
        # config flow based on the chosen city — picks the coordinator/API
        # (ws.bus.go.kr reuses the same service_key, verified live it
        # authenticates there without a separate 활용신청).
        stop_subs: dict = {}
        # 구간(출발-도착 터미널) per subentry: 고속/시외버스도 하나의
        # "intercity_bus_route" subentry type을 공유하고, source("express"|
        # "intercity")로 API만 구분한다.
        route_subs: dict = {}
        for sub_id, sub in entry.subentries.items():
            if sub.subentry_type == "intercity_bus_route":
                route_subs[sub_id] = {
                    "depTerminalName": sub.data["depTerminalName"],
                    "arrTerminalName": sub.data["arrTerminalName"],
                    "grades": sub.data.get("grades", []),
                    "coordinator": IntercityBusCoordinator(
                        hass, entry, service_key, sub.data.get("queries", []),
                        sub.data.get("grades", [])),
                }
            elif sub.data.get("source") == "seoul":
                stop_subs[sub_id] = {
                    "kind": "seoul",
                    "nodeId": sub.data["nodeId"],
                    "nodeName": sub.data["nodeName"],
                    "routes": sub.data.get("routes", []),
                    "coordinator": SeoulBusCoordinator(
                        hass, entry, service_key, sub.data["nodeId"],
                        [r["routeId"] for r in sub.data.get("routes", [])]),
                }
            else:
                stop_subs[sub_id] = {
                    "kind": "tago",
                    "cityCode": sub.data["cityCode"],
                    "nodeId": sub.data["nodeId"],
                    "nodeName": sub.data["nodeName"],
                    "routes": sub.data.get("routes", []),
                    "coordinator": CityBusCoordinator(
                        hass, entry, service_key, sub.data["cityCode"], sub.data["nodeId"],
                        [r["routeId"] for r in sub.data.get("routes", [])]),
                }
        sc = {info["nodeId"]: info["coordinator"] for info in stop_subs.values()}
        all_coords = list(sc.values()) + [info["coordinator"] for info in route_subs.values()]
        await async_first_refresh_all(all_coords, "bus")
        route_by_name = {f"{info['depTerminalName']}→{info['arrTerminalName']}": info
                         for info in route_subs.values()}
        store = {"city_bus_coords": sc, "stop_subs": stop_subs,
                 "route_subs": route_subs, "intercity_bus_by_name": route_by_name}

    entry.runtime_data = store
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORM_MAP.get(etype, []))
    async_register_llm_api(hass, entry, etype)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    etype = entry.data.get(CONF_ENTRY_TYPE)
    return await hass.config_entries.async_unload_platforms(
        entry, PLATFORM_MAP.get(etype, []))

