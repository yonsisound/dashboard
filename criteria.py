"""집계·제외에 공통으로 쓰는 기준 컬럼을 파일로 저장한다."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import json

from dashboard_config import (
    AggregationSpec,
    CRITERIA_FILE_NAME,
    DEFAULT_CRITERIA_COLUMNS,
    NON_CRITERIA_COLUMNS,
    specs_for_columns,
)

CRITERIA_PATH = Path(__file__).resolve().parent / CRITERIA_FILE_NAME
CRITERIA_JSON_KEY = "columns"


class CriteriaSaveError(Exception):
    """기준 목록 파일 저장 실패."""

    def __init__(self, user_message: str, detail: str | None = None) -> None:
        super().__init__(user_message)
        self.user_message = user_message
        self.detail = detail


@dataclass
class CriteriaList:
    columns: list[str] = field(default_factory=list)

    def normalized(self) -> "CriteriaList":
        forbidden = set(NON_CRITERIA_COLUMNS)
        seen: set[str] = set()
        ordered: list[str] = []
        for column in self.columns:
            text = str(column).strip()
            if not text or text in seen or text in forbidden:
                continue
            seen.add(text)
            ordered.append(text)
        return CriteriaList(columns=ordered)

    @property
    def specs(self) -> list[AggregationSpec]:
        return specs_for_columns(self.normalized().columns)

    def with_added(self, column: str) -> "CriteriaList":
        return CriteriaList(columns=[*self.columns, column]).normalized()

    def without(self, column: str) -> "CriteriaList":
        return CriteriaList(
            columns=[item for item in self.columns if item != column]
        ).normalized()


def _as_str_list(value: object) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [str(item) for item in value]
    return []


def default_criteria() -> CriteriaList:
    return CriteriaList(columns=list(DEFAULT_CRITERIA_COLUMNS)).normalized()


def load_criteria_file(
    path: Path = CRITERIA_PATH,
) -> tuple[CriteriaList, str | None]:
    """기준 목록과, 파일이 깨졌을 때 사용자 안내 문구를 함께 반환한다."""
    if not path.exists():
        defaults = default_criteria()
        try:
            save_criteria(defaults, path)
        except CriteriaSaveError:
            return defaults, None
        return defaults, None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except OSError:
        return default_criteria(), "기준 파일을 읽지 못해 기본 기준(센터, 증상, 조치내역)으로 표시합니다."
    except json.JSONDecodeError:
        return default_criteria(), "기준 파일이 손상되어 기본 기준(센터, 증상, 조치내역)으로 표시합니다."

    if isinstance(payload, list):
        columns = _as_str_list(payload)
    elif isinstance(payload, dict):
        columns = _as_str_list(payload.get(CRITERIA_JSON_KEY, []))
    else:
        return default_criteria(), "기준 파일 형식이 올바르지 않아 기본 기준으로 표시합니다."

    return CriteriaList(columns=columns).normalized(), None


def load_criteria(path: Path = CRITERIA_PATH) -> CriteriaList:
    criteria, _warning = load_criteria_file(path)
    return criteria


def save_criteria(criteria: CriteriaList, path: Path = CRITERIA_PATH) -> None:
    cleaned = criteria.normalized()
    payload = {CRITERIA_JSON_KEY: cleaned.columns}
    temp_path = path.with_name(path.name + ".tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temp_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temp_path.replace(path)
    except OSError as error:
        if temp_path.exists():
            temp_path.unlink(missing_ok=True)
        raise CriteriaSaveError(
            "기준 목록을 저장하지 못했습니다. 파일 권한을 확인해 주세요.",
            detail=type(error).__name__,
        ) from error


def addable_columns(available_columns: list[str], current_columns: list[str]) -> list[str]:
    """기준에 넣을 수 있는 컬럼. 개인정보·접수일·이미 등록된 항목은 뺀다."""
    forbidden = set(NON_CRITERIA_COLUMNS)
    current = set(current_columns)
    ordered: list[str] = []
    seen: set[str] = set()
    for column in available_columns:
        name = str(column).strip()
        if not name or name in forbidden or name in current or name in seen:
            continue
        seen.add(name)
        ordered.append(name)
    return ordered
