"""Flag station subentries saved from the pre-#86 station table.

Before #86, STATIONS_BY_SIDO listed 시군구 names for every 시도 except Seoul.
The realtime API looks stations up by 측정소명 alone, so those subentries
never got data (or got Seoul's station of the same name). Nothing can be
migrated automatically — a 시군구 has several real stations to choose from —
so raise a repair issue asking the user to re-add them.
"""
from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import issue_registry as ir

from custom_components.kr_public_data.const import DOMAIN

# (시도, 이름) pairs the old table offered that aren't real stations in that 시도.
# Matching the old table exactly (not "missing from today's snapshot") keeps
# stations added to AirKorea after the snapshot from being flagged.
_PRE_86_NON_STATIONS: dict[str, set[str]] = {
    "부산": {"중구", "서구", "동구", "영도구", "부산진구", "동래구", "남구", "북구", "해운대구",
            "사하구", "금정구", "강서구", "연제구", "수영구", "사상구", "기장군"},
    "대구": {"중구", "동구", "서구", "남구", "북구", "수성구", "달서구", "달성군"},
    "인천": {"중구", "동구", "미추홀구", "연수구", "남동구", "부평구", "계양구", "서구", "강화군"},
    "광주": {"동구", "서구", "남구", "북구", "광산구"},
    "대전": {"동구", "중구", "서구", "유성구", "대덕구"},
    "울산": {"중구", "남구", "동구", "북구", "울주군"},
    "세종": {"세종"},
    "경기": {"수원", "성남", "안양", "부천", "광명", "평택", "안산", "고양", "과천", "의왕",
            "군포", "시흥", "용인", "이천", "안성", "김포", "화성", "광주", "양주", "포천",
            "여주", "구리", "남양주", "오산", "하남", "의정부", "동두천"},
    "강원": {"춘천", "원주", "강릉", "동해", "태백", "속초", "삼척", "홍천", "횡성"},
    "충북": {"청주", "충주", "제천", "보은", "옥천", "영동", "증평", "진천", "괴산", "음성",
            "단양"},
    "충남": {"천안", "보령", "아산", "서산", "계룡", "당진", "금산", "부여", "서천", "청양",
            "홍성", "예산", "태안"},
    "전북": {"전주", "군산", "익산", "정읍", "남원", "김제", "완주", "진안", "무주", "장수",
            "임실", "순창", "고창", "부안"},
    "전남": {"목포", "여수", "순천", "나주", "광양", "담양", "곡성", "구례", "고흥", "보성",
            "화순", "장흥", "강진", "해남", "영암", "무안", "함평", "영광", "장성", "완도",
            "진도", "신안"},
    "경북": {"포항", "경주", "김천", "안동", "구미", "영주", "영천", "상주", "문경", "경산"},
    "경남": {"창원", "진주", "통영", "사천", "김해", "밀양", "거제", "양산"},
    "제주": {"제주", "서귀포", "한림", "애월", "성산"},
}


@callback
def async_check_stale_stations(hass: HomeAssistant, entry: ConfigEntry,
                               stations: list[dict[str, Any]], default_sido: str) -> None:
    """Create or clear this entry's stale-station repair issue."""
    stale = [f"{st.get('sido') or default_sido} {st['stationName']}" for st in stations
             if st["stationName"] in _PRE_86_NON_STATIONS.get(st.get("sido") or default_sido, ())]
    issue_id = f"airkorea_stale_stations_{entry.entry_id}"
    if not stale:
        ir.async_delete_issue(hass, DOMAIN, issue_id)
        return
    ir.async_create_issue(
        hass, DOMAIN, issue_id,
        config_entry_id=entry.entry_id,
        is_fixable=False,
        severity=ir.IssueSeverity.WARNING,
        translation_key="airkorea_stale_stations",
        translation_placeholders={"stations": ", ".join(stale)},
    )
