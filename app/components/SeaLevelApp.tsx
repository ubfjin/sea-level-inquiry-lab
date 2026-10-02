"use client";

import dynamic from "next/dynamic";
import { useEffect, useMemo, useRef, useState } from "react";
import { Activity, ArrowRight, CalendarDays, Check, ChevronRight, CircleHelp, Database, Gauge, Globe2, Info, LockKeyhole, Map, MapPin, Menu, MousePointer2, Search, Settings2, UploadCloud, Waves, X } from "lucide-react";
import { demoGrid, endDate, startDate, type ViewKey, viewMeta } from "../lib/science";
import { API_URL, apiGet, flattenGrid, type MapResponse, type ProjectionResponse, type SeriesResponse, type TrendResponse } from "../lib/api";
import CausesExperience from "./CausesExperience";

const OceanMap = dynamic(() => import("./OceanMap"), { ssr: false });
const PlotChart = dynamic(() => import("./PlotChart"), { ssr: false });

const items: { key: ViewKey; label: string; icon: typeof Waves }[] = [
  { key: "home", label: "홈", icon: Waves }, { key: "date", label: "해수면 변화 탐색", icon: CalendarDays },
  { key: "trend", label: "변화율 지도", icon: Gauge }, { key: "causes", label: "변화의 원인", icon: Activity },
  { key: "projection", label: "2100년 단순 추정", icon: Globe2 },
];

function Flow({ active = 1 }: { active?: number }) { return <div className="flow" aria-label="탐구 단계">{["입력", "분석", "결과", "해석"].map((x, i) => <div className={i <= active ? "on" : ""} key={x}><span>{i + 1}</span>{x}{i < 3 && <ChevronRight />}</div>)}</div>; }

function Field({ label, type = "date", value, onChange, min, max, step }: { label: string; type?: string; value: string | number; onChange: (v: string) => void; min?: string | number; max?: string | number; step?: string | number }) { return <label className="field"><span>{label}</span><input type={type} value={value} min={min} max={max} step={step} onChange={(e) => onChange(e.target.value)} /></label>; }

function ResultStat({ label, value, tone = "blue" }: { label: string; value: string; tone?: string }) { return <div className={`result-stat ${tone}`}><span>{label}</span><strong>{value}</strong></div>; }

function Panel({ children, title = "탐구 설정", hint }: { children: React.ReactNode; title?: string; hint?: string }) { return <aside className="control-panel"><div className="panel-title"><div><span className="step-kicker">탐구 설정</span><h2>{title}</h2></div><Settings2 size={18} /></div>{hint && <p className="panel-hint">{hint}</p>}{children}</aside>; }

function Interpretation({ children, question }: { children: React.ReactNode; question: string }) { return <section className="interpret"><div className="interpret-icon"><CircleHelp /></div><div><span>해석 도움말</span><h3>{question}</h3><p>{children}</p></div></section>; }

function MapResult({ kind, selected, onPick, title, note, points, dataLabel = "시연 모드", worldView = false }: { kind: "height" | "trend" | "projection" | "change"; selected?: { lat: number; lon: number }; onPick?: (lat: number, lon: number) => void; title: string; note?: string; points?: ReturnType<typeof demoGrid>; dataLabel?: string; worldView?: boolean }) { const fallback = useMemo(() => demoGrid(kind), [kind]); return <div className="visual-card"><div className="visual-head"><div><span className="step-kicker">지도 결과</span><h2>{title.replaceAll("SLA", "해수면 고도 편차")}</h2>{note && <p>{note}</p>}</div><span className="data-badge"><Database size={14} /> {dataLabel.replaceAll("SLA", "해수면 고도 편차")}</span></div><OceanMap points={points ?? fallback} kind={kind === "projection" ? "height" : kind} selected={selected} onPick={onPick} worldView={worldView} /></div>; }

