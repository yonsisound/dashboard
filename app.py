"""서비스 접수 데이터 대시보드."""

import importlib
from datetime import date, datetime
from typing import NamedTuple

import pandas as pd
import plotly.express as px
import streamlit as st
import streamlit.components.v1 as components

import dashboard_config

# Streamlit은 형제 모듈을 오래 캐시하므로, 의존 모듈을 읽기 전에 설정을 먼저 다시 읽는다.
dashboard_config = importlib.reload(dashboard_config)

import aggregator
import criteria
import data_loader
import exclusions

data_loader = importlib.reload(data_loader)
aggregator = importlib.reload(aggregator)
exclusions = importlib.reload(exclusions)
criteria = importlib.reload(criteria)

from aggregator import (
    AggregationView,
    aggregate_daily_trend,
    aggregate_weekly_trend,
    apply_common_filters,
    build_aggregations,
    filter_by_category,
    list_column_values,
    list_status_options,
)
from criteria import (
    CriteriaList,
    CriteriaSaveError,
    addable_columns,
    load_criteria_file,
    save_criteria,
)
from dashboard_config import (
    CHART_MAX_BARS,
    COL_RECEIVED_DATE,
    COUNT_COLUMN,
    DEFAULT_CRITERIA_COLUMNS,
    MENU_CRITERIA,
    MENU_DASHBOARD,
    MENU_EXCLUSIONS,
    PII_COLUMNS,
    REQUIRED_COLUMNS,
    STATUS_FILTER_ALL,
    WEEK_COLUMN,
    AggregationSpec,
    column_label,
)
from data_loader import (
    DataLoadError,
    LoadResult,
    load_service_data,
    remaining_pii_columns,
)
from exclusions import (
    ExclusionList,
    ExclusionSaveError,
    apply_exclusions,
    load_exclusion_file,
    save_exclusions,
)

st.set_page_config(
    page_title="서비스 접수 대시보드",
    page_icon="📋",
    layout="wide",
)


CACHE_VERSION = 3
RANKING_TABLE_HEIGHT = 420
TREND_CHART_HEIGHT = 340


class DashboardFilters(NamedTuple):
    selected_date: date
    start_date: date
    end_date: date
    selected_status: str
    exclusions: ExclusionList
    specs: list[AggregationSpec]


def _as_date(value: date | datetime | tuple) -> date:
    if isinstance(value, tuple):
        value = value[0]
    if isinstance(value, datetime):
        return value.date()
    return value


@st.cache_data(show_spinner="구글 드라이브에서 접수건을 불러오는 중...")
def _cached_load(cache_version: int = CACHE_VERSION) -> LoadResult:
    return load_service_data()


def _render_error(error: DataLoadError) -> None:
    st.error(error.user_message)
    if error.detail:
        with st.expander("상세 오류 보기"):
            st.code(error.detail)
    st.stop()


def _render_load_summary(result: LoadResult) -> None:
    with st.expander("원본 데이터 정보", expanded=False):
        metric_columns = st.columns(4)
        metric_columns[0].metric("원본 접수건수", f"{result.row_count:,}건")
        metric_columns[1].metric("사용 컬럼 수", f"{len(result.columns)}개")
        metric_columns[2].metric(
            "접수일 시작",
            result.date_min.strftime("%Y-%m-%d") if result.date_min is not None else "-",
        )
        metric_columns[3].metric(
            "접수일 종료",
            result.date_max.strftime("%Y-%m-%d") if result.date_max is not None else "-",
        )
        st.caption(f"불러온 시각: {result.loaded_at.strftime('%Y-%m-%d %H:%M:%S')}")

        if result.invalid_date_count:
            st.warning(
                f"접수일을 날짜로 바꾸지 못한 행이 {result.invalid_date_count:,}건 있습니다. "
                "해당 건은 일자 집계에서 제외됩니다."
            )

        remaining_pii = remaining_pii_columns(result.columns)
        if remaining_pii:
            st.error("개인정보 컬럼이 남아 있어 미리보기를 표시하지 않습니다.")
            return

        expected_missing = [
            column for column in REQUIRED_COLUMNS if column not in result.columns
        ]
        if expected_missing:
            st.error("필수 컬럼이 빠졌습니다: " + ", ".join(expected_missing))

        extra_columns = [
            column for column in result.columns if column not in REQUIRED_COLUMNS
        ]
        st.markdown(
            "**현재 집계 기준:** "
            + ", ".join(f"`{column}`" for column in REQUIRED_COLUMNS)
        )
        if extra_columns:
            st.markdown(
                "**추가 유지 컬럼:** "
                + ", ".join(f"`{column}`" for column in extra_columns)
            )
        st.caption(
            "개인정보 컬럼(" + ", ".join(PII_COLUMNS) + ")은 불러오지 않았습니다."
        )
        preview = result.dataframe.drop(
            columns=remaining_pii_columns(result.dataframe.columns),
            errors="ignore",
        ).head(20)
        st.dataframe(
            preview,
            width="stretch",
            hide_index=True,
            column_order=list(preview.columns),
        )


