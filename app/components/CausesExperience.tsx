"use client";

import dynamic from "next/dynamic";
import { useEffect, useMemo, useState } from "react";
import {
  Activity, CalendarDays, Check, ChevronDown, CircleHelp, Columns2, Database,
  Info, Layers3, LineChart, LoaderCircle, Map as MapIcon, SlidersHorizontal, Waves,
} from "lucide-react";

import {
  getBarystaticMap, getBarystaticSeries, getBarystaticStatus, getBarystaticTrendMap,
  getCauseOverviewMap, getCauseOverviewSeries, getCauseOverviewStatus,
  getCombinedBarystaticMap, getCombinedBarystaticSeries, getCombinedBarystaticTrendMap,
  type BarystaticMap, type BarystaticSeries, type BarystaticStatus, type BarystaticTrendMap,
  type CauseOverviewLayer, type CauseOverviewSeries, type CauseOverviewStatus,
} from "../lib/barystatic-api";
import styles from "./CausesExperience.module.css";

const Plot = dynamic(() => import("react-plotly.js"), { ssr: false });
const CauseWorldMap = dynamic(() => import("./CauseWorldMap"), { ssr: false });

type MainView = "overview" | "barystatic";
type DetailMode = "individual" | "groups";
type DisplayMode = "monthly" | "moving" | "both";
type MapMode = "month" | "trend";
type Assignment = "A" | "B" | "off";
type GridData = BarystaticMap | BarystaticTrendMap;
type ComponentDefinition = { key: string; label: string; short: string; family: "ice" | "water"; color: string; quality: "monthly" | "interpolated" | "extrapolated"; analysisStart: string; analysisEnd: string };
type SeriesItem = { id: string; label: string; color: string; data: BarystaticSeries };

const components: ComponentDefinition[] = [
  { key: "antarctica", label: "남극 빙상", short: "남극", family: "ice", color: "#245a86", quality: "monthly", analysisStart: "1993-01", analysisEnd: "2020-12" },
  { key: "greenland", label: "그린란드 빙상", short: "그린란드", family: "ice", color: "#168fa8", quality: "monthly", analysisStart: "1993-01", analysisEnd: "2020-12" },
  { key: "mountain_glaciers", label: "산악 빙하", short: "산악 빙하", family: "ice", color: "#55b7c6", quality: "monthly", analysisStart: "1993-01", analysisEnd: "2016-12" },
  { key: "groundwater", label: "지하수 고갈", short: "지하수", family: "water", color: "#d47b49", quality: "extrapolated", analysisStart: "1993-01", analysisEnd: "2023-04" },
  { key: "dam_reservoir_storage", label: "댐 저수", short: "댐", family: "water", color: "#b75b46", quality: "interpolated", analysisStart: "1993-01", analysisEnd: "2017-12" },
  { key: "seasonal_snow", label: "적설", short: "적설", family: "water", color: "#8469b6", quality: "monthly", analysisStart: "1993-01", analysisEnd: "2022-12" },
  { key: "soil_moisture", label: "토양 수분", short: "토양 수분", family: "water", color: "#6f8655", quality: "monthly", analysisStart: "1993-01", analysisEnd: "2022-12" },
];

const componentByKey = Object.fromEntries(components.map((item) => [item.key, item])) as Record<string, ComponentDefinition>;
const qualityLabel = { monthly: "월자료", interpolated: "연도 사이 계산값", extrapolated: "2011년 이후 선형 연장" };
const groupKeys = (assignments: Record<string, Assignment>, group: "A" | "B") => components.filter((item) => assignments[item.key] === group).map((item) => item.key);
const commonPeriod = (keys: string[]) => {
  const chosen = keys.map((key) => componentByKey[key]).filter(Boolean);
  if (!chosen.length) return null;
  return {
    start: chosen.reduce((latest, item) => item.analysisStart > latest ? item.analysisStart : latest, chosen[0].analysisStart),
    end: chosen.reduce((earliest, item) => item.analysisEnd < earliest ? item.analysisEnd : earliest, chosen[0].analysisEnd),
  };
};
const countMonths = (start: string, end: string) => {
  if (!/^\d{4}-\d{2}$/.test(start) || !/^\d{4}-\d{2}$/.test(end)) return 0;
  const [sy, sm] = start.split("-").map(Number);
  const [ey, em] = end.split("-").map(Number);
  return (ey - sy) * 12 + em - sm + 1;
};
const gridMaximum = (data: GridData | null) => {
  if (!data) return 0;
  let maximum = 0;
  data.values.forEach((row) => row.forEach((value) => {
    if (value != null && Number.isFinite(value)) maximum = Math.max(maximum, Math.abs(value));
  }));
  return maximum;
};

function Segmented<T extends string>({ value, options, onChange }: { value: T; options: { value: T; label: string }[]; onChange: (value: T) => void }) {
  return <div className={styles.segmented}>{options.map((option) => (
    <button type="button" key={option.value} className={value === option.value ? styles.active : ""} onClick={() => onChange(option.value)}>{option.label}</button>
  ))}</div>;
}