function Home({ go }: { go: (v: ViewKey) => void }) {
  return <><section className="home-hero"><div className="home-hero-title"><span className="eyebrow">위성 관측 자료로 해수면 변화 탐구하기</span><h1>바다의 높이는 <em>어떻게 변해 왔을까?</em></h1><p>한반도 주변과 전 지구의 해수면 자료를 직접 고르고, 지도와 그래프에서 변화의 증거를 찾아보세요.</p></div><div className="home-hero-content"><div className="hero-map"><MapResult kind="height" title="2024년 12월 해수면 고도 편차" note="색이 붉을수록 평소보다 높고, 푸를수록 낮습니다." /><div className="map-callout"><MousePointer2 size={17} /><span>바다 격자를 클릭해 그곳의 시간 변화를 살펴보세요</span></div></div></div></section><section className="home-path"><div><span className="eyebrow">오늘의 탐구 경로</span><h2>관찰에서 설명까지, 세 단계로 생각해요</h2></div><div className="path-cards">{[["01", "언제·어디에서 달라졌을까요?", "날짜 지도와 위치 시계열을 함께 봅니다.", "date"], ["02", "어디가 더 빠를까요?", "공간별 변화율을 찾습니다.", "trend"], ["03", "왜 변했을까요?", "밀도와 질량 변화를 구분합니다.", "causes"]].map(([n, t, d, k]) => <button key={n} onClick={() => go(k as ViewKey)}><span>{n}</span><h3>{t}</h3><p>{d}</p><ArrowRight /></button>)}</div></section></>;
}

const normalizedLongitude = (value: number) => ((value + 180) % 360 + 360) % 360 - 180;
const latitudeLabel = (value: number) => `${Math.abs(value).toFixed(2)}°${value < 0 ? "S" : "N"}`;
const longitudeLabel = (value: number) => { const normalized = normalizedLongitude(value); return `${Math.abs(normalized).toFixed(2)}°${normalized < 0 ? "W" : "E"}`; };
const locationLabel = (lat: number, lon: number) => `${latitudeLabel(lat)}, ${longitudeLabel(lon)}`;

function mergeObservedGrids(regional?: MapResponse | TrendResponse, global?: MapResponse | TrendResponse) {
  const regionalPoints = regional ? flattenGrid(regional.latitudes, regional.longitudes, regional.values) : [];
  const globalPoints = global ? flattenGrid(global.latitudes, global.longitudes, global.values) : [];
  if (!regional || !regional.latitudes.length || !regional.longitudes.length) return globalPoints;
  const minLat = Math.min(...regional.latitudes); const maxLat = Math.max(...regional.latitudes);
  const minLon = Math.min(...regional.longitudes); const maxLon = Math.max(...regional.longitudes);
  return [
    ...globalPoints.filter((point) => point.lat < minLat || point.lat > maxLat || point.lon < minLon || point.lon > maxLon),
    ...regionalPoints,
  ];
}

