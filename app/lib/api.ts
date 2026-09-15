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

export function flattenGrid(latitudes: number[], longitudes: number[], values: number[][]): GridPoint[] {
  const points: GridPoint[] = [];
  latitudes.forEach((lat, i) => longitudes.forEach((lon, j) => {
    const value = values[i]?.[j];
    if (Number.isFinite(value)) points.push({ lat, lon, value });
  }));
  return points;
}

export type MapResponse = { requested_date: string; data_date: string; latitudes: number[]; longitudes: number[]; values: number[][]; unit: string };
export type SeriesResponse = { trend_mm_per_year: number; series: SeriesPoint[]; requested_location?: { lat: number; lon: number }; grid_location?: { lat: number; lon: number } };
export type TrendResponse = { latitudes: number[]; longitudes: number[]; values: number[][]; unit: string; area_mean: number };
export type ProjectionResponse = { target_year: number; base_year: number; estimate_values: number[][]; change_mm_values: number[][]; latitudes: number[]; longitudes: number[] };