def _apply_content_styles() -> None:
    st.markdown(
        """
        <style>
        .block-container { padding-top: 1.35rem; padding-bottom: 2rem; }
        :root {
            --metric-value-size: clamp(0.7rem, 11cqi, 2.5rem);
            --metric-label-size: clamp(0.7rem, 5.5cqi, 0.9rem);
            --metric-delta-size: clamp(0.7rem, 6cqi, 1rem);
        }
        div[data-testid="stMetric"] {
            background: #f7f8fa;
            border: 1px solid #eceff3;
            border-radius: 10px;
            padding: 0.35rem 0.8rem 0.55rem 0.8rem;
            container-type: inline-size;
            min-width: 0;
        }
        div[data-testid="stVerticalBlock"] > div:has(> div[data-testid="stMetric"]) {
            gap: 0.6rem;
        }
        div[data-testid="stHorizontalBlock"] > div {
            min-width: 0;
        }
        div[data-testid="stMetricLabel"] p,
        div[data-testid="stMetricLabel"] {
            font-size: var(--metric-label-size) !important;
        }
        div[data-testid="stMetricValue"],
        div[data-testid="stMetricValue"] div,
        div[data-testid="stMetricValue"] p {
            font-size: var(--metric-value-size) !important;
            line-height: 1.3 !important;
            white-space: nowrap !important;
            overflow: hidden !important;
            text-overflow: clip !important;
        }
        div[data-testid="stMetricDelta"] {
            font-size: var(--metric-delta-size) !important;
        }
        .period-range-card {
            background: #f7f8fa;
            border: 1px solid #eceff3;
            border-radius: 10px;
            padding: 0.35rem 0.8rem 0.55rem 0.8rem;
            container-type: inline-size;
            min-width: 0;
        }
        .period-range-label {
            font-size: var(--metric-label-size);
            color: rgba(49, 51, 63, 0.6);
        }
        .period-range-value {
            font-size: var(--metric-value-size);
            font-weight: 600;
            color: rgb(49, 51, 63);
            line-height: 1.3;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: clip;
            margin: 0.1rem 0 0.15rem 0;
        }
        .period-range-delta {
            color: rgb(9, 171, 59);
            font-size: var(--metric-delta-size);
            font-weight: 500;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
    components.html(
        """
        <script>
        (function () {
          const win = window.parent;
          const doc = win.document;
          const MIN = 10;

          function targets() {
            return [
              ...doc.querySelectorAll('[data-testid="stMetricValue"]'),
              ...doc.querySelectorAll(".period-range-value"),
            ];
          }

          function fitOne(el) {
            const nodes = [el, ...el.querySelectorAll("div, p, span")];
            nodes.forEach((node) => node.style.removeProperty("font-size"));
            let size = parseFloat(win.getComputedStyle(el).fontSize) || 22;
            let guard = 48;
            const overflow = () =>
              nodes.some((node) => node.scrollWidth > node.clientWidth + 1);
            while (overflow() && size > MIN && guard--) {
              size -= 0.5;
              nodes.forEach((node) =>
                node.style.setProperty("font-size", size + "px", "important")
              );
            }
          }

          function fitAll() {
            targets().forEach(fitOne);
          }

          let timer = null;
          function scheduleFit() {
            if (timer !== null) {
              return;
            }
            timer = win.setTimeout(function () {
              timer = null;
              fitAll();
            }, 50);
          }

          fitAll();
          setTimeout(fitAll, 80);
          setTimeout(fitAll, 250);
          setTimeout(fitAll, 700);

          if (!win.__metricTextFitBound) {
            win.__metricTextFitBound = true;
            win.addEventListener("resize", scheduleFit);
            const observer = new win.ResizeObserver(scheduleFit);
            const watch = () => {
              targets().forEach((el) => observer.observe(el));
              doc.querySelectorAll('[data-testid="stMetric"], .period-range-card')
                .forEach((el) => observer.observe(el));
            };
            watch();
            new win.MutationObserver(function () {
              watch();
              scheduleFit();
            }).observe(doc.body, {
              childList: true,
              subtree: true,
            });
          }
        })();
        </script>
        """,
        height=0,
    )


def _style_chart(figure, height: int) -> None:
    figure.update_layout(
        template="simple_white",
        margin=dict(l=4, r=16, t=8, b=8),
        height=height,
        showlegend=False,
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(size=12),
    )
    figure.update_xaxes(gridcolor="#eef0f3")
    figure.update_yaxes(gridcolor="#eef0f3")


def _render_bar_chart(
    view: AggregationView,
    table: pd.DataFrame | None = None,
    max_bars: int | None = None,
    chart_key: str | None = None,
) -> None:
    table = view.table if table is None else table
    if table.empty:
        st.info("표시할 집계가 없습니다.")
        return

    limit = CHART_MAX_BARS if max_bars is None else max_bars
    chart_table = table.head(limit)
    if max_bars is None and len(table) > CHART_MAX_BARS:
        st.caption(f"차트는 상위 {CHART_MAX_BARS}개만 표시합니다.")

    plot_data = chart_table.iloc[::-1]
    figure = px.bar(
        plot_data,
        x=COUNT_COLUMN,
        y=view.category_label,
        orientation="h",
        text=COUNT_COLUMN,
    )
    figure.update_traces(textposition="outside", cliponaxis=False, textfont_size=11)
    _style_chart(figure, height=max(280, 24 * len(plot_data) + 64))
    figure.update_layout(xaxis_title="", yaxis_title="")
    figure.update_xaxes(rangemode="tozero")
    st.plotly_chart(figure, width="stretch", key=chart_key, config={"displayModeBar": False})


def _render_aggregation(
    view: AggregationView,
    *,
    top_n: int | None = None,
    show_title: bool = True,
    stacked: bool = False,
) -> None:
    display_table = view.table.head(top_n) if top_n is not None else view.table
    if show_title:
        st.subheader(view.title)
    if top_n is not None:
        st.caption(f"상위 {len(display_table):,}개 · 기간 내 합계 {view.total_count:,}건")
    else:
        st.caption(f"구분 {len(view.table):,}개 · 합계 {view.total_count:,}건")

    table_widget = dict(
        width="stretch",
        hide_index=True,
        height=min(RANKING_TABLE_HEIGHT, 48 + 35 * max(len(display_table), 1)),
        column_config={
            COUNT_COLUMN: st.column_config.NumberColumn("접수건수", format="%d"),
        },
    )
    if stacked:
        st.dataframe(display_table, **table_widget)
        _render_bar_chart(
            view,
            table=display_table,
            max_bars=top_n,
            chart_key=f"agg_bar_stacked_{view.key}",
        )
        return

    table_column, chart_column = st.columns((1, 1.3))
    with table_column:
        st.dataframe(display_table, **table_widget)
    with chart_column:
        _render_bar_chart(
            view,
            table=display_table,
            max_bars=top_n,
            chart_key=f"snapshot_bar_{view.key}",
        )


def _render_sidebar_menu() -> str:
    st.sidebar.header("메뉴")
    return st.sidebar.radio(
        "화면 선택",
        options=[MENU_DASHBOARD, MENU_CRITERIA, MENU_EXCLUSIONS],
        key="app_menu",
        label_visibility="collapsed",
        help="대시보드에서 현황을 보거나, 집계 기준·제외 항목을 관리합니다.",
    )


def _render_reload_button() -> None:
    st.sidebar.divider()
    if st.sidebar.button("데이터 다시 불러오기", width="stretch"):
        _cached_load.clear()
        st.rerun()
    st.sidebar.caption("구글 드라이브의 최신 접수건을 다시 읽어 옵니다.")


def _render_sidebar_filters(result: LoadResult, working: pd.DataFrame) -> DashboardFilters:
    st.sidebar.header("조회 조건")

    if result.date_min is None or result.date_max is None:
        st.sidebar.error("접수일 정보가 없어 날짜를 선택할 수 없습니다.")
        st.stop()

    status_options = list_status_options(working)
    if (
        "selected_status" not in st.session_state
        or st.session_state.selected_status not in status_options
    ):
        st.session_state.selected_status = STATUS_FILTER_ALL

    selected_status = st.sidebar.selectbox(
        "진행상태",
        options=status_options,
        key="selected_status",
        help="선택한 진행상태만 집계합니다. 기본값은 전체입니다.",
    )

    min_date = result.date_min.date()
    max_date = result.date_max.date()

    st.sidebar.subheader("일자 지정")
    if "selected_date" not in st.session_state:
        st.session_state.selected_date = max_date
    elif st.session_state.selected_date < min_date or st.session_state.selected_date > max_date:
        st.session_state.selected_date = max_date

    selected_date = _as_date(
        st.sidebar.date_input(
            "조회일",
            min_value=min_date,
            max_value=max_date,
            key="selected_date",
            help="일자 지정 현황 탭에서 볼 하루입니다.",
        )
    )

    st.sidebar.subheader("기간 지정")
    if "period_start" not in st.session_state:
        st.session_state.period_start = min_date
    elif st.session_state.period_start < min_date or st.session_state.period_start > max_date:
        st.session_state.period_start = min_date

    start_date = _as_date(
        st.sidebar.date_input(
            "시작일",
            min_value=min_date,
            max_value=max_date,
            key="period_start",
            help="기간 추이·주간 추이 탭의 시작일입니다.",
        )
    )

    if "period_end" not in st.session_state:
        st.session_state.period_end = max_date
    if st.session_state.period_end < start_date:
        st.session_state.period_end = start_date
    elif st.session_state.period_end > max_date:
        st.session_state.period_end = max_date

    end_date = _as_date(
        st.sidebar.date_input(
            "종료일",
            min_value=start_date,
            max_value=max_date,
            key="period_end",
            help="기간 추이·주간 추이 탭의 종료일입니다.",
        )
    )

    st.sidebar.caption(f"데이터 기간: {min_date:%Y-%m-%d} ~ {max_date:%Y-%m-%d}")
    return DashboardFilters(
        selected_date=selected_date,
        start_date=start_date,
        end_date=end_date,
        selected_status=selected_status,
        exclusions=ExclusionList(),
        specs=[],
    )


def _exclusion_summary_text(
    exclusions: ExclusionList,
    specs: list[AggregationSpec],
) -> str:
    parts = [
        f"제외 {spec.label} {len(exclusions.values_for(spec.column))}개"
        for spec in specs
        if exclusions.values_for(spec.column)
    ]
    return " · ".join(parts) if parts else "제외 항목 없음"


def _persist_exclusions(updated: ExclusionList) -> None:
    try:
        save_exclusions(updated)
    except ExclusionSaveError as error:
        st.error(error.user_message)
        return
    st.session_state["exclusion_save_message"] = True
    st.rerun()


def _render_exclusion_group(
    title: str,
    current_items: list[str],
    source_values: list[str],
    present_in_data: set[str],
    group_key: str,
    exclusions: ExclusionList,
    field_name: str,
) -> None:
    st.subheader(title)
    if not current_items:
        st.info("아직 제외한 항목이 없습니다. 아래에서 선택해 제외할 수 있습니다.")
    else:
        for index, name in enumerate(current_items):
            name_column, button_column = st.columns([4, 1])
            suffix = " · 원본에 없음" if name not in present_in_data else ""
            name_column.write(f"{name}{suffix}")
            if button_column.button("해제", key=f"remove_{group_key}_{index}"):
                remaining = [
                    item for item_index, item in enumerate(current_items) if item_index != index
                ]
                _persist_exclusions(exclusions.with_column(field_name, remaining))

    addable = [value for value in source_values if value not in set(current_items)]
    st.markdown("**제외 등록**")
    if not addable:
        st.caption("더 등록할 항목이 없습니다.")
        return

    selected = st.selectbox(
        f"제외할 {title}",
        options=addable,
        index=None,
        placeholder="검색 또는 선택",
        key=f"add_select_{group_key}",
    )
    if st.button("제외 등록", key=f"add_button_{group_key}", disabled=selected is None):
        if selected:
            _persist_exclusions(exclusions.with_column(field_name, [*current_items, selected]))


def _render_exclusion_page(
    dataframe: pd.DataFrame,
    exclusions: ExclusionList,
    specs: list[AggregationSpec],
) -> None:
    st.header("제외 항목 관리")
    st.caption("기준관리에 등록된 항목만 여기서 제외할 수 있습니다. 해제를 누르면 다시 포함됩니다.")

    if st.session_state.pop("exclusion_save_message", None):
        st.success("저장되었습니다.")

    if not specs:
        st.info("집계 기준이 없습니다. 기준관리에서 컬럼을 추가하면 제외 항목도 함께 나타납니다.")
        return

    active = exclusions.active_for([spec.column for spec in specs])
    if active.is_empty:
        st.info("현재 제외 항목이 없어 전체 데이터가 집계됩니다.")
    else:
        st.info(_exclusion_summary_text(active, specs))

    for start in range(0, len(specs), 3):
        row_specs = specs[start:start + 3]
        columns = st.columns(len(row_specs))
        for column, spec in zip(columns, row_specs):
            source_values = list_column_values(dataframe, spec.column)
            with column:
                _render_exclusion_group(
                    title=spec.label,
                    current_items=exclusions.values_for(spec.column),
                    source_values=source_values,
                    present_in_data=set(source_values),
                    group_key=f"ex_{spec.column}",
                    exclusions=exclusions,
                    field_name=spec.column,
                )


def _persist_criteria(
    updated: CriteriaList,
    exclusions: ExclusionList | None = None,
) -> None:
    try:
        save_criteria(updated)
        if exclusions is not None:
            save_exclusions(exclusions)
    except (CriteriaSaveError, ExclusionSaveError) as error:
        st.error(error.user_message)
        return
    st.session_state["criteria_save_message"] = True
    st.rerun()


def _render_criteria_page(
    available_columns: list[str],
    criteria: CriteriaList,
    exclusions: ExclusionList,
) -> None:
    st.header("기준관리")
    st.caption(
        "대시보드 집계에 쓸 컬럼을 고릅니다. 여기에 있는 항목만 제외 항목 관리에도 나타납니다."
    )

    if st.session_state.pop("criteria_save_message", None):
        st.success("저장되었습니다.")

    current = criteria.normalized()
    if not current.columns:
        st.info("등록된 기준이 없습니다. 아래에서 컬럼을 추가해 주세요.")
    else:
        st.subheader("현재 기준")
        for column in current.columns:
            name_column, button_column = st.columns([4, 1])
            default_mark = " · 기본" if column in DEFAULT_CRITERIA_COLUMNS else ""
            name_column.write(f"**{column_label(column)}** (`{column}`){default_mark}")
            if button_column.button("삭제", key=f"criteria_remove_{column}"):
                _persist_criteria(
                    current.without(column),
                    exclusions.without_column(column),
                )

    addable = addable_columns(available_columns, current.columns)
    st.subheader("기준 추가")
    if not addable:
        st.caption("더 추가할 컬럼이 없습니다.")
        return

    selected = st.selectbox(
        "추가할 컬럼",
        options=addable,
        index=None,
        format_func=lambda column: f"{column_label(column)} ({column})"
        if column_label(column) != column
        else column,
        placeholder="검색 또는 선택",
        key="criteria_add_select",
    )
    if st.button("기준 추가", disabled=selected is None):
        if selected:
            _persist_criteria(current.with_added(selected), exclusions)


def _render_snapshot_tab(
    dataframe: pd.DataFrame,
    filters: DashboardFilters,
) -> None:
    if not filters.specs:
        st.caption("집계 기준이 없습니다. 기준관리에서 컬럼을 추가해 주세요.")
    else:
        st.caption("조회일 접수건을 기준으로 집계합니다.")

    if dataframe.empty:
        if filters.selected_status == STATUS_FILTER_ALL:
            st.warning(
                f"{filters.selected_date:%Y-%m-%d}에 접수된 건이 없습니다. 다른 날짜를 선택해 주세요."
            )
        else:
            st.warning(
                f"{filters.selected_date:%Y-%m-%d}, 진행상태 '{filters.selected_status}' "
                "조건에 맞는 접수건이 없습니다. 필터를 바꿔 주세요."
            )
        return

    views = build_aggregations(dataframe, filters.specs)
    if not views:
        st.info("집계할 기준이 없습니다. 기준관리에서 컬럼을 추가해 주세요.")
        return

    if len(views) == 1:
        _render_aggregation(views[0], show_title=False)
        return

    view_tabs = st.tabs([view.category_label for view in views])
    for tab, view in zip(view_tabs, views):
        with tab:
            _render_aggregation(view, show_title=False)


def _render_trend_line(trend: pd.DataFrame, chart_key: str) -> None:
    figure = px.line(
        trend,
        x=COL_RECEIVED_DATE,
        y=COUNT_COLUMN,
        markers=True,
    )
    figure.update_traces(marker=dict(size=6))
    _style_chart(figure, height=TREND_CHART_HEIGHT)
    figure.update_layout(xaxis_title="", yaxis_title="")
    figure.update_yaxes(rangemode="tozero")
    st.plotly_chart(figure, width="stretch", key=chart_key, config={"displayModeBar": False})


def _selected_row_label(
    table: pd.DataFrame,
    category_label: str,
    widget_key: str,
) -> str | None:
    event = st.dataframe(
        table,
        width="stretch",
        hide_index=True,
        height=RANKING_TABLE_HEIGHT,
        on_select="rerun",
        selection_mode="single-row",
        key=widget_key,
        column_config={
            COUNT_COLUMN: st.column_config.NumberColumn("접수건수", format="%d"),
        },
    )
    rows = list(getattr(getattr(event, "selection", None), "rows", []) or [])
    if not rows:
        return None
    row_index = int(rows[0])
    if row_index < 0 or row_index >= len(table):
        return None
    return str(table.iloc[row_index][category_label])


def _render_period_category_panel(
    dataframe: pd.DataFrame,
    filters: DashboardFilters,
    view: AggregationView,
) -> None:
    selection_state_key = f"period_selected_{view.key}"
    reset_state_key = f"period_reset_{view.key}"
    if reset_state_key not in st.session_state:
        st.session_state[reset_state_key] = 0

    selected_label = st.session_state.get(selection_state_key)
    table_column, trend_column = st.columns((0.92, 1.2), gap="large")
    with table_column:
        header_left, header_right = st.columns([3, 1.2])
        header_left.caption(f"{view.category_label} {len(view.table):,}개 · 합계 {view.total_count:,}건")
        with header_right:
            if selected_label and st.button(
                "선택 해제",
                key=f"period_clear_{view.key}",
                width="stretch",
            ):
                st.session_state[selection_state_key] = None
                st.session_state[reset_state_key] += 1
                st.rerun()
        clicked_label = _selected_row_label(
            view.table,
            view.category_label,
            widget_key=f"period_table_{view.key}_{st.session_state[reset_state_key]}",
        )
        if clicked_label is not None:
            st.session_state[selection_state_key] = clicked_label
            selected_label = clicked_label

    if selected_label:
        trend_source = filter_by_category(dataframe, view.key, selected_label)
        trend_title = selected_label
        trend_caption = f"선택한 {view.category_label}의 일별 추이"
    else:
        trend_source = dataframe
        trend_title = "전체"
        trend_caption = "행을 클릭하면 해당 항목만 볼 수 있습니다."

    trend = aggregate_daily_trend(trend_source, filters.start_date, filters.end_date)
    with trend_column:
        st.markdown(f"**{trend_title}**")
        st.caption(trend_caption)
        metric_columns = st.columns(2)
        metric_columns[0].metric("건수", f"{len(trend_source):,}")
        metric_columns[1].metric(
            "일평균",
            f"{(len(trend_source) / len(trend) if len(trend) else 0):.1f}",
        )
        _render_trend_line(trend, chart_key=f"period_trend_{view.key}")
        with st.expander("일별 건수", expanded=False):
            st.dataframe(
                trend,
                width="stretch",
                hide_index=True,
                height=min(280, 48 + 35 * max(len(trend), 1)),
                key=f"period_trend_table_{view.key}",
                column_config={
                    COUNT_COLUMN: st.column_config.NumberColumn("접수건수", format="%d"),
                },
            )


def _render_period_tab(
    dataframe: pd.DataFrame,
    filters: DashboardFilters,
) -> None:
    trend = aggregate_daily_trend(dataframe, filters.start_date, filters.end_date)
    day_count = len(trend)
    period_count = len(dataframe)
    daily_average = period_count / day_count if day_count else 0

    metric_columns = st.columns(3)
    metric_columns[0].metric("기간 접수건수", f"{period_count:,}건")
    metric_columns[1].metric("일평균", f"{daily_average:.1f}건")
    metric_columns[2].metric("조회 일수", f"{day_count:,}일")

    if dataframe.empty:
        st.warning("선택한 기간·진행상태에 해당하는 접수건이 없습니다. 필터를 바꿔 주세요.")
        return

    views = build_aggregations(dataframe, filters.specs)
    if not views:
        st.info("집계할 기준이 없습니다. 기준관리에서 컬럼을 추가해 주세요.")
        return
    aggregation_tabs = st.tabs([view.category_label for view in views])
    for tab, view in zip(aggregation_tabs, views):
        with tab:
            _render_period_category_panel(dataframe, filters, view)


def _render_weekly_bar(weekly: pd.DataFrame) -> None:
    if weekly.empty:
        st.info("표시할 주간 추이가 없습니다.")
        return
    figure = px.bar(
        weekly,
        x=WEEK_COLUMN,
        y=COUNT_COLUMN,
        text=COUNT_COLUMN,
    )
    figure.update_traces(textposition="outside", cliponaxis=False, textfont_size=11)
    _style_chart(figure, height=TREND_CHART_HEIGHT)
    figure.update_layout(xaxis_title="", yaxis_title="")
    figure.update_yaxes(rangemode="tozero")
    st.plotly_chart(figure, width="stretch", key="weekly_bar", config={"displayModeBar": False})


def _render_weekly_tab(
    dataframe: pd.DataFrame,
    filters: DashboardFilters,
) -> None:
    weekly = aggregate_weekly_trend(dataframe, filters.start_date, filters.end_date)
    week_count = len(weekly)
    period_count = len(dataframe)
    weekly_average = period_count / week_count if week_count else 0

    metric_columns = st.columns(3)
    metric_columns[0].metric("기간 접수건수", f"{period_count:,}건")
    metric_columns[1].metric("주 수", f"{week_count:,}주")
    metric_columns[2].metric("주평균", f"{weekly_average:.1f}건")

    if dataframe.empty:
        st.warning("선택한 기간·진행상태에 해당하는 접수건이 없습니다. 왼쪽에서 기간이나 진행상태를 바꿔 주세요.")
        return

    _render_weekly_bar(weekly)
    with st.expander("주별 건수", expanded=False):
        st.dataframe(
            weekly,
            width="stretch",
            hide_index=True,
            key="weekly_table",
            column_config={
                COUNT_COLUMN: st.column_config.NumberColumn("접수건수", format="%d"),
            },
        )


def _render_dashboard_filter_summary(
    filters: DashboardFilters,
    snapshot_count: int,
    period_count: int,
    excluded_count: int,
) -> None:
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("진행상태", filters.selected_status)
    col2.metric("조회일", f"{filters.selected_date:%Y-%m-%d}", f"{snapshot_count:,}건")
    with col3:
        st.markdown(
            f'<div class="period-range-card">'
            f'<div class="period-range-label">조회기간</div>'
            f'<div class="period-range-value">'
            f"{filters.start_date:%m-%d} ~ {filters.end_date:%m-%d}"
            f"</div>"
            f'<div class="period-range-delta">↑ {period_count:,}건</div>'
            f"</div>",
            unsafe_allow_html=True,
        )
    exclusion_label = _exclusion_summary_text(filters.exclusions, filters.specs)
    col4.metric("제외", "없음" if exclusion_label == "제외 항목 없음" else "적용 중")
    if excluded_count:
        st.caption(f"{exclusion_label} · 집계에서 {excluded_count:,}건이 빠졌습니다.")
    elif exclusion_label != "제외 항목 없음":
        st.caption(exclusion_label)


def main() -> None:
    _apply_content_styles()
    st.title("서비스 접수 현황")

    try:
        result = _cached_load()
    except DataLoadError as error:
        _render_error(error)
    except Exception as error:
        _render_error(
            DataLoadError(
                "데이터를 불러오는 중 문제가 발생했습니다. 잠시 후 다시 시도해 주세요.",
                detail=type(error).__name__,
            )
        )

    leftover_pii = remaining_pii_columns(result.columns)
    if leftover_pii:
        _render_error(
            DataLoadError("개인정보 컬럼이 남아 있어 화면을 표시할 수 없습니다.")
        )

    menu = _render_sidebar_menu()
    criteria_list, criteria_warning = load_criteria_file()
    if criteria_warning:
        st.warning(criteria_warning)
    specs = criteria_list.specs
    exclusion_list, exclusion_warning = load_exclusion_file()
    if exclusion_warning:
        st.warning(exclusion_warning)
    active_exclusions = exclusion_list.active_for(criteria_list.columns)
    working = apply_exclusions(result.dataframe, active_exclusions)

    if menu == MENU_CRITERIA:
        _render_reload_button()
        _render_criteria_page(result.columns, criteria_list, exclusion_list)
        return

    if menu == MENU_EXCLUSIONS:
        _render_reload_button()
        _render_exclusion_page(result.dataframe, exclusion_list, specs)
        return

    filters = _render_sidebar_filters(result, working)._replace(
        exclusions=active_exclusions,
        specs=specs,
    )
    _render_reload_button()
    snapshot_data = apply_common_filters(
        working,
        selected_date=filters.selected_date,
        selected_status=filters.selected_status,
    )
    period_data = apply_common_filters(
        working,
        start_date=filters.start_date,
        end_date=filters.end_date,
        selected_status=filters.selected_status,
    )
    excluded_count = result.row_count - len(working)

    _render_dashboard_filter_summary(
        filters,
        snapshot_count=len(snapshot_data),
        period_count=len(period_data),
        excluded_count=excluded_count,
    )

    snapshot_tab, period_tab, weekly_tab = st.tabs(
        ["일자 지정 현황", "기간 추이(일별)", "주간별 추이"]
    )
    with snapshot_tab:
        _render_snapshot_tab(snapshot_data, filters)
    with period_tab:
        _render_period_tab(period_data, filters)
    with weekly_tab:
        _render_weekly_tab(period_data, filters)

    _render_load_summary(result)


if __name__ == "__main__":
    main()