function DateView() {
  const [date, setDate] = useState("2023-04-01"); const [points, setPoints] = useState<ReturnType<typeof demoGrid>>(); const [usedDate, setUsedDate] = useState("2023-04-01"); const [mapLabel, setMapLabel] = useState("분석 전"); const [mapNote, setMapNote] = useState("한반도 주변 0.125° · 그 밖의 바다 1°"); const [mapError, setMapError] = useState("");
  const [lat, setLat] = useState(38); const [lon, setLon] = useState(132); const [from, setFrom] = useState(startDate); const [to, setTo] = useState(endDate); const [series, setSeries] = useState<SeriesResponse["series"]>([]); const [grid, setGrid] = useState({ lat: 38, lon: 132 }); const [trend, setTrend] = useState(0); const [seriesLabel, setSeriesLabel] = useState("분석 전"); const [resolution, setResolution] = useState<number | null>(null); const [periodNote, setPeriodNote] = useState(""); const [seriesError, setSeriesError] = useState("");

  const loadMap = async () => {
    setMapError("");
    const [regional, global] = await Promise.allSettled([
      apiGet<MapResponse>(`/api/map?date=${date}`),
      apiGet<MapResponse>(`/api/global-map?date=${date}`),
    ]);
    if (regional.status === "rejected" && global.status === "rejected") {
      setPoints(undefined); setMapLabel("자료 없음"); setMapError(regional.reason instanceof Error ? regional.reason.message : "지도 자료를 불러오지 못했습니다."); return;
    }
    const regionalData = regional.status === "fulfilled" ? regional.value : undefined;
    const globalData = global.status === "fulfilled" ? global.value : undefined;
    setPoints(mergeObservedGrids(regionalData, globalData));
    setUsedDate(regionalData?.data_date ?? globalData?.data_date ?? date);
    setMapLabel(regionalData && globalData ? "실제 관측 · 0.125°/1°" : regionalData ? "한반도 주변 0.125°" : "전 지구 1°");
    setMapNote(globalData ? "한반도 주변은 0.125°, 그 밖의 바다는 1° 실제 격자입니다." : "선택 월은 전 지구 1° 자료 기간 밖이어서 한반도 주변 0.125°만 표시합니다.");
    if (regional.status === "rejected") setMapError("한반도 고해상도 자료를 불러오지 못해 전 지구 1° 자료만 표시합니다.");
  };

  const analyzeSeries = async () => {
    setSeriesError(""); setPeriodNote("");
    try {
      const result = await apiGet<SeriesResponse>(`/api/point-series?start=${from}&end=${to}&lat=${lat}&lon=${lon}`);
      setSeries(result.series); setGrid(result.grid_location ?? { lat, lon }); setTrend(result.trend_mm_per_year); setSeriesLabel((result.data_source_label ?? "활성 NetCDF").replaceAll("SLA", "해수면 고도 편차")); setResolution(result.grid_resolution_degrees ?? null); setPeriodNote(result.period_note ?? "");
      if (result.period_adjusted && result.data_period) { setFrom(`${result.data_period.start}-01`); setTo(`${result.data_period.end}-01`); }
    } catch (error) {
      setSeries([]); setResolution(null); setPeriodNote(""); setSeriesError(error instanceof Error ? error.message : "자료를 불러오지 못했습니다."); setSeriesLabel("자료 없음");
    }
  };

  return <><div className="analysis-layout"><Panel title="날짜와 위치 선택" hint="날짜 지도를 확인한 뒤 지도에서 위치를 골라 시계열을 분석합니다."><Field label="지도에서 확인할 날짜" value={date} onChange={setDate} min={startDate} max={endDate} /><button className="primary-btn full" onClick={loadMap}><Search size={17} /> 날짜 지도 불러오기</button>{mapError && <p className="inline-error">{mapError}</p>}<div className="coord-label"><span>시계열 위치</span><small><MapPin size={13} /> 오른쪽 지도 클릭 가능</small></div><div className="field-grid"><Field label="위도 (°)" type="number" value={lat} onChange={(value) => setLat(Number(value))} min={-90} max={90} step="0.1" /><Field label="경도 (°E/°W)" type="number" value={lon} onChange={(value) => setLon(Number(value))} min={-180} max={180} step="0.1" /></div><div className="field-grid"><Field label="시계열 시작" value={from} onChange={setFrom} min={startDate} max={to} /><Field label="시계열 종료" value={to} onChange={setTo} min={from} max={endDate} /></div><button className="primary-btn full" onClick={analyzeSeries}><Activity size={17} /> 선택 위치 시계열 보기</button>{seriesError && <p className="inline-error">{seriesError}</p>}</Panel><MapResult kind="height" title={`${usedDate.slice(0, 7).replace("-", "년 ")}월 SLA 지도`} note={mapNote} points={points} dataLabel={mapLabel} selected={{ lat, lon }} onPick={(pickedLat, pickedLon) => { setLat(pickedLat); setLon(pickedLon); }} worldView /></div><div className="result-row"><ResultStat label="선택한 날짜" value={date.replaceAll("-", ".")} /><ResultStat label="실제 자료 날짜" value={usedDate.replaceAll("-", ".")} /><ResultStat label="지도 해상도" value="0.125° / 1° 자동" tone="cyan" /></div><div className="visual-card chart-card integrated-chart"><div className="visual-head"><div><span className="step-kicker">선택 위치 결과</span><h2>{`선택한 위치 ${locationLabel(lat, lon)} (가장 가까운 해양 격자 ${locationLabel(grid.lat, grid.lon)})`}</h2><p>{from.slice(0, 7)} — {to.slice(0, 7)}{periodNote ? ` · ${periodNote}` : " · 원자료, 12개월 이동평균, 선형 추세"}</p></div><span className="data-badge"><Database size={14} /> {seriesLabel}{resolution == null ? "" : ` · ${resolution}°`}</span></div>{seriesError ? <div className="chart-error-state"><Info /><b>실제 자료를 불러오지 못했습니다.</b><span>{seriesError}</span></div> : series.length ? <PlotChart data={series} trendMmPerYear={trend} /> : <div className="chart-error-state"><MapPin /><b>지도에서 바다 위치를 고른 뒤 시계열 보기를 눌러 주세요.</b><span>한반도 주변은 0.125°, 그 밖의 바다는 1° 자료를 사용합니다.</span></div>}</div><Interpretation question="공간 분포와 한 위치의 장기 변화는 어떻게 연결될까요?">지도는 선택한 한 달의 공간 차이를, 시계열은 같은 위치가 시간에 따라 어떻게 달라졌는지를 보여줍니다. 격자는 보간하지 않았으며 굵은 선만 12개월 이동평균입니다.</Interpretation></>;
}

