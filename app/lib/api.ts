import type { GridPoint, SeriesPoint } from "./science";

export const API_URL = (process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8000").replace(/\/$/, "");

export async function apiGet<T>(path: string): Promise<T> {
  const response = await fetch(`${API_URL}${path}`);
  if (!response.ok) {
    const body = await response.json().catch(() => ({})) as { detail?: string };
    throw new Error(body.detail ?? "자료를 불러오지 못했습니다.");
  }
  return response.json() as Promise<T>;
}

export function flattenGrid(latitudes: number[], longitudes: number[], values: (number | null)[][]): GridPoint[] {
  const points: GridPoint[] = [];
  const spacing = (coordinates: number[]) => {
    const differences = coordinates
      .slice(1)
      .map((value, index) => Math.abs(value - coordinates[index]))
      .filter((value) => Number.isFinite(value) && value > 0)
      .sort((a, b) => a - b);
    return differences.length ? differences[Math.floor(differences.length / 2)] : 1;
  };
  const cellLatDegrees = spacing(latitudes);
  const cellLonDegrees = spacing(longitudes);
  latitudes.forEach((lat, i) => longitudes.forEach((lon, j) => {
    const value = values[i]?.[j];
    if (value !== null && Number.isFinite(value)) {
      points.push({ lat, lon, value, cellLatDegrees, cellLonDegrees });
    }
  }));
  return points;
}

export type MapResponse = {
  requested_date: string;
  data_date: string;
  latitudes: number[];
  longitudes: number[];
  values: (number | null)[][];
  unit: string;
  data_source?: "regional_0.125deg" | "global_1deg";
  data_source_label?: string;
  grid_resolution_degrees?: number;
};
export type SeriesResponse = {
  trend_mm_per_year: number;
  series: SeriesPoint[];
  requested_location?: { lat: number; lon: number };
  grid_location?: { lat: number; lon: number };
  snap_distance_km?: number;
  data_source?: "regional_0.125deg" | "global_1deg";
  data_source_label?: string;
  grid_resolution_degrees?: number;
  requested_period?: { start: string; end: string };
  data_period?: { start: string; end: string };
  period_adjusted?: boolean;
  period_note?: string | null;
};
export type TrendResponse = {
  latitudes: number[];
  longitudes: number[];
  values: (number | null)[][];
  unit: string;
  area_mean: number;
  data_source?: "regional_0.125deg" | "global_1deg";
  data_source_label?: string;
  grid_resolution_degrees?: number;
  requested_period?: { start: string; end: string };
  data_period?: { start: string; end: string };
  period_adjusted?: boolean;
  period_note?: string | null;
};
export type ProjectionResponse = { target_year: number; base_year: number; estimate_values: (number | null)[][]; change_mm_values: (number | null)[][]; latitudes: number[]; longitudes: number[] };
