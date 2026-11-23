"""AirKorea stale-station repair contracts; run with HA 2026.11+ and pytest installed."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from custom_components.kr_public_data.airkorea import STATIONS_BY_SIDO, repairs

_ENTRY = SimpleNamespace(entry_id="E1")


def _run(stations, default_sido="서울"):
    with patch.object(repairs.ir, "async_create_issue") as create, \
            patch.object(repairs.ir, "async_delete_issue") as delete:
        repairs.async_check_stale_stations(None, _ENTRY, stations, default_sido)
    return create, delete


def test_flags_district_names_from_the_old_table():
    create, delete = _run([{"sido": "부산", "stationName": "중구"},
                           {"sido": "경기", "stationName": "수원"},
                           {"sido": "서울", "stationName": "중구"}])
    delete.assert_not_called()
    kwargs = create.call_args.kwargs
    assert create.call_args.args[2] == "airkorea_stale_stations_E1"
    assert kwargs["translation_placeholders"] == {"stations": "부산 중구, 경기 수원"}
    assert kwargs["config_entry_id"] == "E1"


def test_keeps_real_stations_including_old_table_survivors():
    # 파주/공주/연동 were in the old table and are real stations.
    create, delete = _run([{"sido": "경기", "stationName": "파주"},
                           {"sido": "충남", "stationName": "공주"},
                           {"sido": "제주", "stationName": "연동"},
                           {"sido": "부산", "stationName": "광복동"}])
    create.assert_not_called()
    delete.assert_called_once()


def test_legacy_stations_use_the_entry_sido():
    create, _ = _run([{"stationName": "해운대구"}], default_sido="부산")
    assert create.call_args.kwargs["translation_placeholders"] == {"stations": "부산 해운대구"}


def test_no_flagged_name_is_a_current_station_in_its_sido():
    for sido, names in repairs._PRE_86_NON_STATIONS.items():
        assert not names & set(STATIONS_BY_SIDO.get(sido, [])), sido
