"use client";
import { MapContainer, TileLayer, Rectangle, CircleMarker, Tooltip, useMapEvents } from "react-leaflet";
import type { GridPoint } from "../lib/science";
import "leaflet/dist/leaflet.css";

const palette = ["#263f8c", "#467bb7", "#82bad2", "#d5edf1", "#f7f7f2", "#f6c2a3", "#e77f63", "#b83c48"];
function color(v: number, kind: string) { const bounds = kind === "height" ? [-100, -60, -25, 0, 25, 60, 100] : kind === "trend" ? [-2, 0, 2, 3.5, 5, 7, 9] : [-300, -150, -50, 0, 100, 250, 450]; const value = kind === "height" ? v * 1000 : v; const idx = bounds.findIndex((b) => value < b); return palette[idx < 0 ? 7 : idx]; }
function Clicker({ onPick }: { onPick?: (lat: number, lon: number) => void }) { useMapEvents({ click: (e) => onPick?.(Number(e.latlng.lat.toFixed(2)), Number(e.latlng.lng.toFixed(2))) }); return null; }

export default function OceanMap({ points, kind = "height", selected, onPick }: { points: GridPoint[]; kind?: string; selected?: { lat: number; lon: number }; onPick?: (lat: number, lon: number) => void }) {
  return <div className="map-shell"><MapContainer center={[37, 128]} zoom={5} minZoom={4} maxZoom={8} scrollWheelZoom className="h-full w-full" zoomControl><TileLayer attribution='&copy; OpenStreetMap contributors' url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png" />{points.map((p) => <Rectangle key={`${p.lat}-${p.lon}`} bounds={[[p.lat - 1, p.lon - 1], [p.lat + 1, p.lon + 1]]} pathOptions={{ color: color(p.value, kind), fillColor: color(p.value, kind), fillOpacity: 0.72, weight: 0.25 }}><Tooltip sticky>{p.lat.toFixed(1)}°N · {p.lon.toFixed(1)}°E<br />{kind === "height" ? `${(p.value * 1000).toFixed(1)} mm` : `${p.value.toFixed(2)} ${kind === "trend" ? "mm/년" : "mm"}`}</Tooltip></Rectangle>)}{selected && <CircleMarker center={[selected.lat, selected.lon]} radius={8} pathOptions={{ color: "#fff", fillColor: "#062e4f", fillOpacity: 1, weight: 3 }}><Tooltip permanent direction="top">선택 위치</Tooltip></CircleMarker>}<Clicker onPick={onPick} /></MapContainer><div className="legend" aria-label="지도 색상 범례"><span>낮음</span><i /><span>높음</span><b>{kind === "height" ? "SLA (mm)" : kind === "trend" ? "변화율 (mm/년)" : "변화량 (mm)"}</b></div></div>;
}
