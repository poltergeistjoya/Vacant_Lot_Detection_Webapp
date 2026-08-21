export const CHECKPOINTS = [
  { t: 0.0,   tStr: 't0000' },
  { t: 0.1,   tStr: 't0100' },
  { t: 0.2,   tStr: 't0200' },
  { t: 0.298, tStr: 't0298' },
  { t: 0.32,  tStr: 't0320' },
  { t: 0.34,  tStr: 't0340' },
  { t: 0.36,  tStr: 't0360' },
  { t: 0.38,  tStr: 't0380' },
  { t: 0.40,  tStr: 't0400' },
  { t: 0.42,  tStr: 't0420' },
  { t: 0.44,  tStr: 't0440' },
  { t: 0.45,  tStr: 't0450' },
  { t: 0.5,   tStr: 't0500' },
  { t: 0.6,   tStr: 't0600' },
  { t: 0.7,   tStr: 't0700' },
  { t: 0.8,   tStr: 't0800' },
  { t: 0.9,   tStr: 't0900' },
  { t: 1.0,   tStr: 't1000' },
];

export const DEFAULT_THRESHOLD = 0.298;
export const GOOD_ZONE = [0.298, 0.450];

export const TILE_BASE = '/tiles';

export function tileUrl(type, tStr) {
  return `${TILE_BASE}/${tStr}/${type}/{z}/{x}/{y}.png`;
}

export const ESRI_BASEMAP_URL =
  'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}';

export const NAIP_TILE_URL = `${TILE_BASE}/naip/{z}/{x}/{y}.png`;
