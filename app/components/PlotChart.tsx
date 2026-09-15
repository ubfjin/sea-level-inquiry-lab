"use client";
import PlotModule from "react-plotly.js";
import type { SeriesPoint } from "../lib/science";

const Plot = (typeof PlotModule === "function" ? PlotModule : (PlotModule as { default: typeof PlotModule }).default);

export default function PlotChart({ data, area = false }: { data: SeriesPoint[]; area?: boolean }) {
  const x = data.map((d) => d.date);
  return <Plot data={[
    { x, y: data.map((d) => d.monthly * 1000), type: "scatter", mode: "lines", name: area ? "영역 월평균" : "월평균 SLA", line: { color: "#82b7ca", width: 1.4 } },
    { x, y: data.map((d) => d.moving == null ? null : d.moving * 1000), type: "scatter", mode: "lines", name: "12개월 이동평균", line: { color: "#087ea4", width: 3 } },
    { x, y: data.map((d) => d.trend * 1000), type: "scatter", mode: "lines", name: "선형 추세", line: { color: "#f26b5b", width: 2.4, dash: "dash" } },
  ]} layout={{ autosize: true, height: 430, margin: { l: 58, r: 22, t: 24, b: 55 }, paper_bgcolor: "transparent", plot_bgcolor: "#f8fbfd", hovermode: "x unified", font: { family: "Arial, sans-serif", color: "#32485a", size: 13 }, legend: { orientation: "h", x: 0, y: 1.12 }, xaxis: { gridcolor: "#dfeaf0", title: { text: "관측 시기" } }, yaxis: { gridcolor: "#dfeaf0", zerolinecolor: "#9bb3c0", title: { text: "SLA (mm)" } } }} config={{ responsive: true, displaylogo: false, scrollZoom: true, modeBarButtonsToRemove: ["lasso2d", "select2d"] }} useResizeHandler className="h-full w-full" />;
}