function CauseOverviewChart({ data, loading, error }: {
  data: CauseOverviewSeries | null;
  loading: boolean;
  error: string | null;
}) {
  if (loading) return <div className={styles.overviewChartState}><LoaderCircle className={styles.spin} /><b>관측 SLA와 GRACE를 불러오고 있습니다.</b></div>;
  if (error || !data) return <div className={styles.overviewChartState}><Info /><b>{error ?? "공통 비교 시계열을 표시할 수 없습니다."}</b></div>;
  const dates = data.series.map((point) => point.date);
  return <Plot
    data={[
      { x: dates, y: data.series.map((point) => point.observed_mm), type: "scatter", mode: "lines", name: "관측 SLA · 월별", line: { color: "#238fa5", width: 1 }, opacity: 0.25, hovertemplate: "%{x|%Y-%m}<br>%{y:.2f} mm<extra>관측 SLA · 월별</extra>" },
      { x: dates, y: data.series.map((point) => point.observed_moving_12m_mm), type: "scatter", mode: "lines", name: "관측 SLA · 12개월", line: { color: "#146b86", width: 2.8 }, hovertemplate: "%{x|%Y-%m}<br>%{y:.2f} mm<extra>관측 SLA · 12개월</extra>" },
      { x: dates, y: data.series.map((point) => point.grace_mm), type: "scatter", mode: "lines", name: "GRACE · 월별", line: { color: "#d47b49", width: 1 }, opacity: 0.28, connectgaps: false, hovertemplate: "%{x|%Y-%m}<br>%{y:.2f} mm<extra>GRACE · 월별</extra>" },
      { x: dates, y: data.series.map((point) => point.grace_moving_12m_mm), type: "scatter", mode: "lines", name: "GRACE · 12개월", line: { color: "#a75534", width: 2.8 }, connectgaps: false, hovertemplate: "%{x|%Y-%m}<br>%{y:.2f} mm<extra>GRACE · 12개월</extra>" },
    ]}
    layout={{
      autosize: true, height: 360, margin: { l: 58, r: 22, t: 30, b: 52 },
      paper_bgcolor: "transparent", plot_bgcolor: "#f8fbfd", hovermode: "x unified",
      font: { family: "Arial, Noto Sans KR, sans-serif", color: "#32485a", size: 12 },
      legend: { orientation: "h", x: 0, y: 1.16 },
      xaxis: { gridcolor: "#dfeaf0", title: { text: "관측 시기" } },
      yaxis: { gridcolor: "#dfeaf0", zerolinecolor: "#8eaab8", title: { text: "공통 해양 영역 평균 변화량 (mm)" } },
    }}
    config={{ responsive: true, displaylogo: false, modeBarButtonsToRemove: ["lasso2d", "select2d"] }}
    useResizeHandler className={styles.plot}
  />;
}

