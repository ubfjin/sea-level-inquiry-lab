"use client";

import { useMemo, useState } from "react";
import { ImageOverlay, MapContainer, TileLayer, useMapEvents } from "react-leaflet";
import type { LatLngBoundsExpression } from "leaflet";
import "leaflet/dist/leaflet.css";

import type { BarystaticMap, BarystaticTrendMap } from "../lib/barystatic-api";
import styles from "./CausesExperience.module.css";

type GridData = BarystaticMap | BarystaticTrendMap;
type Probe = { lat: number; lon: number; value: number | null };

const bounds: LatLngBoundsExpression = [[-85, -180], [85, 180]];
const palette = [
  [45, 75, 145],
  [137, 191, 211],
  [247, 247, 242],
  [231, 132, 104],
  [184, 60, 72],
];

const normalizeLongitude = (lon: number) => ((lon + 180) % 360 + 360) % 360 - 180;

function nearestIndex(values: number[], target: number, longitude = false) {
  let best = 0;
  let distance = Number.POSITIVE_INFINITY;
  values.forEach((value, index) => {
    const raw = Math.abs((longitude ? normalizeLongitude(value) : value) - target);
    const next = longitude ? Math.min(raw, 360 - raw) : raw;
    if (next < distance) {
      best = index;
      distance = next;
    }
  });
  return best;
}

function colorFor(value: number, maximum: number) {
  const ratio = Math.max(-1, Math.min(1, value / maximum));
  const position = (ratio + 1) * 2;
  const lower = Math.min(3, Math.floor(position));
  const mix = position - lower;
  return palette[lower].map((channel, index) =>
    Math.round(channel + (palette[lower + 1][index] - channel) * mix),
  );
}
function rasterUrl(data: GridData, maximum: number) {
  if (typeof document === "undefined" || !data.values.length) return "";
  const width = 720;
  const height = 400;
  const canvas = document.createElement("canvas");
  canvas.width = width;
  canvas.height = height;
  const context = canvas.getContext("2d");
  if (!context) return "";

  const image = context.createImageData(width, height);
  const maxMercator = Math.log(Math.tan(Math.PI / 4 + (85 * Math.PI / 180) / 2));
  const lonIndices = Array.from({ length: width }, (_, x) => {
    const lon = -180 + ((x + 0.5) / width) * 360;
    return nearestIndex(data.longitudes, lon, true);
  });
  const latIndices = Array.from({ length: height }, (_, y) => {
    const mercator = maxMercator - ((y + 0.5) / height) * maxMercator * 2;
    const lat = Math.atan(Math.sinh(mercator)) * 180 / Math.PI;
    return nearestIndex(data.latitudes, lat);
  });

  for (let y = 0; y < height; y += 1) {
    const row = data.values[latIndices[y]];
    for (let x = 0; x < width; x += 1) {
      const value = row?.[lonIndices[x]];
      const offset = (y * width + x) * 4;
      if (value == null || !Number.isFinite(value)) {
        image.data[offset + 3] = 0;
        continue;
      }
      const [red, green, blue] = colorFor(value, maximum);
      image.data[offset] = red;
      image.data[offset + 1] = green;
      image.data[offset + 2] = blue;
      image.data[offset + 3] = 210;
    }
  }
  context.putImageData(image, 0, 0);
  return canvas.toDataURL("image/png");
}

function GridProbe({
  data,
  onProbe,
}: {
  data: GridData;
  onProbe: (probe: Probe) => void;
}) {
  useMapEvents({
    mousemove(event) {
      const latIndex = nearestIndex(data.latitudes, event.latlng.lat);
      const lonIndex = nearestIndex(data.longitudes, event.latlng.lng, true);
      onProbe({
        lat: data.latitudes[latIndex],
        lon: normalizeLongitude(data.longitudes[lonIndex]),
        value: data.values[latIndex]?.[lonIndex] ?? null,
      });
    },
    click(event) {
      const latIndex = nearestIndex(data.latitudes, event.latlng.lat);
      const lonIndex = nearestIndex(data.longitudes, event.latlng.lng, true);
      onProbe({
        lat: data.latitudes[latIndex],
        lon: normalizeLongitude(data.longitudes[lonIndex]),
        value: data.values[latIndex]?.[lonIndex] ?? null,
      });
    },
  });
  return null;
}

export default function CauseWorldMap({
  title,
  subtitle,
  data,
  loading = false,
  error,
  scaleMax,
  sharedScale,
}: {
  title: string;
  subtitle: string;
  data: GridData | null;
  loading?: boolean;
  error?: string | null;
  scaleMax: number;
  sharedScale: boolean;
}) {
  const [probe, setProbe] = useState<Probe | null>(null);
  const imageUrl = useMemo(
    () => data ? rasterUrl(data, Math.max(scaleMax, 0.001)) : "",
    [data, scaleMax],
  );

  return (
    <div className={styles.mapFrame}>
      <MapContainer
        center={[12, 10]}
        zoom={2}
        minZoom={1}
        maxZoom={6}
        scrollWheelZoom
        worldCopyJump
        className={styles.mapCanvas}
      >
        <TileLayer
          attribution='&copy; OpenStreetMap contributors'
          url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
        />
        {data && imageUrl && <ImageOverlay url={imageUrl} bounds={bounds} opacity={0.84} />}
        {data && <GridProbe data={data} onProbe={setProbe} />}
      </MapContainer>
      <div className={styles.mapLabel}>
        <strong>{title}</strong>
        <span>{subtitle}</span>
      </div>
      {(loading || error || !data) && (
        <div className={styles.mapState} role="status">
          <strong>{loading ? "지도를 계산하고 있습니다" : error ? "지도를 불러오지 못했습니다" : "표시할 지도를 선택해 주세요"}</strong>
          <span>{error ?? (loading ? "같은 조건은 다음부터 더 빠르게 열립니다." : "성분 또는 그룹을 하나 이상 선택하세요.")}</span>
        </div>
      )}
      {data && probe && (
        <div className={styles.mapProbe}>
          <span>위도 {probe.lat.toFixed(1)}° · 경도 {probe.lon.toFixed(1)}°</span>
          <strong>{probe.value == null ? "자료 없음" : `${probe.value.toFixed(2)} ${data.unit}`}</strong>
        </div>
      )}
      <div className={styles.mapLegend} aria-label="지도 색상 범례">
        <div><span>{-scaleMax.toFixed(1)}</span><i /><span>+{scaleMax.toFixed(1)} {data?.unit ?? ""}</span></div>
        <small>{sharedScale ? "두 지도에 같은 색 범위 적용" : "이 지도의 값 범위에 맞춤"}</small>
      </div>
    </div>
  );
}
