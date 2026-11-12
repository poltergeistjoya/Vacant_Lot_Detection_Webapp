import thresholds from '../../data/thresholds.json';

// ── Shared constants ────────────────────────────────
export const ESRI_BASEMAP_URL =
  'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}';
export const ESRI_ATTRIBUTION =
  'Tiles &copy; Esri &mdash; Source: Esri, Maxar, Earthstar Geographics, and the GIS User Community';

export const ESRI_METADATA_URL =
  'https://services.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/4/query';

export const BRONX_CENTER = [40.8501, -73.8662];
export const BRONX_CENTER_LNG_LAT = [-73.855, 40.855];
export const DEFAULT_ZOOM = 13;
export const MIN_ZOOM = 11;
export const MAX_BOUNDS = [[-74.65, 40.3], [-73.05, 41.4]];

// ── Playground constants ─────────────────────────────
// Mask paths are in lib/map.js (not exported — only map.js loads them).

// Treatment defaults — each group has the same color-op knobs.
// Keys match the backend query parameter aliases.
export const TREATMENT_DEFAULTS = {
  sc: 0,       // sigmoidal contrast
  sb: 0.5,     // sigmoidal bias
  g: 1,        // master gamma
  gr: 1,       // gamma red
  gg: 1,       // gamma green
  gb: 1,       // gamma blue
  sat: 1,      // saturation
  gray: 0,     // grayscale
  br: 1,       // brightness
};

export const VACANT_EXTRA_DEFAULTS = {
  tint: '000000',  // tint color hex
  to: 0,           // tint opacity
};

export const BOUNDARY_DEFAULTS = {
  outlineEnabled: false,
  outlineColor: '#ffffff',
  outlineWidth: 3,
  outlineOpacity: 1,

  bloomEnabled: false,
  bloomColor: '#ff8c00',
  bloomRadius: 15,
  bloomIntensity: 0.8,

  shadowEnabled: false,
  shadowRadius: 12,
  shadowStrength: 0.5,
};

// ── Community District constants ─────────────────────
export const CD_GEOJSON_URL = 'community_districts.geojson';

// ── Parcel (MapPLUTO) constants ───────────────────────
export const PARCELS_GEOJSON_URL = 'parcels.geojson';

// ── Athletic surface constants ──────────────────────
export const ATHLETIC_GEOJSON_URL = 'athletic_surfaces_enriched.geojson';

export const BRONX_CD_NAMES = {
  201: 'Mott Haven / Melrose',
  202: 'Hunts Point / Longwood',
  203: 'Morrisania / Crotona',
  204: 'Highbridge / Concourse',
  205: 'Fordham / University Heights',
  206: 'Belmont / East Tremont',
  207: 'Kingsbridge / Riverdale',
  208: 'Riverdale / Fieldston',
  209: 'Parkchester / Soundview',
  210: 'Throgs Neck / Co-op City',
  211: 'Morris Park / Pelham Parkway',
  212: 'Williamsbridge / Baychester',
  226: 'Van Cortlandt Park',
  227: 'Bronx Park / NY Botanical Garden',
  228: 'Pelham Bay Park',
};

// ── Product (MapLibre) constants ────────────────────
// Thresholds are defined once, in data/thresholds.json (scripts/extract_metrics.py);
// the archives and scripts use the same list (THRESHOLDS in server/compositing.py).
export const CHECKPOINTS = thresholds.checkpoints.map(({ t, tStr }) => ({ t, tStr }));
export const DEFAULT_THRESHOLD = thresholds.default_threshold;
export const GOOD_ZONE = thresholds.good_zone;

export const NAIP_TILE_URL = '/tiles/naip/{z}/{x}/{y}.png';
