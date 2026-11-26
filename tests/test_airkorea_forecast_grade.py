"""AirKorea forecast bulletin grade helpers; no Home Assistant required."""
from __future__ import annotations

import importlib
import pathlib
import sys
import types


def _load_airkorea():
    repo = pathlib.Path(__file__).resolve().parents[1]
    inserted = []
    if "custom_components.kr_public_data" not in sys.modules:
        cc = types.ModuleType("custom_components")
        cc.__path__ = [str(repo / "custom_components")]
        kr = types.ModuleType("custom_components.kr_public_data")
        kr.__path__ = [str(repo / "custom_components" / "kr_public_data")]
        inserted = ["custom_components", "custom_components.kr_public_data"]
        sys.modules["custom_components"] = cc
        sys.modules["custom_components.kr_public_data"] = kr
    try:
        return importlib.import_module("custom_components.kr_public_data.airkorea")
    finally:
        for key in inserted:
            sys.modules.pop(key, None)


airkorea = _load_airkorea()

TODAY = "2026-11-24"
TOMORROW = "2026-11-25"
GYEONGI = "경기"
GOOD = "좋음"
NORMAL = "보통"
BAD = "나쁨"
VERY_BAD = "매우나쁨"
VERY_BAD_SPACED = "매우 나쁨"
INSPECTION = "점검"
EMPTY_ATTRS = {"region": "", "all_regions": {}, "data_time": "", "inform_cause": "",
               "inform_overall": ""}


def _item(code="PM10", data=TODAY, grade=f"경기남부 : {BAD}, 경기북부 : {NORMAL}",
          time="2026-11-24 23시 발표", cause="미세먼지 농도가 높습니다",
          overall="전 권역이 '좋음'~'보통'으로 예상됩니다") -> dict:
    """One getMinuDustFrcstDspth bulletin item, with all real fields."""
    return {
        "informCode": code,
        "informData": data,
        "informGrade": grade,
        "dataTime": time,
        "informCause": cause,
        "informOverall": overall,
    }


def test_forecast_region_grades_parses_pairs():
    assert airkorea.forecast_region_grades(_item()) == {
        "경기남부": BAD, "경기북부": NORMAL}


def test_forecast_region_grades_missing_field_is_empty():
    assert airkorea.forecast_region_grades({}) == {}


def test_first_subregion_in_bulletin_order_is_used():
    grade, attrs = airkorea.station_forecast_grade([_item()], GYEONGI, "PM10", TODAY)
    assert grade == BAD
    assert attrs["region"] == "경기남부"
    assert attrs["all_regions"] == {"경기남부": BAD, "경기북부": NORMAL}


def test_subregion_choice_ignores_bulletin_order():
    item = _item(grade=f"경기북부 : {NORMAL}, 경기남부 : {BAD}")
    grade, attrs = airkorea.station_forecast_grade([item], GYEONGI, "PM10", TODAY)
    assert (grade, attrs["region"]) == (BAD, "경기남부")


def test_exact_region_wins_over_subregions():
    item = _item(grade=f"경기 : {GOOD}, 경기남부 : {BAD}, 경기북부 : {NORMAL}")
    grade, attrs = airkorea.station_forecast_grade([item], GYEONGI, "PM10", TODAY)
    assert (grade, attrs["region"]) == (GOOD, GYEONGI)


def test_north_subregion_used_when_south_absent():
    item = _item(grade=f"경기북부 : {NORMAL}")
    assert airkorea.station_forecast_grade([item], GYEONGI, "PM10", TODAY)[0] == NORMAL


def test_gangwon_resolves_to_yeongdong_via_subregion_table():
    item = _item(grade=f"영동 : {GOOD}, 영서 : {NORMAL}")
    grade, attrs = airkorea.station_forecast_grade([item], "강원", "PM10", TODAY)
    assert (grade, attrs["region"]) == (GOOD, "영동")
    assert attrs["all_regions"] == {"영동": GOOD, "영서": NORMAL}


def test_addr_city_selects_gyeonggi_south():
    grade, attrs = airkorea.station_forecast_grade(
        [_item()], GYEONGI, "PM10", TODAY, addr="경기 성남시 분당구 정자동")
    assert (grade, attrs["region"]) == (BAD, "경기남부")


def test_addr_city_selects_gyeonggi_north():
    grade, attrs = airkorea.station_forecast_grade(
        [_item()], GYEONGI, "PM10", TODAY, addr="경기 고양시 일산동구")
    assert (grade, attrs["region"]) == (NORMAL, "경기북부")


def test_addr_city_selects_gangwon_yeongseo():
    item = _item(grade=f"영동 : {GOOD}, 영서 : {BAD}")
    grade, attrs = airkorea.station_forecast_grade(
        [item], "강원", "PM10", TODAY, addr="강원 원주시 반곡동")
    assert (grade, attrs["region"]) == (BAD, "영서")


def test_addr_from_other_sido_is_ignored():
    # 주소의 시도가 측정소 시도와 다르면 무시하고 표 기본값으로 폴백한다.
    item = _item(grade=f"영동 : {GOOD}, 영서 : {BAD}")
    grade, attrs = airkorea.station_forecast_grade(
        [item], "강원", "PM10", TODAY, addr="경기 성남시 분당구 정자동")
    assert (grade, attrs["region"]) == (GOOD, "영동")