function TrendView() {
  const [from, setFrom] = useState(startDate); const [to, setTo] = useState(endDate); const [picked, setPicked] = useState({ lat: 37, lon: 129 }); const [points, setPoints] = useState<ReturnType<typeof demoGrid>>(); const [mean, setMean] = useState(3.42); const [label, setLabel] = useState("분석 전"); const [periodNote, setPeriodNote] = useState(""); const [error, setError] = useState("");
  const analyze = async () => { setError(""); setPeriodNote(""); const [regional, global] = await Promise.allSettled([apiGet<TrendResponse>(`/api/trend-map?start=${from}&end=${to}`), apiGet<TrendResponse>(`/api/global-trend-map?start=${from}&end=${to}`)]); if (regional.status === "rejected" && global.status === "rejected") { setPoints(undefined); setLabel("자료 없음"); setError(regional.reason instanceof Error ? regional.reason.message : "변화율 자료를 불러오지 못했습니다."); return; } const regionalData = regional.status === "fulfilled" ? regional.value : undefined; const globalData = global.status === "fulfilled" ? global.value : undefined; setPoints(mergeObservedGrids(regionalData, globalData)); setMean(globalData?.area_mean ?? regionalData?.area_mean ?? 0); setLabel(regionalData && globalData ? "실제 관측 · 0.125°/1°" : regionalData ? "한반도 주변 0.125°" : "전 지구 1°"); setPeriodNote(globalData?.period_note ?? ""); if (regional.status === "rejected") setError("한반도 고해상도 자료를 불러오지 못해 전 지구 1° 자료만 표시합니다."); };
  const nearest = (points ?? demoGrid("trend")).reduce((best, p) => Math.hypot(p.lat - picked.lat, p.lon - picked.lon) < Math.hypot(best.lat - picked.lat, best.lon - picked.lon) ? p : best);
  return <><div className="analysis-layout"><Panel title="기간 선택" hint="선택 기간 동안 각 격자에서 직선의 기울기를 계산합니다."><Field label="시작 날짜" value={from} onChange={setFrom} /><Field label="종료 날짜" value={to} onChange={setTo} /><div className="formula-box"><span>격자별 계산</span><b>SLA = 기울기 × 시간 + 시작값</b><small>기울기 × 1000 → mm/년</small></div><button className="primary-btn full" onClick={analyze}><Gauge size={17} /> 전 지구 변화율 계산</button>{error && <p className="inline-error">{error}</p>}</Panel><MapResult kind="trend" title="공간별 해수면 변화율" note={periodNote || "한반도 주변은 0.125°, 그 밖의 바다는 1° 실제 격자입니다."} selected={picked} onPick={(lat, lon) => setPicked({ lat, lon })} points={points} dataLabel={label} worldView /></div><div className="result-row"><ResultStat label="전 지구 1° 평균" value={`${mean >= 0 ? "+" : ""}${mean.toFixed(2)} mm/년`} /><ResultStat label="선택 격자" value={locationLabel(nearest.lat, nearest.lon)} /><ResultStat label="선택 위치 변화율" value={`${nearest.value >= 0 ? "+" : ""}${nearest.value.toFixed(2)} mm/년`} tone="coral" /></div><Interpretation question="이 지도는 ‘높은 곳’이 아니라 ‘빨리 변한 곳’을 보여줍니다.">0보다 큰 값은 해마다 높아지는 경향, 0보다 작은 값은 낮아지는 경향입니다. 지도는 실제 0.125°/1° 격자를 보간 없이 표시합니다.</Interpretation></>;
}

