import { apiGet } from "./api";

export type BarystaticComponent = {
  key: string;
  label_ko: string;
  label_en: string;
  group: "land_ice" | "land_water_storage";
  source_start: string;
  source_end: string;
  analysis_start: string;
  analysis_end: string;
  temporal_treatment: string;
  notes_ko: string;
  connected: boolean;
  issues: string[];
};

export type BarystaticStatus = {
  connected: boolean;
  schema_version: string;
  reference_period: { start: string; end: string; operation: string };
  value_convention: {
    fingerprint_variable_unit: "mm";
    ocean_mean_variable: string;
    ocean_mean_unit: "mm";
    positive_direction: string;
    maximum_spherical_harmonic_degree: number;
  };
  analysis_policy: {
    default_start: string;
    implicit_component_sum: false;
    sum_note: string;
  };
  common_period_all_connected_components: { start: string; end: string } | null;
  components: BarystaticComponent[];
};

export type BarystaticSeriesPoint = {
  date: string;
  monthly_mm: number | null;
  moving_12m_mm: number | null;
  linear_trend_mm: number | null;
  quality: "source_monthly" | "interpolated_from_annual" | "extrapolated" | "mission_gap";
};

export type BarystaticSeries = {
  component: string;
  components?: string[];
  label_ko: string;
  requested_period: { start: string; end: string };
  data_period: { start: string; end: string };
  reference_period: { start: string; end: string; operation: string };
  unit: "mm";
  trend_mm_per_year: number;
  temporal_treatment: string;
  series: BarystaticSeriesPoint[];
};

export type BarystaticMap = {
  component: string;
  components?: string[];
  label_ko: string;
  requested_date: string;
  data_date: string;
  reference_period: { start: string; end: string; operation: string };
  latitudes: number[];
  longitudes: number[];
  values: (number | null)[][];
  unit: "mm";
  cyclic_endpoint_removed: boolean;
  quality: BarystaticSeriesPoint["quality"] | "mixed";
};

export type BarystaticTrendMap = Omit<
  BarystaticMap,
  "requested_date" | "data_date" | "quality" | "unit"
> & {
  requested_period: { start: string; end: string };
  data_period: { start: string; end: string };
  months_used: number;
  warning: string | null;
  unit: "mm/year";
};

export type GraceStatus = {
  connected: boolean;
  message?: string;
  source?: string;
  period?: { start: string; end: string };
  reference_period?: { start: string; end: string };
  available_months?: number;
  mission_gap_months?: number;
  mission_gap?: string;
  unit?: "mm";
  issues?: string[];
};

export type CauseOverviewLayer = "observed" | "grace";

export type CauseOverviewStatus = {
  connected: boolean;
  message?: string;
  source?: string;
  period?: { start: string; end: string };
  reference_period?: { start: string; end: string };
  available_grace_months?: number;
  mission_gap_months?: number;
  common_ocean_cells?: number;
  grid?: string;
  alignment?: string;
  mask_policy?: string;
  layers?: { observed: boolean; grace: boolean; steric: boolean };
  unit?: "mm";
  issues?: string[];
};

export type CauseOverviewSeriesPoint = {
  date: string;
  observed_mm: number | null;
  grace_mm: number | null;
  observed_moving_12m_mm: number | null;
  grace_moving_12m_mm: number | null;
  quality: "source_monthly" | "grace_mission_gap";
};

export type CauseOverviewSeries = {
  requested_period: { start: string; end: string };
  reference_period: { start: string; end: string };
  unit: "mm";
  common_ocean_cells: number;
  common_observation_months: number;
  trend_month_policy: string;
  observed_trend_mm_per_year: number;
  grace_trend_mm_per_year: number;
  series: CauseOverviewSeriesPoint[];
};

const query = (values: Record<string, string>) => new URLSearchParams(values).toString();

export const getBarystaticStatus = () =>
  apiGet<BarystaticStatus>("/api/causes/barystatic/components");

export const getGraceStatus = () =>
  apiGet<GraceStatus>("/api/causes/grace/status");

export const getGraceSeries = (start: string, end: string) =>
  apiGet<BarystaticSeries>(
    `/api/causes/grace/series?${query({ start, end })}`,
  );

export const getGraceMap = (date: string) =>
  apiGet<BarystaticMap>(
    `/api/causes/grace/map?${query({ date })}`,
  );

export const getCauseOverviewStatus = () =>
  apiGet<CauseOverviewStatus>("/api/causes/overview/status");

export const getCauseOverviewSeries = (start: string, end: string) =>
  apiGet<CauseOverviewSeries>(
    `/api/causes/overview/series?${query({ start, end })}`,
  );

export const getCauseOverviewMap = (date: string, layer: CauseOverviewLayer) =>
  apiGet<BarystaticMap>(
    `/api/causes/overview/map?${query({ date, layer })}`,
  );

export const getBarystaticSeries = (component: string, start: string, end: string) =>
  apiGet<BarystaticSeries>(
    `/api/causes/barystatic/${encodeURIComponent(component)}/series?${query({ start, end })}`,
  );

export const getBarystaticMap = (component: string, date: string) =>
  apiGet<BarystaticMap>(
    `/api/causes/barystatic/${encodeURIComponent(component)}/map?${query({ date })}`,
  );

const componentQuery = (components: string[]) => components.join(",");

export const getCombinedBarystaticSeries = (
  components: string[],
  start: string,
  end: string,
) =>
  apiGet<BarystaticSeries>(
    `/api/causes/barystatic/combined/series?${query({
      components: componentQuery(components),
      start,
      end,
    })}`,
  );

export const getCombinedBarystaticMap = (components: string[], date: string) =>
  apiGet<BarystaticMap>(
    `/api/causes/barystatic/combined/map?${query({
      components: componentQuery(components),
      date,
    })}`,
  );

export const getBarystaticTrendMap = (component: string, start: string, end: string) =>
  apiGet<BarystaticTrendMap>(
    `/api/causes/barystatic/${encodeURIComponent(component)}/trend-map?${query({ start, end })}`,
  );

export const getCombinedBarystaticTrendMap = (
  components: string[],
  start: string,
  end: string,
) =>
  apiGet<BarystaticTrendMap>(
    `/api/causes/barystatic/combined/trend-map?${query({
      components: componentQuery(components),
      start,
      end,
    })}`,
  );
