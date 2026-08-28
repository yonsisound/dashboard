"""센터별·증상별·조치내역별 집계. UI는 이 모듈의 결과만 표시한다."""

from __future__ import annotations

from dataclasses import dataclass

from datetime import date

import pandas as pd

from dashboard_config import (
    AGGREGATION_SPECS,
    COL_RECEIVED_DATE,
    COL_STATUS,
    COUNT_COLUMN,
    MISSING_VALUE_LABEL,
    STATUS_FILTER_ALL,
    WEEK_COLUMN,
    AggregationSpec,
)


def filter_by_received_date(
    dataframe: pd.DataFrame,
    selected_date: date,
) -> pd.DataFrame:
    """선택한 달력 날짜(하루)에 접수된 행만 남긴다."""
    if COL_RECEIVED_DATE not in dataframe.columns:
        raise KeyError(f"집계할 컬럼이 없습니다: {COL_RECEIVED_DATE}")

    received = pd.to_datetime(dataframe[COL_RECEIVED_DATE], errors="coerce")
    selected = pd.Timestamp(selected_date).normalize()
    matched = received.dt.normalize() == selected
    return dataframe.loc[matched].copy()


def filter_by_status(
    dataframe: pd.DataFrame,
    selected_status: str,
) -> pd.DataFrame:
    """진행상태 필터. '전체'이면 데이터를 그대로 둔다."""
    if COL_STATUS not in dataframe.columns:
        raise KeyError(f"집계할 컬럼이 없습니다: {COL_STATUS}")
    if selected_status == STATUS_FILTER_ALL:
        return dataframe

    filled = fill_missing_category(dataframe[COL_STATUS])
    return dataframe.loc[filled == selected_status].copy()


def filter_by_date_range(
    dataframe: pd.DataFrame,
    start_date: date,
    end_date: date,
) -> pd.DataFrame:
    """시작일~종료일(당일 포함)에 접수된 행만 남긴다."""
    if COL_RECEIVED_DATE not in dataframe.columns:
        raise KeyError(f"집계할 컬럼이 없습니다: {COL_RECEIVED_DATE}")

    start = pd.Timestamp(start_date).normalize()
    end = pd.Timestamp(end_date).normalize()
    if start > end:
        start, end = end, start

    received = pd.to_datetime(dataframe[COL_RECEIVED_DATE], errors="coerce").dt.normalize()
    matched = (received >= start) & (received <= end)
    return dataframe.loc[matched].copy()


def apply_common_filters(
    dataframe: pd.DataFrame,
    *,
    selected_date: date | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
    selected_status: str = STATUS_FILTER_ALL,
) -> pd.DataFrame:
    """일자·기간·진행상태 등 이후 차트에 공통 적용할 필터."""
    filtered = dataframe
    if selected_date is not None:
        filtered = filter_by_received_date(filtered, selected_date)
    elif start_date is not None and end_date is not None:
        filtered = filter_by_date_range(filtered, start_date, end_date)
    return filter_by_status(filtered, selected_status)


def filter_by_category(
    dataframe: pd.DataFrame,
    column: str,
    category_value: str,
) -> pd.DataFrame:
    """집계 항목(센터·증상·조치내역 등) 값으로 행을 좁힌다."""
    if column not in dataframe.columns:
        raise KeyError(f"집계할 컬럼이 없습니다: {column}")
    filled = fill_missing_category(dataframe[column])
    return dataframe.loc[filled == category_value].copy()


def list_column_values(dataframe: pd.DataFrame, column: str) -> list[str]:
    """사이드바·제외 등록용 값 목록. 건수 많은 순."""
    if column not in dataframe.columns:
        return []
    ranked = fill_missing_category(dataframe[column]).value_counts()
    return ranked.index.tolist()


def list_status_options(dataframe: pd.DataFrame) -> list[str]:
    """사이드바용 진행상태 목록. 맨 앞에 '전체', 이후 건수 많은 순."""
    return [STATUS_FILTER_ALL, *list_column_values(dataframe, COL_STATUS)]


def fill_missing_category(
    series: pd.Series,
    missing_label: str = MISSING_VALUE_LABEL,
) -> pd.Series:
    """빈 값·공백을 집계용 미분류 라벨로 바꾼다."""
    text = series.astype("string").str.strip()
    missing = text.isna() | (text == "")
    return text.mask(missing, missing_label)