function Overview() {
  const [date, setDate] = useState("2016-12");
  const [layer, setLayer] = useState<CauseOverviewLayer>("observed");
  const [status, setStatus] = useState<CauseOverviewStatus | null>(null);
  const [series, setSeries] = useState<CauseOverviewSeries | null>(null);
  const [map, setMap] = useState<BarystaticMap | null>(null);
  const [seriesLoading, setSeriesLoading] = useState(true);
  const [mapLoading, setMapLoading] = useState(true);
  const [seriesError, setSeriesError] = useState<string | null>(null);
  const [mapError, setMapError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    Promise.all([
      getCauseOverviewStatus(),
      getCauseOverviewSeries("2003-01", "2023-04"),
    ]).then(([nextStatus, nextSeries]) => {
      if (!active) return;
      setStatus(nextStatus);
      setSeries(nextSeries);
      setSeriesError(null);
    }).catch((error: Error) => {
      if (active) setSeriesError(error.message);
    }).finally(() => {
      if (active) setSeriesLoading(false);
    });
    return () => { active = false; };
  }, []);

  useEffect(() => {
    let active = true;
    getCauseOverviewMap(date, layer).then((nextMap) => {
      if (active) {
        setMap(nextMap);
        setMapError(null);
      }
    }).catch((error: Error) => {
      if (active) setMapError(error.message);
    }).finally(() => {
      if (active) setMapLoading(false);
    });
    return () => { active = false; };
  }, [date, layer]);

  const selectLayer = (nextLayer: CauseOverviewLayer) => {
    setLayer(nextLayer);
    setMapLoading(true);
    setMap(null);
    setMapError(null);
  };

  const maximum = Math.max(gridMaximum(map), 0.1);
  const connected = status?.connected === true;
  return <>
    <div className={connected ? styles.dataNotice : seriesError ? styles.dataNoticeError : styles.dataNotice}>
      {connected ? <Check size={17} /> : seriesError ? <Info size={17} /> : <LoaderCircle className={styles.spin} size={17} />}
      <div>
        <b>{connected ? "Copernicus 관측 SLA와 GRACE 실제 자료 연결됨" : seriesError ? "공통 비교 자료를 불러오지 못했습니다" : "자료 연결 상태를 확인하고 있습니다"}</b>
        <span>{connected ? `두 자료를 같은 1° 해양 격자 ${status?.common_ocean_cells?.toLocaleString() ?? "—"}개에서 비교합니다. GRACE 임무 공백은 채우지 않았습니다.` : seriesError ?? "잠시 기다려 주세요."}</span>
      </div>
    </div>
    <div className={styles.workspace}>
      <aside className={styles.controls}>
        <div className={styles.panelHeading}><div><span>탐구 설정</span><h2>한 달의 원인 지도</h2></div><SlidersHorizontal size={18} /></div>
        <label className={styles.field}><span><CalendarDays size={14} /> 확인할 월</span><input type="month" value={date} min="2003-01" max="2023-04" onChange={(event) => {
          setDate(event.target.value);
          setMapLoading(true);
          setMap(null);
          setMapError(null);
        }} /></label>
        <fieldset className={styles.optionList}><legend>지도에 표시할 자료</legend>
          <label><input type="radio" name="overview-layer" checked={layer === "observed"} onChange={() => selectLayer("observed")} /><span>관측 해수면<small>Copernicus 월평균 SLA</small></span></label>
          <label className={styles.unavailableOption}><input type="radio" name="overview-layer" disabled /><span>Steric<small>수온·염분 계산 준비</small></span></label>
          <label><input type="radio" name="overview-layer" checked={layer === "grace"} onChange={() => selectLayer("grace")} /><span>GRACE 질량<small>실제 fingerprint</small></span></label>
          <label className={styles.unavailableOption}><input type="radio" name="overview-layer" disabled /><span>Steric + GRACE<small>Steric 연결 후 활성화</small></span></label>
          <label className={styles.unavailableOption}><input type="radio" name="overview-layer" disabled /><span>관측값 − 성분 합<small>세 자료 연결 후 활성화</small></span></label>
        </fieldset>
        <div className={styles.referenceNote}><Database size={15} /><span><b>공통 기준</b>각 격자에서 2003–2010년 평균을 제거했습니다.</span></div>
        <div className={styles.gapNote}><Info size={14} /><span><b>자료가 없는 기간</b>2017-06–2018-05는 GRACE와 GRACE-FO 사이의 임무 공백입니다.</span></div>
      </aside>
      <section className={styles.mapCard}>
        <div className={styles.cardHead}><div><span>{layer === "observed" ? "관측된 해수면 높이 변화" : "해양 질량 변화 · Fingerprint"}</span><h2>{layer === "observed" ? "Copernicus SLA 공간분포" : "GRACE 상대 해수면 공간분포"}</h2><p>{layer === "observed" ? "위성 고도계로 관측한 전체 해수면 변화입니다." : "육지 질량 변화를 원인으로 계산된 해양의 상대 해수면 반응입니다."}</p></div><span className={styles.statusPill}><MapIcon size={14} /> 공통 전 지구 1°</span></div>
        <div className={styles.mapSingle}>
          <CauseWorldMap title={layer === "observed" ? "관측된 해수면 변화" : "GRACE 해양 질량 변화"} subtitle={`${date} · 2003–2010년 평균 대비`} data={map} loading={mapLoading} error={mapError} scaleMax={maximum} sharedScale={false} />
        </div>
      </section>
    </div>
    <section className={styles.chartCard}>
      <div className={styles.cardHead}><div><span>고정된 공통 해양 영역의 면적가중 평균</span><h2>관측된 변화와 GRACE 질량 변화 비교</h2><p>같은 격자와 기준기간을 사용하며, GRACE 임무 공백은 선으로 이어 붙이지 않았습니다.</p></div><span className={styles.statusPill}>{series?.common_observation_months ?? "—"}개월 공통 관측</span></div>
      <CauseOverviewChart data={series} loading={seriesLoading} error={seriesError} />
    </section>
    <section className={styles.connectionCard}>
      <div className={styles.cardHead}><div><span>실제 데이터 연결 상태</span><h2>큰 그림을 구성하는 세 자료</h2><p>연결된 자료부터 실제 값으로 표시합니다.</p></div></div>
      <div className={styles.connectionRows}>
        <div><b>관측된 해수면 변화</b><span>Copernicus Marine 월평균 SLA · {series?.observed_trend_mm_per_year.toFixed(3) ?? "—"} mm/년</span><em className={styles.connectedStatus}>연결됨</em></div>
        <div><b>Steric sea level</b><span>수온·염분으로 계산할 adapter</span><em>계산 준비</em></div>
        <div><b>Ocean mass sea level</b><span>GRACE/GRACE-FO fingerprint · {series?.grace_trend_mm_per_year.toFixed(3) ?? "—"} mm/년</span><em className={styles.connectedStatus}>연결됨</em></div>
      </div>
    </section>
  </>;
}

