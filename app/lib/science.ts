export type GridPoint = { lat: number; lon: number; value: number };
export type SeriesPoint = { date: string; monthly: number; moving: number | null; trend: number };

export const startDate = "1993-01-01";
export const endDate = "2024-12-01";

const hash = (lat: number, lon: number) => Math.sin(lat * 1.7) * 0.025 + Math.cos(lon * 0.8) * 0.018;

export function demoGrid(kind: "height" | "trend" | "projection" | "change", year = 2024): GridPoint[] {
  const points: GridPoint[] = [];
  for (let lat = 30; lat <= 46; lat += 2) {
    for (let lon = 117; lon <= 139; lon += 2) {
      const seaMask = !((lon < 121 && lat > 39) || (lon > 124 && lon < 130 && lat > 34 && lat < 40));
      if (!seaMask) continue;
      const base = hash(lat, lon) + (year - 1993) * 0.0034;
      const trend = 3.4 + Math.sin((lat + lon) * 0.9) * 1.8;
      const value = kind === "height" ? base : kind === "trend" ? trend : kind === "projection" ? base + trend * 0.076 : trend * 76;
      points.push({ lat, lon, value: Number(value.toFixed(3)) });
    }
  }
  return points;
}

export function demoSeries(lat = 38, lon = 132): SeriesPoint[] {
  const out: SeriesPoint[] = [];
  const raw: number[] = [];
  for (let i = 0; i < 384; i++) {
    const y = 1993 + Math.floor(i / 12);
    const m = i % 12;
    const seasonal = Math.sin((m / 12) * Math.PI * 2 + lat / 9) * 0.032;
    const regional = Math.cos(i / 17 + lon / 11) * 0.012;
    raw.push(-0.055 + i * (0.0039 / 12) + seasonal + regional);
    const moving = i < 11 ? null : raw.slice(i - 11, i + 1).reduce((a, b) => a + b, 0) / 12;
    out.push({ date: `${y}-${String(m + 1).padStart(2, "0")}-01`, monthly: Number(raw[i].toFixed(4)), moving: moving == null ? null : Number(moving.toFixed(4)), trend: Number((-0.055 + i * (0.0039 / 12)).toFixed(4)) });
  }
  return out;
}

export const viewMeta = {
  home: { eyebrow: "탐구 시작", title: "해수면의 변화를 직접 읽어 보세요", desc: "날짜와 장소를 고르면 위성으로 관측한 월평균 해수면 자료를 지도와 그래프로 비교할 수 있습니다." },
  date: { eyebrow: "활동 01", title: "날짜별 해수면", desc: "한 달 동안 평균한 해수면 고도 편차가 바다마다 어떻게 다른지 살펴봅니다." },
  point: { eyebrow: "활동 02", title: "한 장소의 변화", desc: "지도에서 한 지점을 고르고, 시간에 따른 월평균 변화와 장기 추세를 함께 읽습니다." },
  region: { eyebrow: "활동 03", title: "영역 평균 변화", desc: "한 격자가 아닌 분석 영역 전체를 평균해 지역적인 흔들림과 장기 경향을 구분합니다." },
  trend: { eyebrow: "활동 04", title: "변화율 지도", desc: "해수면의 높이가 아니라, 해마다 얼마나 빨리 변했는지를 격자별로 비교합니다." },
  causes: { eyebrow: "탐구 확장", title: "해수면은 왜 변할까요?", desc: "관측된 변화와 바닷물의 밀도 변화, 바다에 더해진 물의 질량을 구분해 생각합니다." },
  projection: { eyebrow: "활동 05", title: "2100년 단순 추정", desc: "과거의 선형 변화가 같은 속도로 이어진다고 가정해 2100년 값을 계산합니다." },
  admin: { eyebrow: "교사용 도구", title: "데이터 관리", desc: "NetCDF 파일을 검사한 뒤 수업에서 사용할 활성 자료로 교체합니다." },
} as const;
export type ViewKey = keyof typeof viewMeta;