function CausesView() {
  return <CausesExperience />;
}

function ProjectionView() {
  const [tab, setTab] = useState<"projection" | "change">("projection"); const [from, setFrom] = useState(startDate); const [to, setTo] = useState(endDate); const [base, setBase] = useState(2024); const [projection, setProjection] = useState<ProjectionResponse>(); const [label, setLabel] = useState("시연 모드"); const [error, setError] = useState("");
  const analyze = async () => { setError(""); try { const r = await apiGet<ProjectionResponse>(`/api/projection?start=${from}&end=${to}&base_year=${base}&target_year=2100`); setProjection(r); setLabel("활성 NetCDF"); } catch (e) { setError(e instanceof Error ? e.message : "자료를 불러오지 못했습니다."); } };
  const points = projection ? flattenGrid(projection.latitudes, projection.longitudes, tab === "projection" ? projection.estimate_values : projection.change_mm_values) : undefined; const changePoints = projection ? flattenGrid(projection.latitudes, projection.longitudes, projection.change_mm_values) : undefined; const meanChange = changePoints ? changePoints.reduce((s, p) => s + p.value, 0) / changePoints.length : 260;
  return <><div className="warning"><Info /><div><b>단순 계산이며 기후 예측이 아닙니다.</b><p>이 결과는 실제 2100년 해수면을 정확히 예측한 것이 아닙니다. 과거의 선형 변화가 같은 속도로 계속된다고 가정한 단순 계산입니다.</p></div></div><div className="analysis-layout"><Panel hint="과거 자료의 기간과 비교 기준연도를 정합니다."><Field label="추세 시작" value={from} onChange={setFrom} /><Field label="추세 종료" value={to} onChange={setTo} /><Field label="비교 기준연도" type="number" value={base} onChange={(v) => setBase(Number(v))} /><div className="formula-box"><span>단순 외삽</span><b>2100년 값 = 기울기 × 2100 + 절편</b><small>미래의 가속·감속은 포함하지 않음</small></div><button className="primary-btn full" onClick={analyze}><Activity size={17} /> 2100년 값 계산</button>{error && <p className="inline-error">{error}</p>}</Panel><div><div className="tabs"><button className={tab === "projection" ? "active" : ""} onClick={() => setTab("projection")}>2100년 SLA</button><button className={tab === "change" ? "active" : ""} onClick={() => setTab("change")}>기준연도 대비 변화량</button></div><MapResult kind={tab} title={tab === "projection" ? "2100년 SLA 단순 추정" : `${base}년 대비 2100년 변화량`} note={`${from.slice(0,4)}–${to.slice(0,4)}년 선형 추세를 그대로 연장한 계산`} points={points} dataLabel={label} /></div></div><div className="result-row"><ResultStat label="기준연도" value={`${base}년`} /><ResultStat label="목표연도" value="2100년" /><ResultStat label="영역 평균 변화량" value={`+${(meanChange ?? 260).toFixed(0)} mm`} tone="coral" /></div><Interpretation question="왜 이 결과를 ‘예측’이라고 부르면 안 될까요?">실제 미래에는 온실가스 배출, 빙상 반응, 해류와 지반 변화 등으로 상승 속도가 달라집니다. 이 화면은 선형 추세라는 가정을 시험하는 활동입니다.</Interpretation></>;
}