function ComponentPicker({ mode, selected, setSelected, assignments, setAssignments }: {
  mode: DetailMode; selected: string[]; setSelected: (value: string[]) => void;
  assignments: Record<string, Assignment>; setAssignments: (value: Record<string, Assignment>) => void;
}) {
  const applyPreset = (preset: "ice" | "water" | "all" | "none") => setSelected(components.filter((item) => preset === "all" || item.family === preset).map((item) => item.key));
  return <>
    {mode === "individual" && <div className={styles.presetRow}>
      <button type="button" onClick={() => applyPreset("ice")}>빙권만</button><button type="button" onClick={() => applyPreset("water")}>육상 물만</button>
      <button type="button" onClick={() => applyPreset("all")}>전체 선택</button><button type="button" onClick={() => applyPreset("none")}>전체 해제</button>
    </div>}
    <div className={styles.componentGroups}>{(["ice", "water"] as const).map((family) => <section key={family}>
      <h3>{family === "ice" ? "빙상과 빙하" : "육상 물 저장량"}</h3>
      {components.filter((item) => item.family === family).map((item) => <div className={styles.componentRow} key={item.key}>
        <span className={styles.colorDot} style={{ background: item.color }} />
        <div className={styles.componentName}><b>{item.label}</b><small>{qualityLabel[item.quality]}</small></div>
        {mode === "individual" ? <label className={styles.checkControl}>
          <input type="checkbox" checked={selected.includes(item.key)} onChange={(event) => setSelected(event.target.checked ? [...selected, item.key] : selected.filter((key) => key !== item.key))} /><span><Check size={12} /></span>
        </label> : <div className={styles.assignment}>{(["A", "B", "off"] as Assignment[]).map((value) => <button type="button" key={value} className={assignments[item.key] === value ? styles.active : ""} onClick={() => setAssignments({ ...assignments, [item.key]: value })}>{value === "off" ? "제외" : value}</button>)}</div>}
      </div>)}
    </section>)}</div>
  </>;
}

function GroupFormula({ assignments }: { assignments: Record<string, Assignment> }) {
  const formula = (group: "A" | "B") => {
    const names = components.filter((item) => assignments[item.key] === group).map((item) => item.short);
    return names.length ? names.join(" + ") : "선택된 성분 없음";
  };
  return <section className={styles.groupFormula} aria-label="두 비교 그룹의 구성">
    <div><span>그룹 A</span><strong>{formula("A")}</strong></div><b>비교</b><div><span>그룹 B</span><strong>{formula("B")}</strong></div>
    <p><Database size={14} /> GRACE는 어느 그룹에도 더하지 않는 독립적인 관측 기준입니다.</p>
  </section>;
}

function DataAvailabilityTimeline() {
  const rows = [
    { label: "남극 빙상", width: "90%", kind: "monthly", note: "1993–2020 · 월자료" }, { label: "그린란드", width: "90%", kind: "monthly", note: "1993–2020 · 월자료" },
    { label: "산악 빙하", width: "77%", kind: "monthly", note: "1993–2016 · 월자료" }, { label: "지하수", width: "100%", kind: "groundwater", note: "2011년 이후 마지막 경향 연장" },
    { label: "댐", width: "81%", kind: "interpolated", note: "1993–2017 · 관측 사이 계산" }, { label: "적설", width: "97%", kind: "monthly", note: "1993–2022 · 월자료" },
    { label: "토양 수분", width: "97%", kind: "monthly", note: "1993–2022 · 월자료" },
  ];
  return <details className={styles.availabilityCard}>
    <summary className={styles.availabilitySummary}><div><span>자료 범위</span><h2>성분별 자료 기간과 계산 구간</h2><p>필요할 때만 펼쳐 월자료, 관측 사이 계산, 마지막 경향 연장을 확인합니다.</p></div><span className={styles.availabilityAction}>자료 범위 확인 <ChevronDown size={15} /></span></summary>
    <div className={styles.availabilityContent}><div className={styles.availabilityLegend}><span><i className={styles.monthlyKey} />월자료</span><span><i className={styles.interpolatedKey} />관측 사이 계산</span><span><i className={styles.extrapolatedKey} />마지막 경향 연장</span><span><i className={styles.missingKey} />자료 없음</span></div>
      <div className={styles.timelineScroll}><div className={styles.timelineScale}><span>1993</span><span>2000</span><span>2010</span><span>2020</span><span>2023</span></div><div className={styles.timelineRows}>
        {rows.map((row) => <div className={styles.timelineRow} key={row.label}><b>{row.label}</b><div className={styles.timelineTrack}>{row.kind === "groundwater" ? <><i className={styles.monthlyFill} style={{ width: "58%" }} /><i className={styles.extrapolatedFill} style={{ left: "58%", width: "42%" }} /></> : <i className={row.kind === "interpolated" ? styles.interpolatedFill : styles.monthlyFill} style={{ width: row.width }} />}</div><small>{row.note}</small></div>)}
        <div className={styles.timelineRow}><b>GRACE</b><div className={styles.timelineTrack}><i className={styles.graceFill} /><i className={styles.graceGap} /></div><small>변환 후 연결 · 임무 사이 공백은 채우지 않음</small></div>
      </div></div>
    </div>
  </details>;
}

