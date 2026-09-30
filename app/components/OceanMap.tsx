"use client";
import { MapContainer, TileLayer, Rectangle, CircleMarker, Pane, Tooltip, useMapEvents } from "react-leaflet";
import type { GridPoint } from "../lib/science";
import "leaflet/dist/leaflet.css";

const palette = ["#263f8c", "#467bb7", "#82bad2", "#d5edf1", "#f7f7f2", "#f6c2a3", "#e77f63", "#b83c48"];
const displayValue = (value: number, kind: string) => kind === "height" ? value * 1000 : value;
function scaleFor(points: GridPoint[], kind: string) {
  const globalPoints = points.filter((point) => (point.cellLatDegrees ?? 1) >= 0.9 && (point.cellLonDegrees ?? 1) >= 0.9);
  const source = globalPoints.length ? globalPoints : points;
  const values = source.map((point) => displayValue(point.value, kind)).filter(Number.isFinite).sort((a, b) => a - b);
  if (!values.length) return { min: -1, max: 1 };
  const percentile = (ratio: number) => values[Math.min(values.length - 1, Math.max(0, Math.floor((values.length - 1) * ratio)))];
  const limit = Math.max(Math.abs(percentile(0.02)), Math.abs(percentile(0.98)), kind === "trend" ? 0.5 : 1);
  return { min: -limit, max: limit };
}
function color(value: number, kind: string, min: number, max: number) {
  const ratio = Math.max(0, Math.min(1, (displayValue(value, kind) - min) / (max - min)));
  return palette[Math.min(palette.length - 1, Math.floor(ratio * palette.length))];
}
const formatLatitude = (value: number) => `${Math.abs(value).toFixed(2)}°${value < 0 ? "S" : "N"}`;
const formatLongitude = (value: number) => { const normalized = normalizeLongitude(value); return `${Math.abs(normalized).toFixed(2)}°${normalized < 0 ? "W" : "E"}`; };
const normalizeLongitude = (longitude: number) => ((longitude + 180) % 360 + 360) % 360 - 180;
function Clicker({ onPick }: { onPick?: (lat: number, lon: number) => void }) { useMapEvents({ click: (e) => onPick?.(Number(e.latlng.lat.toFixed(2)), Number(normalizeLongitude(e.latlng.lng).toFixed(2))) }); return null; }

export default function OceanMap({ points, kind = "height", selected, onPick, worldView = false }: { points: GridPoint[]; kind?: string; selected?: { lat: number; lon: number }; onPick?: (lat: number, lon: number) => void; worldView?: boolean }) {
  const scale = scaleFor(points, kind);
  const unit = kind === "height" ? "mm" : kind === "trend" ? "mm/년" : "mm";
  const digits = kind === "trend" ? 1 : 0;
  return <div className="map-shell"><MapContainer center={worldView ? [20, 0] : [37, 128]} zoom={worldView ? 2 : 5} minZoom={1} maxZoom={8} scrollWheelZoom worldCopyJump preferCanvas className="h-full w-full" zoomControl>
    <TileLayer attribution='&copy; OpenStreetMap contributors' url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png" />
    <Pane name="sea-level-grid" style={{ zIndex: 400 }}>
      {points.map((p) => {
        const halfLat = (p.cellLatDegrees ?? 1) / 2;
        const halfLon = (p.cellLonDegrees ?? 1) / 2;
        const fill = color(p.value, kind, scale.min, scale.max);
        return <Rectangle key={`${p.lat}-${p.lon}`} bounds={[[p.lat - halfLat, p.lon - halfLon], [p.lat + halfLat, p.lon + halfLon]]} pathOptions={{ color: fill, fillColor: fill, fillOpacity: 0.72, weight: 0.15 }}><Tooltip sticky>{formatLatitude(p.lat)} · {formatLongitude(p.lon)}<br />격자 {p.cellLatDegrees ?? 1}° × {p.cellLonDegrees ?? 1}°<br />{displayValue(p.value, kind).toFixed(kind === "trend" ? 2 : 1)} {unit}</Tooltip></Rectangle>;
      })}
    </Pane>
    {selected && <CircleMarker center={[selected.lat, normalizeLongitude(selected.lon)]} radius={8} pathOptions={{ color: "#fff", fillColor: "#062e4f", fillOpacity: 1, weight: 3 }}><Tooltip permanent direction="top">선택 위치</Tooltip></CircleMarker>}
    <Clicker onPick={onPick} />
  </MapContainer><div className="legend numeric-legend" aria-label="지도 색상 범례"><span>{scale.min.toFixed(digits)}</span><span>0</span><span>{scale.max.toFixed(digits)}</span><i /><b>{kind === "height" ? "해수면 고도 편차" : kind === "trend" ? "변화율" : "변화량"} ({unit})</b></div></div>;
}
