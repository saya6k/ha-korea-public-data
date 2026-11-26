"""AirKorea (에어코리아) sub-module."""
import re
from datetime import datetime

from custom_components.kr_public_data.utils import KST, sido_short_name

# 대기오염정보 조회 서비스 (15073861) - v1
STATION_URL = "https://apis.data.go.kr/B552584/MsrstnInfoInqireSvc/getMsrstnList"
REALTIME_URL = "https://apis.data.go.kr/B552584/ArpltnInforInqireSvc/getMsrstnAcctoRltmMesureDnsty"
FORECAST_URL = "https://apis.data.go.kr/B552584/ArpltnInforInqireSvc/getMinuDustFrcstDspth"
SCAN_INTERVAL = 1800

# 생활기상지수 조회서비스 V5 (V4 was retired: NO_OPENAPI_SERVICE_ERROR, 2026-11)
UV_IDX_URL = "https://apis.data.go.kr/1360000/LivingWthrIdxServiceV5/getUVIdxV5"
AIR_STAG_URL = "https://apis.data.go.kr/1360000/LivingWthrIdxServiceV5/getAirDiffusionIdxV5"

# 시도 → 행정구역코드 (생활기상지수용 areaNo)
SIDO_AREA_CODE = {
    "서울": "1100000000", "부산": "2600000000", "대구": "2700000000",
    "인천": "2800000000", "광주": "2900000000", "대전": "3000000000",
    "울산": "3100000000", "세종": "3600000000", "경기": "4100000000",
    "강원": "5100000000", "충북": "4300000000", "충남": "4400000000",
    "전북": "4500000000", "전남": "4600000000", "경북": "4700000000",
    "경남": "4800000000", "제주": "5000000000",
}

UV_GRADES = [(3, "낮음"), (6, "보통"), (8, "높음"), (11, "매우높음"), (999, "위험")]
STAG_GRADES = [(25, "낮음"), (50, "보통"), (75, "높음"), (999, "매우높음")]

_DATA_TIME_RE = re.compile(r"(\d{4}-\d{2}-\d{2})\s+(\d{1,2})")

# AirKorea 대기질 예보는 권역 단위로 발표한다: 경기는 남부/북부, 강원은 영동/영서,
# 그 외 시도는 분할 없음(공식 FAQ). 권역 나열 순서가 주소를 못 쓸 때의 기본 선택 순서이고,
# 시군 목록은 측정소 주소로 권역을 가리는 데 쓴다. 전체 등급은 all_regions로 노출한다.
# https://www.airkorea.or.kr/web/board/5/1171/?pMENU_NO=21
BULLETIN_SUBREGIONS = {
    "경기": {
        "경기남부": ("과천시", "광명시", "광주시", "군포시", "부천시", "성남시",
                   "수원시", "시흥시", "안산시", "안성시", "안양시", "양평군",
                   "오산시", "용인시", "의왕시", "이천시", "여주시", "평택시",
                   "하남시", "화성시"),
        "경기북부": ("가평군", "고양시", "구리시", "김포시", "남양주시", "양주시",
                   "연천군", "동두천시", "의정부시", "파주시", "포천시"),
    },
    "강원": {
        "영동": ("고성군", "속초시", "양양군", "강릉시", "동해시", "삼척시", "태백시"),
        "영서": ("양구군", "인제군", "홍천군", "평창군", "정선군", "철원군",
                "화천군", "춘천시", "횡성군", "원주시", "영월군"),
    },
}


def forecast_region_grades(item: dict) -> dict[str, str]:
    """미세먼지 예보 항목의 informGrade를 {지역: 등급}으로 파싱한다."""
    grades: dict[str, str] = {}
    for raw_pair in (item.get("informGrade", "") or "").split(","):
        pair = raw_pair.strip()
        if " : " not in pair:
            continue
        region, grade = pair.split(" : ", 1)
        grade = grade.strip()
        if not grade:
            continue
        grades[region.strip()] = grade
    return grades


def select_forecast_item(
    forecasts: list[dict], inform_code: str, target_date: str
) -> dict | None:
    """해당 오염물질/날짜의 예보 중 가장 최근 발표(시각 기준)를 고른다."""
    matches = [fc for fc in forecasts
               if fc.get("informCode") == inform_code
               and fc.get("informData") == target_date]
    if not matches:
        return None

    def bulletin_key(fc: dict) -> tuple[str, int]:
        m = _DATA_TIME_RE.search(str(fc.get("dataTime", "") or ""))
        return (m.group(1), int(m.group(2))) if m else ("", -1)

    return max(matches, key=bulletin_key)