function DetailChart({ items, display, showTrend, separated, spacing, loading, error }: {
  items: SeriesItem[]; display: DisplayMode; showTrend: boolean; separated: boolean; spacing: number; loading: boolean; error: string | null;
}) {
  const traces = useMemo(() => items.flatMap((item, itemIndex) => {
    const dates = item.data.series.map((point) => point.date);
    const offset = separated ? itemIndex * spacing : 0;
    const raw = item.data.series.map((point) => point.monthly_mm);
    const moving = item.data.series.map((point) => point.moving_12m_mm);
    const trend = item.data.series.map((point) => point.linear_trend_mm);
    const output = [];
    if (display !== "moving") output.push({ x: dates, y: raw.map((value) => value == null ? null : value + offset), customdata: raw, type: "scatter" as const, mode: "lines" as const, name: `${item.label}${display === "both" ? " · 월별" : ""}`, line: { color: item.color, width: display === "both" ? 1.2 : 2.2 }, opacity: display === "both" ? 0.42 : 1, hovertemplate: `%{x|%Y-%m}<br>${item.label}: %{customdata:.2f} mm<extra></extra>` });
    if (display !== "monthly") output.push({ x: dates, y: moving.map((value) => value == null ? null : value + offset), customdata: moving, type: "scatter" as const, mode: "lines" as const, name: `${item.label}${display === "both" ? " · 12개월" : ""}`, line: { color: item.color, width: 2.8 }, hovertemplate: `%{x|%Y-%m}<br>${item.label}: %{customdata:.2f} mm<extra></extra>` });
    if (showTrend) output.push({ x: dates, y: trend.map((value) => value == null ? null : value + offset), customdata: trend, type: "scatter" as const, mode: "lines" as const, name: `${item.label} · 선형 추세`, line: { color: item.color, width: 1.5, dash: "dash" as const }, hovertemplate: `%{x|%Y-%m}<br>추세: %{customdata:.2f} mm<extra></extra>` });
    return output;
  }), [display, items, separated, showTrend, spacing]);
  if (loading) return <div className={styles.chartState}><LoaderCircle className={styles.spin} /><b>실제 월자료를 불러오고 있습니다.</b></div>;
  if (error) return <div className={styles.chartState}><Info /><b>{error}</b><span>선택 기간이 모든 성분의 공통 자료 범위 안인지 확인하세요.</span></div>;
  if (!items.length) return <div className={styles.chartState}><Info /><b>비교할 성분을 하나 이상 선택하세요.</b></div>;
  return <Plot data={traces} layout={{
    autosize: true, height: 520, margin: { l: 58, r: 22, t: 34, b: 52 }, paper_bgcolor: "transparent", plot_bgcolor: "#f8fbfd", hovermode: "x unified",
    font: { family: "Arial, Noto Sans KR, sans-serif", color: "#32485a", size: 12 }, legend: { orientation: "h", x: 0, y: 1.18 },
    xaxis: { gridcolor: "#dfeaf0", title: { text: "관측 시기" } }, yaxis: { gridcolor: "#dfeaf0", zerolinecolor: "#8eaab8", title: { text: separated ? "시각적으로 분리한 높이" : "전 지구 평균 해수면 기여량 (mm)" } },
    annotations: separated ? [{ x: 1, y: 1.08, xref: "paper", yref: "paper", text: "선만 위로 옮겨 표시했습니다. hover 값은 실제 값입니다.", showarrow: false, font: { color: "#9a641d", size: 11 } }] : [],
  }} config={{ responsive: true, displaylogo: false, modeBarButtonsToRemove: ["lasso2d", "select2d"] }} useResizeHandler className={styles.plot} />;
}

