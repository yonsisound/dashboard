"""대시보드에서 사용하는 컬럼명·시트 설정을 한곳에서 관리한다."""

from dataclasses import dataclass

SHEET_ID = "1jw5lqKXQIxuGt3eAMbUmWj_fJNL1h9ZY"
EXPORT_URL = (
    f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/export?format=xlsx"
)

# 대시보드 집계에 사용하는 원본 컬럼명 (4.2항)
COL_RECEIVED_DATE = "접수일"
COL_STATUS = "진행상태"
COL_CENTER = "방문CE센터"
COL_CLIENT = "거래처명"
COL_SYMPTOM = "실장애증상"
COL_ACTION = "조치내역"

# 현재 대시보드 집계에 필수인 컬럼. 그 외 비개인정보 컬럼은 향후 집계 기준 확장을 위해 유지한다.
REQUIRED_COLUMNS = [
    COL_RECEIVED_DATE,
    COL_STATUS,
    COL_CENTER,
    COL_CLIENT,
    COL_SYMPTOM,
    COL_ACTION,
]

# 로딩 단계에서 메모리에 올리지 않는 개인정보 컬럼 (4.3항)
PII_COLUMNS = [
    "고객명",
    "연락번호",
    "이동번호",
    "주소",
]

MISSING_VALUE_LABEL = "미분류"
COUNT_COLUMN = "접수건수"
WEEK_COLUMN = "주간"
CHART_MAX_BARS = 20
PERIOD_TOP_N = 10
STATUS_FILTER_ALL = "전체"
MENU_DASHBOARD = "대시보드"
MENU_CRITERIA = "기준관리"
MENU_EXCLUSIONS = "제외 항목 관리"
EXCLUSIONS_FILE_NAME = "exclusions.json"
CRITERIA_FILE_NAME = "criteria.json"


@dataclass(frozen=True)
class AggregationSpec:
    column: str
    label: str
    title: str


# 화면 표시용 짧은 이름. 없는 컬럼은 원본 컬럼명을 그대로 쓴다.
COLUMN_LABELS = {
    COL_CENTER: "센터",
    COL_SYMPTOM: "증상",
    COL_ACTION: "조치내역",
    COL_CLIENT: "거래처명",
    COL_STATUS: "진행상태",
}

# 최초 실행 시 등록되는 집계 기준 (원본 컬럼명)
DEFAULT_CRITERIA_COLUMNS = [COL_CENTER, COL_SYMPTOM, COL_ACTION]

# 집계 기준으로 쓸 수 없는 컬럼. 접수일은 기간 축으로만 쓰고, 개인정보는 로드하지 않는다.
NON_CRITERIA_COLUMNS = [*PII_COLUMNS, COL_RECEIVED_DATE]

# 예전 제외 파일 키 → 원본 컬럼명
LEGACY_EXCLUSION_KEYS = {
    "센터": COL_CENTER,
    "centers": COL_CENTER,
    "거래처명": COL_CLIENT,
    "clients": COL_CLIENT,
    "조치내역": COL_ACTION,
    "actions": COL_ACTION,
    "증상": COL_SYMPTOM,
}


def column_label(column: str) -> str:
    return COLUMN_LABELS.get(column, column)


def spec_for_column(column: str) -> AggregationSpec:
    label = column_label(column)
    return AggregationSpec(column=column, label=label, title=f"{label}별 접수건수")


def specs_for_columns(columns: list[str]) -> list[AggregationSpec]:
    return [spec_for_column(column) for column in columns]


# 집계 기준을 여기에만 추가하면 표·차트에 자동 반영된다. (기준관리 기본값과 동일)
AGGREGATION_SPECS = specs_for_columns(DEFAULT_CRITERIA_COLUMNS)