def _addr_bulletin_region(sido: str, addr: str) -> str:
    """측정소 주소의 시군명으로 예보 권역을 가린다. 못 가리면 빈 문자열."""
    if not addr or station_sido(addr) != sido:
        return ""
    for part in addr.split()[1:]:
        for name, cities in BULLETIN_SUBREGIONS.get(sido, {}).items():
            if part in cities:
                return name
    return ""


def station_forecast_grade(
    forecasts: list[dict], sido: str, inform_code: str, target_date: str,
    addr: str = "",
) -> tuple[str | None, dict]:
    """측정소 소속 시도의 예보 등급과 근거 속성을 반환한다."""
    empty_attrs: dict = {"region": "", "all_regions": {}, "data_time": "", "inform_cause": "",
                         "inform_overall": ""}
    item = select_forecast_item(forecasts, inform_code, target_date)
    if item is None:
        return None, empty_attrs

    grades = forecast_region_grades(item)
    # 공보의 정확한 시도명 > 주소의 시군으로 가린 권역 > 표 나열 순서의 첫 권역 >
    # substring 폴백. 선택 권역 외 등급은 all_regions 속성으로 확인할 수 있다.
    if sido in grades:
        region = sido
    else:
        region = _addr_bulletin_region(sido, addr)
        region = region or next(
            (name for name in BULLETIN_SUBREGIONS.get(sido, ()) if name in grades), "")
        region = region or next((r for r in grades if sido and sido in r), "")
    if not region:
        return None, empty_attrs

    known = BULLETIN_SUBREGIONS.get(sido, ())
    return grades[region], {
        "region": region,
        "all_regions": {r: g for r, g in grades.items() if r in known or sido in r},
        "data_time": item.get("dataTime", "") or "",
        "inform_cause": item.get("informCause", "") or "",
        "inform_overall": item.get("informOverall", "") or "",
    }