def aggregate_by_column(
    dataframe: pd.DataFrame,
    column: str,
    category_label: str,
) -> pd.DataFrame:
    """지정 컬럼 기준 접수건수를 내림차순 표로 반환한다."""
    if column not in dataframe.columns:
        raise KeyError(f"집계할 컬럼이 없습니다: {column}")

    work = pd.DataFrame(
        {category_label: fill_missing_category(dataframe[column])}
    )
    return (
        work.groupby(category_label, dropna=False)
        .size()
        .reset_index(name=COUNT_COLUMN)
        .sort_values([COUNT_COLUMN, category_label], ascending=[False, True])
        .reset_index(drop=True)
    )


@dataclass(frozen=True)
class AggregationView:
    key: str
    title: str
    category_label: str
    table: pd.DataFrame

    @property
    def total_count(self) -> int:
        return int(self.table[COUNT_COLUMN].sum()) if not self.table.empty else 0


def build_aggregations(
    dataframe: pd.DataFrame,
    specs: list[AggregationSpec] | None = None,
) -> list[AggregationView]:
    """지정한 집계 기준(없으면 기본 센터/증상/조치내역)으로 건수를 계산한다."""
    views: list[AggregationView] = []
    for spec in AGGREGATION_SPECS if specs is None else specs:
        if spec.column not in dataframe.columns:
            continue
        views.append(
            AggregationView(
                key=spec.column,
                title=spec.title,
                category_label=spec.label,
                table=aggregate_by_column(dataframe, spec.column, spec.label),
            )
        )
    return views


def aggregate_daily_trend(
    dataframe: pd.DataFrame,
    start_date: date,
    end_date: date,
) -> pd.DataFrame:
    """기간 내 일자별 접수건수. 건수가 0인 날도 포함해 추이 선을 끊기지 않게 한다."""
    if COL_RECEIVED_DATE not in dataframe.columns:
        raise KeyError(f"집계할 컬럼이 없습니다: {COL_RECEIVED_DATE}")

    start = pd.Timestamp(start_date).normalize()
    end = pd.Timestamp(end_date).normalize()
    if start > end:
        start, end = end, start

    received = pd.to_datetime(dataframe[COL_RECEIVED_DATE], errors="coerce").dt.normalize()
    counts = received.dropna().value_counts()
    all_days = pd.date_range(start, end, freq="D")
    series = counts.reindex(all_days, fill_value=0).astype(int)
    return pd.DataFrame(
        {
            COL_RECEIVED_DATE: series.index.strftime("%Y-%m-%d"),
            COUNT_COLUMN: series.to_numpy(),
        }
    )


def _monday_of(day: pd.Timestamp) -> pd.Timestamp:
    normalized = pd.Timestamp(day).normalize()
    return normalized - pd.Timedelta(days=int(normalized.dayofweek))


def aggregate_weekly_trend(
    dataframe: pd.DataFrame,
    start_date: date,
    end_date: date,
) -> pd.DataFrame:
    """기간을 월요일 시작 주 단위로 묶어 접수건수를 반환한다."""
    if COL_RECEIVED_DATE not in dataframe.columns:
        raise KeyError(f"집계할 컬럼이 없습니다: {COL_RECEIVED_DATE}")

    start = pd.Timestamp(start_date).normalize()
    end = pd.Timestamp(end_date).normalize()
    if start > end:
        start, end = end, start

    received = pd.to_datetime(dataframe[COL_RECEIVED_DATE], errors="coerce").dt.normalize()
    received = received.dropna()
    week_starts = received - pd.to_timedelta(received.dt.dayofweek, unit="D")
    counts = week_starts.value_counts()

    first_monday = _monday_of(start)
    last_monday = _monday_of(end)
    all_weeks = pd.date_range(first_monday, last_monday, freq="7D")
    series = counts.reindex(all_weeks, fill_value=0).astype(int)

    labels = [
        f"{monday:%Y-%m-%d} ~ {(monday + pd.Timedelta(days=6)):%m-%d}"
        for monday in series.index
    ]
    return pd.DataFrame(
        {
            WEEK_COLUMN: labels,
            COUNT_COLUMN: series.to_numpy(),
        }
    )
