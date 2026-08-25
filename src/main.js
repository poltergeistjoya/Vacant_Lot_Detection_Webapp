import { Map as MaplibreMap, NavigationControl } from 'maplibre-gl';
import 'maplibre-gl/dist/maplibre-gl.css';
import {
  ESRI_BASEMAP_URL,
  ESRI_ATTRIBUTION,
  BRONX_CENTER_LNG_LAT,
  DEFAULT_ZOOM,
  CHECKPOINTS,
  DEFAULT_THRESHOLD,
  TILE_BASE,
  tileUrl,
  NAIP_TILE_URL,
} from './lib/layers.js';
import { initSlider, setThresholdsData, getDefaultIndex } from './slider.js';
import { TOOLTIPS } from './tooltips.js';

// ── Layer definitions ───────────────────────────────
const defaultCP = CHECKPOINTS.find(c => c.t === DEFAULT_THRESHOLD);

const LAYERS = [
  {
    id: 'naip',
    label: 'NAIP Aerial',
    tooltip: TOOLTIPS.naip,
    url: NAIP_TILE_URL,
    visible: false,
  },
  {
    id: 'overlay',
    label: 'Vacant Overlay',
    tooltip: TOOLTIPS.overlay,
    url: tileUrl('overlay', defaultCP.tStr),
    visible: true,
  },
  {
    id: 'error',
    label: 'Error Map',
    tooltip: TOOLTIPS.error,
    url: tileUrl('error', defaultCP.tStr),
    visible: false,
  },
  {
    id: 'roads',
    label: 'Roads',
    tooltip: TOOLTIPS.roads,
    url: `${TILE_BASE}/roads/{z}/{x}/{y}.png`,
    visible: false,
  },
  {
    id: 'parks',
    label: 'Parks',
    tooltip: TOOLTIPS.parks,
    url: `${TILE_BASE}/parks/{z}/{x}/{y}.png`,
    visible: false,
  },
];

// ── Map setup ───────────────────────────────────────
const map = new MaplibreMap({
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
    layers: [
      { id: 'basemap', type: 'raster', source: 'esri' },
    ],
  },
  center: BRONX_CENTER_LNG_LAT,
  zoom: DEFAULT_ZOOM,
  maxZoom: 18,
  minZoom: 10,
});

map.addControl(new NavigationControl(), 'top-right');

// ── Add tile layers on load ─────────────────────────
map.on('load', () => {
  for (const layer of LAYERS) {
    map.addSource(layer.id, {
      type: 'raster',
      tiles: [layer.url],
      tileSize: 256,
    });
    map.addLayer({
      id: layer.id,
      type: 'raster',
      source: layer.id,
      layout: {
        visibility: layer.visible ? 'visible' : 'none',
      },
    });
  }

  // Build layer panel
  buildLayerPanel();

  // Fetch threshold metrics
  fetchThresholds();
});

// ── Slider ──────────────────────────────────────────
initSlider(document.getElementById('slider-container'), (cp) => {
  swapRasterSource('overlay', tileUrl('overlay', cp.tStr));
  swapRasterSource('error', tileUrl('error', cp.tStr));
});

// ── Swap raster source (MapLibre has no setTiles) ───
function swapRasterSource(layerId, newUrl) {
  const layer = map.getLayer(layerId);
  if (!layer) return;

  const visibility = map.getLayoutProperty(layerId, 'visibility');
  map.removeLayer(layerId);
  map.removeSource(layerId);

  map.addSource(layerId, {
    type: 'raster',
    tiles: [newUrl],
    tileSize: 256,
  });
  map.addLayer({
    id: layerId,
    type: 'raster',
    source: layerId,
    layout: { visibility },
  });

  // Re-order layers to preserve draw order
  reorderLayers();
}

function reorderLayers() {
  const ids = LAYERS.map(l => l.id);
  for (let i = 1; i < ids.length; i++) {
    if (map.getLayer(ids[i]) && map.getLayer(ids[i - 1])) {
      map.moveLayer(ids[i]);
    }
  }
}

// ── Layer panel ─────────────────────────────────────
function buildLayerPanel() {
  const panel = document.getElementById('layer-panel');
  panel.innerHTML = '';

  for (const layer of LAYERS) {
    const row = document.createElement('div');
    row.className = 'layer-row';

    const cb = document.createElement('input');
    cb.type = 'checkbox';
    cb.id = `cb-${layer.id}`;
    cb.checked = layer.visible;
    cb.addEventListener('change', () => {
      map.setLayoutProperty(layer.id, 'visibility', cb.checked ? 'visible' : 'none');
    });

    const label = document.createElement('label');
    label.htmlFor = cb.id;
    label.textContent = layer.label;

    const tip = document.createElement('span');
    tip.className = 'tooltip-chip';
    tip.textContent = '?';
    const tipText = document.createElement('span');
    tipText.className = 'tooltip-text';
    tipText.textContent = layer.tooltip;
    tip.appendChild(tipText);

    row.appendChild(cb);
    row.appendChild(label);
    row.appendChild(tip);
    panel.appendChild(row);
  }
}

// ── Fetch thresholds JSON ───────────────────────────
async function fetchThresholds() {
  try {
    const resp = await fetch(`${TILE_BASE}/thresholds.json`);
    if (resp.ok) {
      const data = await resp.json();
      setThresholdsData(data);
    }
  } catch {
    // metrics stay as "Loading…" — non-fatal
  }
}
