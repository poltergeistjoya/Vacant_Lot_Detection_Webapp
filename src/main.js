import * as maplibregl from 'maplibre-gl';
import 'maplibre-gl/dist/maplibre-gl.css';
import {
  ESRI_BASEMAP_URL, ESRI_ATTRIBUTION, BRONX_CENTER_LNG_LAT,
  DEFAULT_ZOOM, CHECKPOINTS, DEFAULT_THRESHOLD, NAIP_TILE_URL,
} from './lib/layers.js';
import { initSlider, setThresholdsData, getDefaultIndex } from './slider.js';
import { TOOLTIPS } from './tooltips.js';

const IS_DEV = new URLSearchParams(window.location.search).has('dev');

const defaultCP = CHECKPOINTS[getDefaultIndex()];
let currentTStr = defaultCP.tStr;

// ── Layer state ────────────────────────────────────
const layerState = {
  overlay: true,
  naip: false,
};

// ── Map ─────────────────────────────────────────────
const map = new maplibregl.Map({
  container: 'map',
  style: {
    version: 8,
    sources: {
      product: {
        type: 'raster',
        tiles: [productTileUrl()],
        tileSize: 256,
        attribution: ESRI_ATTRIBUTION,
      },
    },
    layers: [{ id: 'product', type: 'raster', source: 'product' }],
  },
  center: BRONX_CENTER_LNG_LAT,
  zoom: DEFAULT_ZOOM,
  maxZoom: 18,
});

map.addControl(new maplibregl.NavigationControl(), 'top-right');

// ── Tile URL logic ─────────────────────────────────
function productTileUrl() {
  if (!layerState.overlay) {
    return layerState.naip
      ? NAIP_TILE_URL
      : ESRI_BASEMAP_URL;
  }
  return `/api/tile/product/{z}/{x}/{y}.png?t=${currentTStr}`;
}

function updateTileSource() {
  const url = productTileUrl();
  const wasVisible = map.getLayoutProperty('product', 'visibility') !== 'none';

  map.removeLayer('product');
  map.removeSource('product');

  map.addSource('product', {
    type: 'raster',
    tiles: [url],
    tileSize: 256,
    attribution: ESRI_ATTRIBUTION,
  });

  map.addLayer({
    id: 'product',
    type: 'raster',
    source: 'product',
    layout: { visibility: wasVisible ? 'visible' : 'none' },
  }, getDevInsertBefore());
}

function getDevInsertBefore() {
  if (!IS_DEV) return undefined;
  const devOrder = ['error', 'roads', 'parks-fill'];
  for (const id of devOrder) {
    if (map.getLayer(id)) return id;
  }
  return undefined;
}

// ── Layer panel ─────────────────────────────────────
const LAYERS = [
  { id: 'naip',    label: 'NAIP Imagery',  defaultOn: false, tooltip: TOOLTIPS.naip },
  { id: 'overlay', label: 'Vacant Overlay', defaultOn: true,  tooltip: TOOLTIPS.overlay },
];

function buildLayerPanel() {
  const panel = document.getElementById('layer-panel');
  const allLayers = IS_DEV
    ? [...LAYERS, { id: 'error', label: 'Error Map', defaultOn: false, tooltip: TOOLTIPS.error }]
    : LAYERS;

  allLayers.forEach(l => {
    const row = document.createElement('div');
    row.className = 'layer-row';

    const cb = document.createElement('input');
    cb.type = 'checkbox';
    cb.id = `layer-${l.id}`;
    cb.checked = l.id === 'overlay' ? layerState.overlay
               : l.id === 'naip' ? layerState.naip
               : l.defaultOn;
    cb.addEventListener('change', () => toggleLayer(l.id, cb.checked));

    const label = document.createElement('label');
    label.htmlFor = cb.id;
    label.textContent = l.label;

    const tip = document.createElement('span');
    tip.className = 'tooltip-chip';
    tip.textContent = '?';
    tip.title = l.tooltip;

    row.append(cb, label, tip);
    panel.append(row);
  });
}

function toggleLayer(id, visible) {
  if (id === 'overlay' || id === 'naip') {
    layerState[id] = visible;
    updateTileSource();
  } else if (IS_DEV) {
    const vis = visible ? 'visible' : 'none';
    if (id === 'parks') {
      map.setLayoutProperty('parks-fill', 'visibility', vis);
      map.setLayoutProperty('parks-line', 'visibility', vis);
    } else if (map.getLayer(id)) {
      map.setLayoutProperty(id, 'visibility', vis);
    }
  }
}

// ── Dev-only layers ─────────────────────────────────
function addDevLayers() {
  if (!IS_DEV) return;

  map.addSource('error', {
    type: 'raster',
    tiles: [`/tiles/${currentTStr}/error/{z}/{x}/{y}.png`],
    tileSize: 256,
  });
  map.addLayer({
    id: 'error',
    type: 'raster',
    source: 'error',
    layout: { visibility: 'none' },
    paint: { 'raster-opacity': 1 },
  });

  map.addSource('roads', { type: 'geojson', data: 'roads.geojson' });
  map.addLayer({
    id: 'roads',
    type: 'line',
    source: 'roads',
    layout: { visibility: 'visible' },
    paint: {
      'line-color': '#141414',
      'line-opacity': 0.55,
      'line-width': ['interpolate', ['linear'], ['zoom'], 12, 1, 16, 2.5],
    },
  });
}

// ── Threshold change ────────────────────────────────
function onThresholdChange(cp) {
  currentTStr = cp.tStr;
  updateTileSource();
}

// ── Init ────────────────────────────────────────────
map.on('load', () => {
  addDevLayers();
  buildLayerPanel();
  loadThresholds();

  // Hide error legend in non-dev mode
  if (!IS_DEV) {
    const legend = document.querySelector('.sidebar-section:last-child');
    if (legend) legend.style.display = 'none';
  }
});

initSlider(document.getElementById('slider-container'), onThresholdChange);

async function loadThresholds() {
  try {
    const resp = await fetch('thresholds.json');
    const data = await resp.json();
    setThresholdsData(data);
  } catch (e) {
    console.warn('Could not load thresholds.json:', e);
  }
}