def test_addr_unknown_city_falls_back_to_table_order():
    grade, attrs = airkorea.station_forecast_grade(
        [_item()], GYEONGI, "PM10", TODAY, addr="경기 미정시 어딘가")
    assert (grade, attrs["region"]) == (BAD, "경기남부")


# 경계 케이스: 공식 구분이 지리 직관과 갈리는 시군을,
# 그 안에서도 가장 헷갈리는 실제 주소로 고정한다.
def test_addr_boundary_pins_gyeonggi_membership():
    north = airkorea.station_forecast_grade(
        [_item()], GYEONGI, "PM10", TODAY, addr="경기 김포시 고촌읍")
    south = airkorea.station_forecast_grade(
        [_item()], GYEONGI, "PM10", TODAY, addr="경기 양평군 용문면")
    assert (north[0], north[1]["region"]) == (NORMAL, "경기북부")
    assert (south[0], south[1]["region"]) == (BAD, "경기남부")


def test_addr_boundary_pins_gangwon_membership():
    item = _item(grade=f"영동 : {GOOD}, 영서 : {BAD}")
    yeongdong = airkorea.station_forecast_grade(
        [item], "강원", "PM10", TODAY, addr="강원 태백시 혈동")
    yeongseo = airkorea.station_forecast_grade(
        [item], "강원", "PM10", TODAY, addr="강원 인제군 북면")
    assert (yeongdong[0], yeongdong[1]["region"]) == (GOOD, "영동")
    assert (yeongseo[0], yeongseo[1]["region"]) == (BAD, "영서")


def test_substring_fallback_for_unlisted_split():
    # 표에 없는 신규 분할이 생기면 substring으로 폴백한다.
    item = _item(grade=f"충북서부 : {GOOD}, 충북동부 : {BAD}")
    grade, attrs = airkorea.station_forecast_grade([item], "충북", "PM10", TODAY)
    assert (grade, attrs["region"]) == (GOOD, "충북서부")


def test_no_matching_region_returns_empty_attrs():
    item = _item(grade=f"서울 : {GOOD}")
    assert airkorea.station_forecast_grade([item], GYEONGI, "PM10", TODAY) == (None,
                                                                               EMPTY_ATTRS)


def test_select_forecast_item_prefers_latest_bulletin():
    early = _item(time="2026-11-24 11시 발표", grade=f"경기 : {GOOD}")
    late = _item(time="2026-11-24 23시 발표", grade=f"경기 : {BAD}")
    assert airkorea.select_forecast_item([early, late], "PM10", TODAY) is late


def test_unparseable_data_time_sorts_lowest():
    early = _item(time="발표시각 없음", grade=f"경기 : {BAD}")
    late = _item(time="2026-11-24 09시 발표", grade=f"경기 : {GOOD}")
    assert airkorea.station_forecast_grade([early, late], GYEONGI, "PM10", TODAY)[0] == GOOD


def test_pm10_and_pm25_are_independent():
    forecasts = [_item(code="PM10", grade=f"경기 : {BAD}"),
                 _item(code="PM25", grade=f"경기 : {GOOD}")]
    grades = [airkorea.station_forecast_grade(forecasts, GYEONGI, code, TODAY)[0]
              for code in ("PM10", "PM25")]
    assert grades == [BAD, GOOD]


def test_other_day_item_is_ignored():
    item = _item(data=TOMORROW, grade=f"경기 : {BAD}")
    assert airkorea.station_forecast_grade([item], GYEONGI, "PM10", TODAY)[0] is None


def test_missing_target_date_returns_empty_attrs():
    assert airkorea.station_forecast_grade([], GYEONGI, "PM10", TODAY) == (None, EMPTY_ATTRS)


def test_bulletin_metadata_in_attrs():
    _, attrs = airkorea.station_forecast_grade([_item()], GYEONGI, "PM10", TODAY)
    assert (attrs["data_time"], attrs["inform_cause"], attrs["inform_overall"]) == (
        "2026-11-24 23시 발표", "미세먼지 농도가 높습니다",
        "전 권역이 '좋음'~'보통'으로 예상됩니다")


def test_missing_overall_field_becomes_empty_string():
    item = _item(overall="")
    _, attrs = airkorea.station_forecast_grade([item], GYEONGI, "PM10", TODAY)
    assert attrs["inform_overall"] == ""


def test_grade_tokens_pass_through_verbatim():
    # 등급 토큰은 정규화 없이 원문 그대로 통과한다.
    for token in (VERY_BAD, VERY_BAD_SPACED, INSPECTION):
        assert airkorea.station_forecast_grade(
            [_item(grade=f"경기 : {token}")], GYEONGI, "PM10", TODAY)[0] == token


def test_unparseable_grade_pairs_are_skipped():
    # 콜론이 없는 쌍과 등급이 빈 쌍은 건너뛴다.
    assert airkorea.forecast_region_grades(
        _item(grade=f"경기남부 {BAD}, 경기북부 : {NORMAL}")) == {"경기북부": NORMAL}
    assert airkorea.forecast_region_grades(
        _item(grade=f"경기남부 : , 경기북부 : {NORMAL}")) == {"경기북부": NORMAL}


def test_empty_sido_does_not_match_every_region():
    item = _item(grade=f"경기 : {BAD}, 서울 : {GOOD}")
    assert airkorea.station_forecast_grade([item], "", "PM10", TODAY) == (None, EMPTY_ATTRS)
