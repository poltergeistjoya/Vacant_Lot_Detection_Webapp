import * as maplibregl from 'maplibre-gl';
import 'maplibre-gl/dist/maplibre-gl.css';
import {
  ESRI_BASEMAP_URL, ESRI_ATTRIBUTION, BRONX_CENTER_LNG_LAT,
  DEFAULT_ZOOM, CHECKPOINTS, DEFAULT_THRESHOLD, tileUrl, NAIP_TILE_URL,
} from './lib/layers.js';
import { initSlider, setThresholdsData, getDefaultIndex } from './slider.js';
import { TOOLTIPS } from './tooltips.js';

const IS_DEV = new URLSearchParams(window.location.search).has('dev');

const defaultCP = CHECKPOINTS[getDefaultIndex()];
let currentTStr = defaultCP.tStr;

// ── Layer definitions ───────────────────────────────
// Core layers always available; dev layers only with ?dev
const LAYERS = [
  { id: 'naip',    label: 'NAIP Imagery',   defaultOn: false, tooltip: TOOLTIPS.naip },
  { id: 'overlay', label: 'Vacant Overlay', defaultOn: true,  tooltip: TOOLTIPS.overlay },
];

const DEV_LAYERS = [
  { id: 'error', label: 'Error Map', defaultOn: false, tooltip: TOOLTIPS.error },
  { id: 'roads', label: 'Roads',     defaultOn: true,  tooltip: TOOLTIPS.roads },
  { id: 'parks', label: 'Parks',     defaultOn: false, tooltip: TOOLTIPS.parks },
];

const allLayers = IS_DEV ? [...LAYERS, ...DEV_LAYERS] : LAYERS;
const layerVisibility = {};
allLayers.forEach(l => { layerVisibility[l.id] = l.defaultOn; });

// ── Map ─────────────────────────────────────────────
const map = new maplibregl.Map({
  container: 'map',
  style: {
    version: 8,
    sources: {
      esri: {
        type: 'raster',
        tiles: [ESRI_BASEMAP_URL],
        tileSize: 256,
        attribution: ESRI_ATTRIBUTION,
      },
    },
    layers: [{ id: 'esri', type: 'raster', source: 'esri' }],
  },
  center: BRONX_CENTER_LNG_LAT,
  zoom: DEFAULT_ZOOM,
  maxZoom: 18,
});

map.addControl(new maplibregl.NavigationControl(), 'top-right');

// ── Sources & layers on load ────────────────────────
map.on('load', () => {
  addSources();
  addMapLayers();
  buildLayerPanel();
  loadThresholds();
});

function addSources() {
  map.addSource('naip', {
    type: 'raster',
    tiles: [NAIP_TILE_URL],
    tileSize: 256,
  });

  map.addSource('overlay', {
    type: 'raster',
    tiles: [tileUrl('overlay', currentTStr)],
    tileSize: 256,
  });

  if (IS_DEV) {
    map.addSource('error', {
      type: 'raster',
      tiles: [tileUrl('error', currentTStr)],
      tileSize: 256,
    });

    map.addSource('roads', {
      type: 'geojson',
      data: 'roads.geojson',
    });

    map.addSource('parks', {
      type: 'geojson',
      data: 'parks.geojson',
    });
  }
}

function addMapLayers() {
  map.addLayer({
    id: 'naip',
    type: 'raster',
    source: 'naip',
    layout: { visibility: layerVisibility.naip ? 'visible' : 'none' },
  });

  map.addLayer({
    id: 'overlay',
    type: 'raster',
    source: 'overlay',
    layout: { visibility: layerVisibility.overlay ? 'visible' : 'none' },
    paint: { 'raster-opacity': 1, 'raster-opacity-transition': { duration: 150 } },
  });

  if (IS_DEV) {
    map.addLayer({
      id: 'error',
      type: 'raster',
      source: 'error',
      layout: { visibility: layerVisibility.error ? 'visible' : 'none' },
      paint: { 'raster-opacity': 1, 'raster-opacity-transition': { duration: 150 } },
    });

    map.addLayer({
      id: 'roads',
      type: 'line',
      source: 'roads',
      layout: { visibility: layerVisibility.roads ? 'visible' : 'none' },
      paint: {
        'line-color': '#141414',
        'line-opacity': 0.55,
        'line-width': ['interpolate', ['linear'], ['zoom'], 12, 1, 16, 2.5],
      },
    });

    map.addLayer({
      id: 'parks-fill',
      type: 'fill',
      source: 'parks',
      paint: { 'fill-color': '#2ecc71', 'fill-opacity': 0.25 },
      layout: { visibility: layerVisibility.parks ? 'visible' : 'none' },
    });

    map.addLayer({
      id: 'parks-line',
      type: 'line',
      source: 'parks',
      paint: { 'line-color': '#27ae60', 'line-width': 1.5 },
      layout: { visibility: layerVisibility.parks ? 'visible' : 'none' },
    });
  }
}

// ── Layer panel ─────────────────────────────────────
function buildLayerPanel() {
  const panel = document.getElementById('layer-panel');
  allLayers.forEach(l => {
    const row = document.createElement('div');
    row.className = 'layer-row';

    const cb = document.createElement('input');
    cb.type = 'checkbox';
    cb.id = `layer-${l.id}`;
    cb.checked = layerVisibility[l.id];
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
  layerVisibility[id] = visible;
  const vis = visible ? 'visible' : 'none';
  if (id === 'parks') {
    map.setLayoutProperty('parks-fill', 'visibility', vis);
    map.setLayoutProperty('parks-line', 'visibility', vis);
  } else {
    map.setLayoutProperty(id, 'visibility', vis);
  }
}

// ── Threshold change ────────────────────────────────
function onThresholdChange(cp) {
  currentTStr = cp.tStr;
  swapRasterSource('overlay', tileUrl('overlay', cp.tStr));
  if (IS_DEV) swapRasterSource('error', tileUrl('error', cp.tStr));
}

function swapRasterSource(layerId, newUrl) {
  const wasVisible = map.getLayoutProperty(layerId, 'visibility') === 'visible';
  map.removeLayer(layerId);
  map.removeSource(layerId);

  map.addSource(layerId, {
    type: 'raster',
    tiles: [newUrl],
    tileSize: 256,
  });

  const layerDef = {
    id: layerId,
    type: 'raster',
    source: layerId,
    layout: { visibility: wasVisible ? 'visible' : 'none' },
    paint: { 'raster-opacity': 1, 'raster-opacity-transition': { duration: 150 } },
  };

  const beforeId = getInsertBefore(layerId);
  map.addLayer(layerDef, beforeId);
}

function getInsertBefore(layerId) {
  const order = IS_DEV
    ? ['naip', 'overlay', 'error', 'roads', 'parks-fill']
    : ['naip', 'overlay'];
  const idx = order.indexOf(layerId);
  for (let i = idx + 1; i < order.length; i++) {
    if (map.getLayer(order[i])) return order[i];
  }
  return undefined;
}

// ── Init slider ─────────────────────────────────────
initSlider(document.getElementById('slider-container'), onThresholdChange);

// ── Load thresholds.json ────────────────────────────
async function loadThresholds() {
  try {
    const resp = await fetch('thresholds.json');
    const data = await resp.json();
    setThresholdsData(data);
  } catch (e) {
    console.warn('Could not load thresholds.json:', e);
  }
}