function BarystaticDetail() {
  const [mode, setMode] = useState<DetailMode>("individual");
  const [selected, setSelected] = useState(["antarctica", "greenland", "mountain_glaciers"]);
  const [assignments, setAssignments] = useState<Record<string, Assignment>>(() => Object.fromEntries(components.map((item) => [item.key, item.family === "ice" ? "A" : "B"])));
  const [start, setStart] = useState("2003-01"); const [end, setEnd] = useState("2016-12");
  const [display, setDisplay] = useState<DisplayMode>("monthly"); const [showTrend, setShowTrend] = useState(false);
  const [separated, setSeparated] = useState(false); const [spacing, setSpacing] = useState(10);
  const [status, setStatus] = useState<BarystaticStatus | null>(null); const [statusError, setStatusError] = useState<string | null>(null);
  const [items, setItems] = useState<SeriesItem[]>([]); const [seriesLoading, setSeriesLoading] = useState(true); const [seriesError, setSeriesError] = useState<string | null>(null);
  const [mapMode, setMapMode] = useState<MapMode>("month"); const [mapDate, setMapDate] = useState("2016-12");
  const [mapComparison, setMapComparison] = useState(false); const [sharedScale, setSharedScale] = useState(true);
  const [individualMapA, setIndividualMapA] = useState("antarctica"); const [individualMapB, setIndividualMapB] = useState("greenland");
  const [mapA, setMapA] = useState<GridData | null>(null); const [mapB, setMapB] = useState<GridData | null>(null);
  const [mapLoading, setMapLoading] = useState(false); const [mapErrorA, setMapErrorA] = useState<string | null>(null); const [mapErrorB, setMapErrorB] = useState<string | null>(null);

  const groupA = useMemo(() => groupKeys(assignments, "A"), [assignments]);
  const groupB = useMemo(() => groupKeys(assignments, "B"), [assignments]);
  const activeKeys = mode === "individual" ? selected : [...groupA, ...groupB];
  const period = commonPeriod(activeKeys);
  const effectiveMapA = selected.includes(individualMapA) ? individualMapA : (selected[0] ?? "");
  const effectiveMapB = selected.includes(individualMapB) ? individualMapB : (selected[1] ?? selected[0] ?? "");
  const targetA = useMemo(() => mode === "individual" ? (effectiveMapA ? [effectiveMapA] : []) : groupA, [effectiveMapA, groupA, mode]);
  const targetB = useMemo(() => mode === "individual" ? (effectiveMapB ? [effectiveMapB] : []) : groupB, [effectiveMapB, groupB, mode]);
  const trendMonths = countMonths(start, end);
  const trendWarning = mapMode === "trend" && trendMonths >= 60 && trendMonths < 120 ? "10년 미만의 변화율은 계절변동과 단기 변동의 영향을 크게 받을 수 있습니다." : null;

  useEffect(() => {
    let active = true;
    getBarystaticStatus().then((result) => { if (active) { setStatus(result); setStatusError(null); } }).catch((error: Error) => { if (active) setStatusError(error.message); });
    return () => { active = false; };
  }, []);

  useEffect(() => {
    let active = true;
    const load = async () => {
      setSeriesLoading(true); setSeriesError(null);
      try {
        let next: SeriesItem[] = [];
        if (mode === "individual") {
          const results = await Promise.all(selected.map((key) => getBarystaticSeries(key, start, end)));
          next = results.map((data, index) => ({ id: selected[index], label: componentByKey[selected[index]].label, color: componentByKey[selected[index]].color, data }));
        } else {
          const requests: Promise<SeriesItem>[] = [];
          if (groupA.length) requests.push(getCombinedBarystaticSeries(groupA, start, end).then((data) => ({ id: "A", label: "그룹 A 선택 성분 합계", color: "#168fa8", data })));
          if (groupB.length) requests.push(getCombinedBarystaticSeries(groupB, start, end).then((data) => ({ id: "B", label: "그룹 B 선택 성분 합계", color: "#d47b49", data })));
          next = await Promise.all(requests);
        }
        if (active) setItems(next);
      } catch (error) {
        if (active) { setItems([]); setSeriesError(error instanceof Error ? error.message : "시계열을 불러오지 못했습니다."); }
      } finally { if (active) setSeriesLoading(false); }
    };
    void load(); return () => { active = false; };
  }, [end, groupA, groupB, mode, selected, start]);

  useEffect(() => {
    let active = true;
    const loadOne = async (keys: string[]) => {
      if (!keys.length) return null;
      if (mapMode === "trend") {
        if (trendMonths < 60) throw new Error("변화율 지도는 최소 5년(60개월) 이상의 기간이 필요합니다.");
        return keys.length === 1 ? getBarystaticTrendMap(keys[0], start, end) : getCombinedBarystaticTrendMap(keys, start, end);
      }
      return keys.length === 1 ? getBarystaticMap(keys[0], mapDate) : getCombinedBarystaticMap(keys, mapDate);
    };
    const load = async () => {
      setMapLoading(true); setMapA(null); setMapB(null); setMapErrorA(null); setMapErrorB(null);
      const first = await loadOne(targetA).then((data) => ({ data, error: null }), (error: Error) => ({ data: null, error: error.message }));
      const second = mapComparison ? await loadOne(targetB).then((data) => ({ data, error: null }), (error: Error) => ({ data: null, error: error.message })) : { data: null, error: null };
      if (active) { setMapA(first.data); setMapErrorA(first.error); setMapB(second.data); setMapErrorB(second.error); setMapLoading(false); }
    };
    void load(); return () => { active = false; };
  }, [end, mapComparison, mapDate, mapMode, start, targetA, targetB, trendMonths]);

  const ownMaxA = Math.max(gridMaximum(mapA), 0.1); const ownMaxB = Math.max(gridMaximum(mapB), 0.1); const commonMax = Math.max(ownMaxA, ownMaxB);
  const mapLabel = (keys: string[], group: "A" | "B") => mode === "individual" ? (componentByKey[keys[0]]?.label ?? "성분을 선택하세요") : `그룹 ${group} 선택 성분 합계`;
  const mapSubtitle = mapMode === "month" ? `${mapDate} · 2003–2010년 평균 대비` : `${start}–${end} · 월자료 선형 추세`;

  return <>
    <div className={statusError ? styles.dataNoticeError : styles.dataNotice}>
      {status ? <Check size={17} /> : statusError ? <Info size={17} /> : <LoaderCircle className={styles.spin} size={17} />}
      <div><b>{status ? "7개 질량 성분 실제 자료 연결됨" : statusError ? "자료 서버에 연결할 수 없습니다" : "자료 연결 상태를 확인하고 있습니다"}</b><span>{status ? "지도와 그래프는 처리된 fingerprint NetCDF에서 직접 계산합니다." : statusError ?? "잠시 기다려 주세요."}</span></div>
    </div>
    <div className={styles.detailModeRow}><Segmented value={mode} onChange={(value) => { setMode(value); setDisplay(value === "individual" ? "monthly" : "moving"); setSeparated(false); }} options={[{ value: "individual", label: "개별 성분 비교" }, { value: "groups", label: "두 그룹 비교" }]} /><span>{mode === "individual" ? `${selected.length}개 성분 표시 중 · 최대 7개` : "각 성분은 A 또는 B 한 곳에만 배정"}</span></div>
    {mode === "groups" && <GroupFormula assignments={assignments} />}
    <div className={styles.workspace}>
      <aside className={styles.controls}>
        <div className={styles.panelHeading}><div><span>성분 선택</span><h2>{mode === "individual" ? "어떤 원인을 비교할까요?" : "두 묶음을 만들어 보세요"}</h2></div><Layers3 size={18} /></div>
        <ComponentPicker mode={mode} selected={selected} setSelected={setSelected} assignments={assignments} setAssignments={setAssignments} />
        <div className={styles.periodBlock}><div><label>시작 월<input type="month" value={start} onChange={(event) => setStart(event.target.value)} /></label><label>종료 월<input type="month" value={end} onChange={(event) => setEnd(event.target.value)} /></label></div>
          <p><Info size={13} /> {period ? `현재 선택의 공통 자료 기간은 ${period.start}–${period.end}입니다.` : "성분을 하나 이상 선택하세요."}</p>
          <button type="button" disabled={!period} onClick={() => { if (!period) return; setStart(period.start); setEnd(period.end); setMapDate(period.end); }}>공통기간으로 맞추기</button>
        </div>
      </aside>
      <section className={styles.chartCard}>
        <div className={styles.cardHead}><div><span>전 지구 평균 해수면 기여량</span><h2>{mode === "individual" ? "선택한 질량 성분의 시간 변화" : "그룹 A와 그룹 B 선택 성분 합계"}</h2><p>GRACE는 변환 후 독립적인 기준선으로 추가하며, 선택 성분 합계에는 넣지 않습니다.</p></div><span className={styles.statusPill}>실제 자료</span></div>
        <div className={styles.chartTools}><Segmented value={display} onChange={setDisplay} options={[{ value: "monthly", label: "월별 값" }, { value: "moving", label: "12개월 평균" }, { value: "both", label: "둘 다" }]} /><label><input type="checkbox" checked={showTrend} onChange={(event) => setShowTrend(event.target.checked)} /> 추세선</label>{mode === "individual" && <label><input type="checkbox" checked={separated} onChange={(event) => setSeparated(event.target.checked)} /> 세로로 펼쳐 보기</label>}{separated && <label className={styles.rangeControl}>선 간격 <input type="range" min="5" max="24" value={spacing} onChange={(event) => setSpacing(Number(event.target.value))} /><b>{spacing} mm</b></label>}</div>
        <DetailChart items={items} display={display} showTrend={showTrend} separated={separated} spacing={spacing} loading={seriesLoading} error={seriesError} />
      </section>
    </div>
    <DataAvailabilityTimeline />
    <section className={styles.mapCardWide}>
      <div className={styles.cardHead}><div><span>지역별 상대 해수면 반응 · Fingerprint</span><h2>{mapMode === "month" ? "선택 월의 공간분포" : "선택 기간의 변화율 지도"}</h2><p>{mapMode === "month" ? "기준기간 평균에서 얼마나 높거나 낮은지를 보여줍니다." : "각 격자에서 월자료에 선형 추세를 맞춰 변화 속도를 계산합니다."}</p></div><label className={styles.compareToggle}><Columns2 size={15} /> 나란히 비교 <input type="checkbox" checked={mapComparison} onChange={(event) => setMapComparison(event.target.checked)} /></label></div>
      <div className={styles.mapTools}><Segmented value={mapMode} onChange={setMapMode} options={[{ value: "month", label: "선택 월" }, { value: "trend", label: "선택 기간 변화율" }]} />{mapMode === "month" && <label>확인할 월 <input type="month" value={mapDate} onChange={(event) => setMapDate(event.target.value)} /></label>}
        {mode === "individual" && <><label>왼쪽 지도<select value={effectiveMapA} onChange={(event) => setIndividualMapA(event.target.value)} disabled={!selected.length}>{selected.map((key) => <option key={key} value={key}>{componentByKey[key].label}</option>)}</select></label>{mapComparison && <label>오른쪽 지도<select value={effectiveMapB} onChange={(event) => setIndividualMapB(event.target.value)} disabled={!selected.length}>{selected.map((key) => <option key={key} value={key}>{componentByKey[key].label}</option>)}</select></label>}</>}
        {mapComparison && <label className={styles.sharedScale}><input type="checkbox" checked={sharedScale} onChange={(event) => setSharedScale(event.target.checked)} /> 같은 색 범위</label>}
      </div>
      {trendWarning && <div className={styles.trendWarning}><Info size={15} /> {trendWarning}</div>}
      <div className={mapComparison ? styles.mapPair : styles.mapSingle}>
        <CauseWorldMap title={mapLabel(targetA, "A")} subtitle={mapSubtitle} data={mapA} loading={mapLoading} error={mapErrorA} scaleMax={sharedScale ? commonMax : ownMaxA} sharedScale={sharedScale && mapComparison} />
        {mapComparison && <CauseWorldMap title={mapLabel(targetB, "B")} subtitle={mapSubtitle} data={mapB} loading={mapLoading} error={mapErrorB} scaleMax={sharedScale ? commonMax : ownMaxB} sharedScale={sharedScale} />}
      </div>
    </section>
    <section className={styles.summaryTable}>
      <div className={styles.cardHead}><div><span>결과 요약</span><h2>{mode === "individual" ? "선택 성분의 전 지구 평균 변화율" : "두 선택 성분 합계의 변화율"}</h2></div></div>
      <div className={styles.tableRows}>{items.map((item) => <div key={item.id}><span>{item.label}</span><strong>{item.data.trend_mm_per_year >= 0 ? "+" : ""}{item.data.trend_mm_per_year.toFixed(3)} mm/년</strong><small>{mode === "groups" ? "선택 성분 공통기간 합계" : qualityLabel[componentByKey[item.id].quality]}</small></div>)}{!seriesLoading && !seriesError && !items.length && <div><span>성분을 선택하면 결과가 표시됩니다.</span></div>}</div>
    </section>
  </>;
}