function AdminView() {
  const [logged, setLogged] = useState(false); const [file, setFile] = useState<File | null>(null); const [checking, setChecking] = useState(false); const [checked, setChecked] = useState(false); const [candidate, setCandidate] = useState(""); const [validation, setValidation] = useState<Record<string, unknown> | null>(null); const [error, setError] = useState(""); const pw = useRef<HTMLInputElement>(null);
  if (!logged) return <div className="login-card"><div className="login-mark"><LockKeyhole /></div><span className="eyebrow">교사용 데이터 관리</span><h2>관리자 로그인</h2><p>수업에 사용할 NetCDF 자료를 검사하고 활성화합니다.</p><label className="field"><span>관리자 비밀번호</span><input ref={pw} type="password" placeholder="비밀번호 입력" onKeyDown={(e) => e.key === "Enter" && setLogged(true)} /></label><button className="primary-btn full" onClick={() => setLogged(true)}>로그인</button><small>로컬 개발 환경에서는 임의의 비밀번호로 화면을 확인할 수 있습니다.</small></div>;
  const validate = async () => { if (!file) return; setChecking(true); setError(""); try { const form = new FormData(); form.append("file", file); const response = await fetch(`${API_URL}/api/admin/validate`, { method: "POST", headers: { Authorization: `Bearer ${pw.current?.value || "oceanlab"}` }, body: form }); const data = await response.json() as { detail?: string; candidate: string; validation: Record<string, unknown> }; if (!response.ok) throw new Error(data.detail); setCandidate(data.candidate); setValidation(data.validation); setChecked(true); } catch (e) { setError(e instanceof Error ? e.message : "파일 검사에 실패했습니다."); setChecked(false); } finally { setChecking(false); } };
  const activate = async () => { try { const response = await fetch(`${API_URL}/api/admin/activate/${candidate}`, { method: "POST", headers: { Authorization: `Bearer ${pw.current?.value || "oceanlab"}` } }); const data = await response.json() as { detail?: string }; if (!response.ok) throw new Error(data.detail); alert("활성 자료로 적용되었습니다."); } catch (e) { setError(e instanceof Error ? e.message : "적용하지 못했습니다."); } };
  const row = (key: string, fallback: string) => validation?.[key] == null ? fallback : String(validation[key]);
  return <><Flow active={checked ? 3 : file ? 1 : 0} /><div className="admin-grid"><section className="upload-card"><div className="panel-title"><div><span className="step-kicker">STEP 1 · 업로드</span><h2>NetCDF 자료 선택</h2></div><UploadCloud /></div><label className="dropzone"><input type="file" accept=".nc,.nc4,.netcdf" onChange={(e) => { setFile(e.target.files?.[0] ?? null); setChecked(false); }} /><UploadCloud /><b>{file ? file.name : "파일을 놓거나 눌러서 선택"}</b><span>NetCDF (.nc, .nc4) · 최대 2 GB</span></label><button className="primary-btn full" disabled={!file || checking} onClick={validate}>{checking ? "좌표와 변수를 검사하는 중…" : "파일 검사 시작"}</button>{error && <p className="inline-error">{error}</p>}</section><section className="validation-card"><div className="panel-title"><div><span className="step-kicker">STEP 2 · 검사 결과</span><h2>{checked ? "수업에 사용할 수 있는 자료예요" : "검사 대기 중"}</h2></div>{checked && <Check className="check" />}</div>{checked ? <div className="validation-list">{[["파일명", row("filename", file?.name ?? "-")], ["데이터 기간", `${row("time_start", "-")} — ${row("time_end", "-")}`], ["위도 범위", `${row("lat_min", "-")}° — ${row("lat_max", "-")}°`], ["경도 범위", `${row("lon_min", "-")}° — ${row("lon_max", "-")}°`], ["시간 간격", row("interval", "-")], ["변수 목록", Array.isArray(validation?.variables) ? validation.variables.join(", ") : "-"], ["SLA 존재 여부", validation?.has_sla ? "있음" : "없음"], ["SLA 단위", row("sla_unit", "-")]].map(([a,b]) => <div key={a}><span>{a}</span><b>{b}</b><Check /></div>)}</div> : <div className="empty-check"><Database /><p>파일을 선택하고 검사를 시작하면<br />기간, 좌표, 변수, 단위를 확인합니다.</p></div>}{checked && <button className="apply-btn" onClick={activate}><Check /> 이 자료를 활성 데이터로 적용</button>}</section></div><Interpretation question="활성 자료를 바꾸기 전에 무엇을 확인해야 할까요?">SLA 변수가 있고 단위가 m인지, 시간 간격이 월 단위인지, 수업에서 다룰 한반도 주변 범위를 포함하는지 확인하세요.</Interpretation></>;
}

