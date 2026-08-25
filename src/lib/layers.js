// ── Shared constants ────────────────────────────────
export const ESRI_BASEMAP_URL =
  'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}';
export const ESRI_ATTRIBUTION =
  'Tiles &copy; Esri &mdash; Source: Esri, Maxar, Earthstar Geographics, and the GIS User Community';

export const BRONX_CENTER = [40.8501, -73.8662];
export const BRONX_CENTER_LNG_LAT = [-73.855, 40.855]; // MapLibre uses [lng, lat]
export const DEFAULT_ZOOM = 13;

// ── Playground (Leaflet) constants ──────────────────
export const MASK_PNG_URL = 'mask_overlay.png';
export const MASK_BOUNDS_URL = 'mask_overlay.json';

// Playground treatment defaults — basemap, vacant, and non-vacant each get
// the same set of CSS-filter knobs; boundary effects are vacant-only.
export const DEFAULTS = {
  // Basemap treatment
  basemapBrightness: 1,
  basemapContrast: 1,
  basemapSaturation: 1,
  basemapHue: 0,
  basemapBlur: 0,

  // Vacant area treatment
  vacantBrightness: 1,
  vacantContrast: 1,
  vacantSaturation: 1,
  vacantHue: 0,
  vacantBlur: 0,

  // Non-vacant area treatment
  nonVacantBrightness: 1,
  nonVacantContrast: 1,
  nonVacantSaturation: 1,
  nonVacantHue: 0,
  nonVacantBlur: 0,

  // Boundary effects (vacant only)
  outlineEnabled: false,
  outlineColor: '#ffffff',
  outlineWidth: 3,
  outlineOpacity: 1,

  glowEnabled: false,
  glowColor: '#ff8c00',
  glowRadius: 15,
  glowStrength: 0.8,
  glowOpacity: 0.8,

  shadowEnabled: false,
  shadowRadius: 12,
  shadowStrength: 0.5,
};

// ── Product (MapLibre) constants ────────────────────
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

export const NAIP_TILE_URL = `${TILE_BASE}/naip/{z}/{x}/{y}.png`;