export default function CausesExperience() {
  const [view, setView] = useState<MainView>("overview");
  return <div className={styles.experience}>
    <div className={styles.flow} aria-label="탐구 단계">{["입력", "분석", "결과", "해석"].map((label, index) => <div className={index < 2 ? styles.on : ""} key={label}><span>{index + 1}</span>{label}</div>)}</div>
    <section className={styles.equation}><div><Activity size={17} /><span>관측된 해수면 변화<small>Observed</small></span></div><b>≈</b><div className={styles.steric}><Waves size={17} /><span>밀도 변화<small>Steric</small></span></div><b>+</b><div className={styles.mass}><Database size={17} /><span>질량 변화<small>GRACE · Barystatic</small></span></div></section>
    <nav className={styles.mainTabs} aria-label="원인 탐구 화면"><button type="button" className={view === "overview" ? styles.active : ""} onClick={() => setView("overview")}><MapIcon size={17} /><span><b>큰 그림</b><small>관측·Steric·GRACE 비교</small></span></button><button type="button" className={view === "barystatic" ? styles.active : ""} onClick={() => setView("barystatic")}><LineChart size={17} /><span><b>질량 성분 자세히</b><small>7개 성분과 두 그룹 비교</small></span></button></nav>
    {view === "overview" ? <Overview /> : <BarystaticDetail />}
    <section className={styles.helpCard}><CircleHelp size={22} /><div><span>해석 도움말</span><h3>{view === "overview" ? "두 원인 성분의 합이 관측값과 정확히 같지 않은 이유는 무엇일까요?" : "GRACE와 선택 성분 합계가 다른 것은 오류일까요?"}</h3><p>{view === "overview" ? "자료의 관측 방식과 공간 범위, 처리 방법이 다르므로 지역별 차이와 잔차가 나타날 수 있습니다." : "개별 성분 자료가 모든 질량 이동을 포함하지는 않습니다. 결과는 항상 ‘선택 성분 합계’로 해석합니다."}</p></div></section>
  </div>;
}