export default function SeaLevelApp() {
  const [view, setView] = useState<ViewKey>("home"); const [mobile, setMobile] = useState(false); const [activeData, setActiveData] = useState(false); const meta = viewMeta[view]; const go = (v: ViewKey) => { setView(v); setMobile(false); window.scrollTo({ top: 0, behavior: "smooth" }); };
  useEffect(() => { void fetch(`${API_URL}/health`).then(async (r) => { if (!r.ok) throw new Error("offline"); return await r.json() as { active_dataset?: boolean }; }).then((d) => setActiveData(Boolean(d.active_dataset))).catch(() => setActiveData(false)); }, []);
  return <div className="app-shell"><header className="topbar"><button className="brand" onClick={() => go("home")}><span><Waves /></span><div><b>해수면 탐구 실험</b><small>SEA LEVEL INQUIRY LAB</small></div></button><div className={`dataset-status ${activeData ? "" : "demo"}`}><span /><div><small>현재 자료</small><b>{activeData ? "Copernicus 월평균 SLA · 실제 관측 자료" : "자료 서버 연결 안 됨"}</b></div></div><button className="mobile-toggle" aria-label={mobile ? "탐구 메뉴 닫기" : "탐구 메뉴 열기"} onClick={() => setMobile(!mobile)}>{mobile ? <X /> : <Menu />}</button></header><div className="body-grid"><nav className={mobile ? "side-nav open" : "side-nav"}><div className="nav-caption">탐구 메뉴</div>{items.map((it) => <button key={it.key} className={view === it.key ? "active" : ""} onClick={() => go(it.key)}><it.icon /><span>{it.label}</span>{view === it.key && <ChevronRight className="chev" />}</button>)}<div className="nav-source"><Database /><div><span>데이터 원칙</span><p>시연 자료와 실제 관측 자료를 구분해 표시합니다.</p></div></div></nav><main className="main-content"><header className="page-head"><div><span className="eyebrow">{meta.eyebrow}</span>{view !== "home" && <><h1>{meta.title}</h1><p>{meta.desc}</p></>}</div>{view !== "home" && <span className="scope-chip"><Map size={15} /> {view === "date" || view === "trend" ? "전 지구 · 0.125°/1° 자동 선택" : "115–135°E · 25–45°N"}</span>}</header>{view === "home" && <Home go={go} />}{view === "date" && <DateView />}{view === "trend" && <TrendView />}{view === "causes" && <CausesView />}{view === "projection" && <ProjectionView />}{view === "admin" && <AdminView />}</main></div></div>;
}
