"""구글 시트에서 접수건을 불러오고, 개인정보 컬럼만 제거한다."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from io import BytesIO
import urllib.error
import urllib.request

import pandas as pd

from dashboard_config import (
    COL_RECEIVED_DATE,
    EXPORT_URL,
    PII_COLUMNS,
    REQUIRED_COLUMNS,
)

DOWNLOAD_TIMEOUT_SECONDS = 30
USER_AGENT = "Mozilla/5.0 (compatible; ServiceDashboard/1.0)"


class DataLoadError(Exception):
    """사용자에게 보여 줄 데이터 로딩 실패."""

    def __init__(self, user_message: str, detail: str | None = None) -> None:
        super().__init__(user_message)
        self.user_message = user_message
        self.detail = detail


@dataclass(frozen=True)
class LoadResult:
    dataframe: pd.DataFrame
    loaded_at: datetime
    invalid_date_count: int

    @property
    def row_count(self) -> int:
        return len(self.dataframe)

    @property
    def columns(self) -> list[str]:
        return list(self.dataframe.columns)

    @property
    def date_min(self) -> pd.Timestamp | None:
        series = self.dataframe[COL_RECEIVED_DATE].dropna()
        if series.empty:
            return None
        return series.min()

    @property
    def date_max(self) -> pd.Timestamp | None:
        series = self.dataframe[COL_RECEIVED_DATE].dropna()
        if series.empty:
            return None
        return series.max()


def _download_workbook_bytes() -> bytes:
    request = urllib.request.Request(
        EXPORT_URL,
        headers={"User-Agent": USER_AGENT},
    )
    try:
        with urllib.request.urlopen(request, timeout=DOWNLOAD_TIMEOUT_SECONDS) as response:
            payload = response.read()
    except urllib.error.HTTPError as error:
        if error.code in (401, 403):
            raise DataLoadError(
                "파일에 접근할 권한이 없습니다. 구글 시트 공유 설정을 확인해 주세요.",
                detail=f"HTTP {error.code}",
            ) from error
        if error.code == 404:
            raise DataLoadError(
                "지정된 엑셀 파일을 찾을 수 없습니다. 시트 주소를 확인해 주세요.",
                detail=f"HTTP {error.code}",
            ) from error
        raise DataLoadError(
            "구글 드라이브에서 파일을 불러오지 못했습니다. 잠시 후 다시 시도해 주세요.",
            detail=f"HTTP {error.code}",
        ) from error
    except urllib.error.URLError as error:
        raise DataLoadError(
            "구글 드라이브에 연결하지 못했습니다. 네트워크 연결을 확인해 주세요.",
            detail=str(error.reason),
        ) from error
    except TimeoutError as error:
        raise DataLoadError(
            "파일 다운로드 시간이 초과되었습니다. 네트워크 상태를 확인해 주세요.",
        ) from error
    except DataLoadError:
        raise
    except Exception as error:
        raise DataLoadError(
            "구글 드라이브에서 파일을 불러오지 못했습니다. 잠시 후 다시 시도해 주세요.",
            detail=type(error).__name__,
        ) from error

    if not payload:
        raise DataLoadError("내려받은 파일이 비어 있습니다.")
    if not payload.startswith(b"PK"):
        raise DataLoadError(
            "엑셀 파일이 아닌 응답을 받았습니다. 공유 설정(링크가 있는 모든 사용자 - 보기)을 확인해 주세요."
        )
    return payload


def _normalize_column_name(name: object) -> str:
    return str(name).strip()


def _read_excel(buffer: BytesIO, **kwargs) -> pd.DataFrame:
    try:
        return pd.read_excel(buffer, engine="openpyxl", **kwargs)
    except Exception as error:
        raise DataLoadError(
            "엑셀 파일 형식이 올바르지 않아 읽지 못했습니다.",
            detail=str(error),
        ) from error


def remaining_pii_columns(columns: object) -> list[str]:
    """데이터프레임에 남아 있는 개인정보 컬럼명을 반환한다."""
    present = {_normalize_column_name(column) for column in columns}
    return [column for column in PII_COLUMNS if column in present]


def _is_pii_column(column: object) -> bool:
    return _normalize_column_name(column) in PII_COLUMNS


def _drop_pii_and_validate(source: pd.DataFrame) -> pd.DataFrame:
    source = source.copy()
    source.columns = [_normalize_column_name(column) for column in source.columns]

    missing_columns = [
        column for column in REQUIRED_COLUMNS if column not in source.columns
    ]
    if missing_columns:
        raise DataLoadError(
            "필수 컬럼이 없어 데이터를 불러올 수 없습니다: "
            + ", ".join(missing_columns)
        )

    pii_in_memory = remaining_pii_columns(source.columns)
    if pii_in_memory:
        source = source.drop(columns=pii_in_memory)

    leftover_pii = remaining_pii_columns(source.columns)
    if leftover_pii:
        raise DataLoadError(
            "개인정보 컬럼이 남아 있어 데이터를 표시할 수 없습니다.",
            detail=", ".join(leftover_pii),
        )

    return source


def load_service_data() -> LoadResult:
    """접수건을 불러온 뒤 개인정보 컬럼만 제거하고, 나머지 컬럼은 유지한다."""
    workbook_bytes = _download_workbook_bytes()
    buffer = BytesIO(workbook_bytes)

    header_frame = _read_excel(buffer, nrows=0)
    header_names = [_normalize_column_name(column) for column in header_frame.columns]
    available = set(header_names)

    missing_columns = [column for column in REQUIRED_COLUMNS if column not in available]
    if missing_columns:
        raise DataLoadError(
            "필수 컬럼이 없어 데이터를 불러올 수 없습니다: "
            + ", ".join(missing_columns)
        )

    buffer.seek(0)
    raw_frame = _read_excel(
        buffer,
        usecols=lambda column: not _is_pii_column(column),
    )
    dataframe = _drop_pii_and_validate(raw_frame)

    if dataframe.empty:
        raise DataLoadError("파일에 집계할 접수건이 없습니다.")

    dataframe[COL_RECEIVED_DATE] = pd.to_datetime(
        dataframe[COL_RECEIVED_DATE],
        errors="coerce",
    )
    invalid_date_count = int(dataframe[COL_RECEIVED_DATE].isna().sum())

    return LoadResult(
        dataframe=dataframe,
        loaded_at=datetime.now(),
        invalid_date_count=invalid_date_count,
    )
