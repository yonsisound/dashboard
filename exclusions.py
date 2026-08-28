"""기준 컬럼별 제외 목록을 파일로 저장하고 집계에 반영한다."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import json

import pandas as pd

from aggregator import fill_missing_category
from dashboard_config import EXCLUSIONS_FILE_NAME, LEGACY_EXCLUSION_KEYS

EXCLUSIONS_PATH = Path(__file__).resolve().parent / EXCLUSIONS_FILE_NAME


@dataclass
class ExclusionList:
    by_column: dict[str, list[str]] = field(default_factory=dict)

    @property
    def is_empty(self) -> bool:
        return not any(self.by_column.values())

    def values_for(self, column: str) -> list[str]:
        return list(self.by_column.get(column, []))

    def normalized(self) -> "ExclusionList":
        cleaned: dict[str, list[str]] = {}
        for column, values in self.by_column.items():
            name = str(column).strip()
            if not name:
                continue
            unique_values = _unique_keep_order(values)
            if unique_values:
                cleaned[name] = unique_values
        return ExclusionList(by_column=cleaned)

    def with_column(self, column: str, values: list[str]) -> "ExclusionList":
        updated = dict(self.normalized().by_column)
        cleaned = _unique_keep_order(values)
        if cleaned:
            updated[column] = cleaned
        else:
            updated.pop(column, None)
        return ExclusionList(by_column=updated)

    def without_column(self, column: str) -> "ExclusionList":
        updated = {
            name: values
            for name, values in self.normalized().by_column.items()
            if name != column
        }
        return ExclusionList(by_column=updated)

    def active_for(self, columns: list[str]) -> "ExclusionList":
        """현재 기준에 있는 컬럼의 제외값만 남긴다. 기준에서 빠진 컬럼은 무효다."""
        allowed = set(columns)
        return ExclusionList(
            by_column={
                name: values
                for name, values in self.normalized().by_column.items()
                if name in allowed
            }
        )


class ExclusionSaveError(Exception):
    """제외 목록 파일 저장 실패."""

    def __init__(self, user_message: str, detail: str | None = None) -> None:
        super().__init__(user_message)
        self.user_message = user_message
        self.detail = detail


def _unique_keep_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        text = str(value).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        ordered.append(text)
    return ordered


def _as_str_list(value: object) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [str(item) for item in value]
    return []


def _payload_to_by_column(payload: dict) -> dict[str, list[str]]:
    by_column: dict[str, list[str]] = {}
    for key, value in payload.items():
        column = LEGACY_EXCLUSION_KEYS.get(str(key), str(key).strip())
        if not column:
            continue
        merged = [*by_column.get(column, []), *_as_str_list(value)]
        by_column[column] = merged
    return by_column


def load_exclusion_file(
    path: Path = EXCLUSIONS_PATH,
) -> tuple[ExclusionList, str | None]:
    """제외 목록과, 파일이 깨졌을 때 사용자 안내 문구를 함께 반환한다."""
    if not path.exists():
        return ExclusionList(), None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except OSError:
        return ExclusionList(), "제외 목록 파일을 읽지 못해 전체 데이터로 집계합니다."
    except json.JSONDecodeError:
        return ExclusionList(), "제외 목록 파일이 손상되어 전체 데이터로 집계합니다."
    if not isinstance(payload, dict):
        return ExclusionList(), "제외 목록 형식이 올바르지 않아 전체 데이터로 집계합니다."
    return ExclusionList(by_column=_payload_to_by_column(payload)).normalized(), None


def load_exclusions(path: Path = EXCLUSIONS_PATH) -> ExclusionList:
    exclusions, _warning = load_exclusion_file(path)
    return exclusions


def save_exclusions(exclusions: ExclusionList, path: Path = EXCLUSIONS_PATH) -> None:
    cleaned = exclusions.normalized()
    temp_path = path.with_name(path.name + ".tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temp_path.write_text(
            json.dumps(cleaned.by_column, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temp_path.replace(path)
    except OSError as error:
        if temp_path.exists():
            temp_path.unlink(missing_ok=True)
        raise ExclusionSaveError(
            "제외 목록을 저장하지 못했습니다. 파일 권한을 확인해 주세요.",
            detail=type(error).__name__,
        ) from error


def apply_exclusions(
    dataframe: pd.DataFrame,
    exclusions: ExclusionList,
    active_columns: list[str] | None = None,
) -> pd.DataFrame:
    """기준에 있는 컬럼의 제외값만 뺀다. 원본에 없는 값·기준에 없는 컬럼은 무시한다."""
    working = exclusions.active_for(active_columns) if active_columns is not None else exclusions
    if working.is_empty:
        return dataframe

    filtered = dataframe
    for column, values in working.normalized().by_column.items():
        if not values or column not in filtered.columns:
            continue
        category_values = fill_missing_category(filtered[column])
        filtered = filtered.loc[~category_values.isin(set(values))]
    return filtered.copy()