def living_index_now(data: dict, now: datetime) -> int | None:
    """Value of a 생활기상지수 response (UV, 대기정체) for the slot holding ``now``.

    Fields count hours from the bulletin's issue time (``date``, YYYYMMDDHH
    KST — 06 or 18), not hours of the day: the 18시 bulletin's ``h18`` is
    noon the next day. Not every index has ``h0`` (대기정체 starts at
    ``h3``), so take the first slot at or after now. "0" is a real value
    (UV at night).
    """
    if not data:
        return None
    try:
        issued = datetime.strptime(str(data.get("date", "")), "%Y%m%d%H").replace(tzinfo=KST)
        offset = max(int((now - issued).total_seconds() // 3600) // 3 * 3, 0)
    except ValueError:
        offset = 0
    slots = sorted(int(k[1:]) for k, v in data.items()
                   if k[:1] == "h" and k[1:].isdigit() and str(v).strip())
    for slot in slots:
        if slot >= offset:
            try:
                return int(data[f"h{slot}"])
            except (ValueError, TypeError):
                continue
    return None


# 전남광주통합특별시 주소에서 광주(옛 광역시) 몫을 가려내는 자치구 — 전남에는 '구'가 없다.
_GWANGJU_GU = {"동구", "서구", "남구", "북구", "광산구"}


def station_sido(addr: str) -> str:
    """측정소 주소의 시도 축약명 ('부산광역시 …'/'부산 …' → '부산')."""
    parts = addr.split()
    if not parts:
        return ""
    if parts[0].startswith("전남광주"):
        return "광주" if len(parts) > 1 and parts[1] in _GWANGJU_GU else "전남"
    return sido_short_name(parts[0])


def group_stations(items: list[dict]) -> dict[str, list[str]]:
    """getMsrstnList 항목들 → {시도 축약명: 정렬된 측정소명 목록}."""
    grouped: dict[str, list[str]] = {}
    for item in items:
        name = item.get("stationName")
        sido = station_sido(item.get("addr", ""))
        if name and sido in SIDO_AREA_CODE:
            grouped.setdefault(sido, []).append(name)
    return {sido: sorted(grouped[sido]) for sido in SIDO_AREA_CODE if sido in grouped}

# 시도별 측정소 목록 — 설정 흐름이 측정소정보 API(getMsrstnList)를 못 쓸 때의 폴백.
# 2026-11-23 실제 목록 674곳을 group_stations()로 분류한 스냅샷이다.
STATIONS_BY_SIDO = {
    "서울": ["강남구","강남대로","강동구","강변북로","강북구","강서구","공항대로","관악구",
            "광진구","구로구","금천구","노원구","도봉구","도산대로","동대문구","동작구",
            "동작대로 중앙차로","마포구","서대문구","서초구","성동구","성북구","송파구","시흥대로",
            "신촌로","양천구","영등포구","영등포로","용산구","은평구","정릉로","종로","종로구",
            "중구","중랑구","천호대로","청계천로","한강대로","홍릉로","화랑로"],
    "부산": ["감천동","개금동","광복동","광안동","기장읍","녹산동","당리동","대신동","대연동",
            "대저동","덕천동","덕포동","명장동","명지동","부산감만","부산북항","부산신항","부산항",
            "삼락동","수정동","연산동","온천동","용수리","용호동","우동","장림동","재송동",
            "전포동","좌동","청룡동","청학동","초량동","태종대","학장동","화명동","회동동"],
    "대구": ["군위읍","남산1동","내당동","다사읍","대명동","만촌동","본동","산격동","서변동",
            "서호동","수창동","시지동","신암동","연호동","용계동","유가읍","이곡동","이현동",
            "지산동","진천동","충혼탑","침산동","태전동","평리동","호림동","화원읍"],
    "인천": ["검단","경인항","계산","고잔","구월동","길상","남동","논현","덕적도","동막","동춘",
            "백령도","부평","부평역","삼산","서창","서해","석남","석모리","석바위","송도","송림",
            "송해","송현","숭의","신흥","아암","연평도","연희","영종","영흥","운서","울도","원당",
            "인천 남항","인천 북항","인천 신항","인천항","임학","주안","중봉","청라","효성"],
    "광주": ["건국동","노대동","농성동","두암동","서석동","오선동","우산동(광주)","운암동",
            "유촌동","일곡동","주월동","치평동","평동"],
    "대전": ["관평동","구성동","노은동","대성동","대흥동1","둔산동","문창동","문평동","비래동",
            "상대동(대전)","성남동1","월평동","읍내동","정림동","지족동"],
    "울산": ["농소동","대송동","덕신리","무거동","방어진순환도로","범서읍","부곡동(울산)",
            "북부순환도로","산업로","삼남읍","삼산동","상남리","선암동","성남동","송정동","신정동",
            "신정로","약사동","여천동(울산)","울산항","웅촌면","전하동","화산리","효문동"],
    "세종": ["보람동","부강면","아름동","전의면","조치원읍","한솔동"],
    "경기": ["가남읍","가평","감일","경수대로(동수원)","경안동","경춘로","고덕동","고색동","고읍",
            "고잔동","고천동","고촌읍","곤지암","공도읍","과천동","관인면","광교동","교문동",
            "금곡동","금암로(신장동)","금촌동","기흥","김량장동","남양읍","내동","단대동","당동",
            "대부동","대신면","대야동","대왕판교로(백현동)","동구동","동탄","모현읍","목감동",
            "미사","배곧동","백마로(마두역)","백석읍","백암면","별내동","별양동","보산동","복정동",
            "본오동","봉담읍","봉산동","부곡3동","부곡동1","부림동","부발읍","비전동","사우동",
            "산본동","상대원동","새솔동","서신면","서해안로","선단동","설성면","설악면",
            "성남대로(모란역)","소사본동","소하동","송내대로(중동)","송북동","송산3동","수내동",
            "수지","시화산단","식사동","신원동","신장동","신풍동","안양2동","안양8동","안중",
            "양평읍","연천","연천(DMZ)","영통동","오남읍","오산동","오정동","오포1동","와부읍",
            "용문면","우정읍","운정","운중동","원곡동","원삼면","월곶면","의정부1동","의정부동",
            "이동읍","인계동","일동면","장현동","장호원읍","전곡","정왕동","정자동","주엽동",
            "죽산면","중2동","중부대로(구갈동)","중앙대로(고잔동)","중앙동(경기)","진접읍",
            "창전동","천천동","철산동","청계동","청북읍","초지동","파주","파주읍","평택항",
            "한강로","한강신도시","행신동","향남읍","호계3동","호매실","호수동","화도읍"],
    "강원": ["간성읍","갈말읍","고성(DMZ)","금호동","남양동1","동해항","묵호항","문막읍",
            "반곡동(명륜동)","방산면","북평면","삼척항","상리","신사우동","양구읍","양양읍",
            "영월읍","옥계항","옥천동","온의동","우천면","인제(DMZ)","인제읍","정선읍","주문진읍",
            "중앙동(강원)","중앙로","지정면","천곡동","철원(DMZ)","초당동","치악산","퇴계동",
            "평창읍","호산항","홍천읍","화천(DMZ)","화천읍","황지동","횡성읍"],
    "충북": ["가덕면","감물면","괴산읍","금왕","단성면","단양읍","덕산읍","도안면","매포읍",
            "보은읍","복대동","봉명동","사천동","산남동","살미면","소이면","송학면","영동읍",
            "영천동","오송읍","오창읍","옥천읍","용담동","용암동","음성읍","장락동","중앙탑면",
            "증평읍","진천읍","청천면","청풍면","칠금동","호암동","황간면"],
    "충남": ["격렬비열도","고덕면(충남)","공주","금산읍","내포","논산","당진시청사","대산리",
            "대산항","대천2동","도고면","독곶리","동문동","둔포면","모종동","배방읍","백석동",
            "보령항","복운리","부여읍","사곡면","삽교읍","서면","서천읍","성거읍","성동면",
            "성성동","성연면","성황동","송산면","송악면","수신면","신방동","엄사면","연무읍",
            "예산군","외연도","원북면","이원면","인주면","장재리","장항읍","장항항","정산면",
            "주교면","청양읍","탄천면","태안읍","태안항","파도리","평택당진항",
            "평택당진항(당진항)","합덕읍","홍성읍"],
    "전북": ["계화면","고산면","고창읍","관촌면","광활면","구이면","군산항","금마면","노송동",
            "말도","모현동","무주읍","봉동읍","부안읍","비응도동","사정동","삼기면","삼천동",
            "새만금","서신동","소룡동","소룡동2","송천동","순창읍","신태인","신풍동(군산)",
            "심원면","안성면","여산면","여의동","연지동","영파동","옥산면","요촌동","용동면",
            "운봉읍","운암면","임실읍","장계면","장수읍","죽항동","진안읍","춘포면","팔복동",
            "팔봉동","함열읍","혁신동","효자동"],
    "전남": ["가거도","강진읍","고흥읍","곡성읍","광양 율촌","광양 중마","광양읍","광양항",
            "구례읍","남악.오룡","담양읍","대불","덕충동","목포항","무안읍","문수동","벌교읍",
            "보성읍","봉강면","부흥동","빛가람동","삼일동","서강동","송단리","순천만","신대",
            "신안군","신지면","안마도","여수항","여천동(여수)","연향동","영광읍","영암읍","완도항",
            "용당동","월내동","율촌면","장성읍","장천동","장흥읍","중동","진도읍","진월면",
            "태인동","함평읍","해남읍","호두리","홍도","화순읍","화양면"],
    "경북": ["3공단","4공단","가흥동","강구면","공단동","대가야읍","대광동","대도동","대송면",
            "명륜동","문경시","보덕동","봉화군청","상주시","석포면","성건동","성주군","송도동",
            "안강읍","안계면","안계면(교외)","양덕동","연일읍","영덕읍","영양군","영주동","영천시",
            "영해면","예천군","오천읍","외동읍","우현동","울릉읍","울진군","원평동","율곡동",
            "의성읍","장량동","장흥동","제철동","중방동","진량읍","진미동","청림동","청송읍",
            "칠곡군","태하리","평화남산동","포항항","하양읍","형곡동","화북면","화양읍"],
    "경남": ["가야읍","거창읍","경화동","고성읍","고현동","금성면","김해대로","남상면","남해읍",
            "내서읍","내일동","대산면","대안동","동상동","마산항","명서동","무전동","물금읍",
            "반송로","봉암동","북부동","사천읍","사파동","산청읍","삼방동","삼진로","삼천포항",
            "삼호동","상대동(진주)","상봉동","성주동","아주동","옥포항","용지동","웅남동","월영동",
            "의령읍","장유동","저구리","정촌면","진례면","진영읍","진해항","창녕읍","하동읍",
            "하동항","함양읍","합천읍","향촌동","회원동"],
    "제주": ["강정동","고산리","남원읍","노형로","대정읍","동홍동","성산읍","애월읍","연동",
            "이도동","제주항","조천읍","한림읍","화북동"],
}
