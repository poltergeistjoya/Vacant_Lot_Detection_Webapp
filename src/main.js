import * as maplibregl from 'maplibre-gl';
import 'maplibre-gl/dist/maplibre-gl.css';
import {
  ESRI_BASEMAP_URL, ESRI_ATTRIBUTION, ESRI_METADATA_URL,
  BRONX_CENTER_LNG_LAT, DEFAULT_ZOOM, MIN_ZOOM, MAX_BOUNDS,
  CHECKPOINTS, NAIP_TILE_URL,
  BRONX_CD_NAMES,
} from './lib/layers.js';
import { addDistrictLayer } from './lib/districts.js';
import { addParcelLayer, updateParcelThreshold } from './lib/parcels.js';
import { initSlider, setThresholdsData, getDefaultIndex } from './slider.js';
import { TOOLTIPS } from './tooltips.js';

const defaultCP = CHECKPOINTS[getDefaultIndex()];
let currentTStr = defaultCP.tStr;

// ── Layer state ────────────────────────────────────
const layerState = {
  overlay: true,
  naip: false,
  parcels: false,
};

let selectedCD = null;
let parcelCount = 0;
let plutoVersion = '';
let imagerySource = 'Esri World Imagery';

const MONTHS = [
  'January', 'February', 'March', 'April', 'May', 'June',
  'July', 'August', 'September', 'October', 'November', 'December',
];

async function fetchImageryInfo(lng, lat, zoom) {
  try {
    const d = 0.005;
    const params = new URLSearchParams({
      geometry: `${lng - d},${lat - d},${lng + d},${lat + d}`,
      geometryType: 'esriGeometryEnvelope',
      spatialRel: 'esriSpatialRelIntersects',
      inSR: '4326',
      outFields: 'SRC_DATE2,SRC_DESC,MinMapLevel,MaxMapLevel',
      returnGeometry: 'false',
      f: 'json',
    });
    const resp = await fetch(`${ESRI_METADATA_URL}?${params}`);
    const data = await resp.json();
    if (data.features?.length) {
      const z = Math.round(zoom);
      const match = data.features.find(f => {
        const a = f.attributes;
        return z >= (a.MinMapLevel || 0) && z <= (a.MaxMapLevel || 99);
      }) || data.features[data.features.length - 1];
      const attrs = match.attributes;
      const name = attrs.SRC_DESC || 'Esri World Imagery';
      if (attrs.SRC_DATE2) {
        const dt = new Date(attrs.SRC_DATE2);
        const dateStr = `${dt.getFullYear()} ${MONTHS[dt.getMonth()]} ${String(dt.getDate()).padStart(2, '0')}`;
        return `${name} · ${dateStr}`;
      }
      return name;
    }
  } catch { /* fall through */ }
  return 'Esri World Imagery';
}

// ── Footer ────────────────────────────────────────
function updateFooter() {
  const sources = [];

  sources.push('U-Net (ResNet-34)');

  if (layerState.naip) {
    sources.push('NAIP 2022 · 60 cm/px');
  } else {
    sources.push(imagerySource);
  }

  if (layerState.parcels) {
    const ver = plutoVersion ? ` · ${plutoVersion}` : '';
    sources.push(`MapPLUTO${ver}`);
  }

  let text = sources.join(' | ');

  if (selectedCD) {
    const cdNum = selectedCD % 100;
    const name = BRONX_CD_NAMES[selectedCD] || `District ${cdNum}`;
    text += ` · CD ${cdNum} — ${name}`;
  }

  const el = document.getElementById('footer-info');
  if (el) el.textContent = text;
}

// ── Map ─────────────────────────────────────────────
const map = new maplibregl.Map({
  container: 'map',
  style: {
    version: 8,
    sources: {
      basemap: {
        type: 'raster',
        tiles: [ESRI_BASEMAP_URL],
        tileSize: 256,
        attribution: ESRI_ATTRIBUTION,
      },
      product: {
        type: 'raster',
        tiles: [`/api/tile/product/{z}/{x}/{y}.png?t=${currentTStr}`],
        tileSize: 256,
      },
    },
    layers: [
      { id: 'basemap-layer', type: 'raster', source: 'basemap' },
      { id: 'product-layer', type: 'raster', source: 'product' },
    ],
  },
  center: BRONX_CENTER_LNG_LAT,
  zoom: DEFAULT_ZOOM,
  minZoom: MIN_ZOOM,
  maxZoom: 19,
  maxBounds: MAX_BOUNDS,
});

map.addControl(new maplibregl.NavigationControl(), 'top-right');

// ── Tile URL logic ─────────────────────────────────
function updateTileSource() {
  const url = layerState.naip
    ? NAIP_TILE_URL
    : `/api/tile/product/{z}/{x}/{y}.png?t=${currentTStr}`;
  map.getSource('product')?.setTiles([url]);
}

function applyBasemapTreatment(bm) {
  if (!bm || !map.getLayer('basemap-layer')) return;
  if (bm.grayscale != null) {
    map.setPaintProperty('basemap-layer', 'raster-saturation', -bm.grayscale);
  }
  if (bm.brightness != null) {
    map.setPaintProperty('basemap-layer', 'raster-brightness-max', bm.brightness);
  }
  if (bm.sig_contrast != null && bm.sig_contrast !== 0) {
    map.setPaintProperty('basemap-layer', 'raster-contrast', Math.tanh(bm.sig_contrast / 10));
  }
}

// ── Layer panel ─────────────────────────────────────
const LAYERS = [
  { id: 'naip',    label: 'NAIP Imagery',       defaultOn: false, tooltip: TOOLTIPS.naip },
  { id: 'overlay', label: 'Vacant Overlay',      defaultOn: true,  tooltip: TOOLTIPS.overlay },
  { id: 'cd',      label: 'Community Districts', defaultOn: true,  tooltip: TOOLTIPS.cd },
  { id: 'parcels', label: 'Parcel Ownership',    defaultOn: false, tooltip: TOOLTIPS.parcels },
];

function buildLayerPanel() {
  const panel = document.getElementById('layer-panel');

  LAYERS.forEach(l => {
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
    const tipText = document.createElement('span');
    tipText.className = 'tooltip-text';
    tipText.textContent = l.tooltip;
    tip.append(tipText);
    tip.addEventListener('mouseenter', () => {
      const r = tip.getBoundingClientRect();
      const sidebar = document.querySelector('.sidebar');
      const sidebarRight = sidebar ? sidebar.getBoundingClientRect().right : r.right;
      tipText.style.top = `${r.top}px`;
      tipText.style.left = `${sidebarRight + 8}px`;
      tipText.style.display = 'block';
    });
    tip.addEventListener('mouseleave', () => { tipText.style.display = 'none'; });

    row.append(cb, label, tip);
    panel.append(row);

    if (l.id === 'parcels') {
      const countRow = document.createElement('div');
      countRow.id = 'parcel-count-row';
      countRow.className = 'layer-stat';
      countRow.hidden = true;

      const countLabel = document.createElement('span');
      countLabel.textContent = 'Vacant Lots Found ';

      const countValue = document.createElement('strong');
      countValue.id = 'parcel-count-value';

      const countTip = document.createElement('span');
      countTip.className = 'tooltip-chip';
      countTip.textContent = '?';
      const countTipText = document.createElement('span');
      countTipText.className = 'tooltip-text';
      countTipText.textContent = 'Vacant lots found by model or recorded in MapPLUTO';
      countTip.append(countTipText);
      countTip.addEventListener('mouseenter', () => {
        const r = countTip.getBoundingClientRect();
        const sidebar = document.querySelector('.sidebar');
        const sidebarRight = sidebar ? sidebar.getBoundingClientRect().right : r.right;
        countTipText.style.top = `${r.top}px`;
        countTipText.style.left = `${sidebarRight + 8}px`;
        countTipText.style.display = 'block';
      });
      countTip.addEventListener('mouseleave', () => { countTipText.style.display = 'none'; });

      countRow.append(countLabel, countValue, countTip);
      panel.append(countRow);

      const legend = document.createElement('div');
      legend.id = 'parcel-legend';
      legend.className = 'legend';
      legend.hidden = true;
      legend.style.paddingLeft = '24px';

      const items = [
        { color: '#ef4444', label: 'Model + PLUTO agree' },
        { color: '#f97316', label: 'Model predicted only' },
        { color: '#3b82f6', label: 'PLUTO recorded only' },
      ];
      items.forEach(({ color, label }) => {
        const item = document.createElement('div');
        item.className = 'legend-item';

        const swatch = document.createElement('span');
        swatch.className = 'legend-swatch';
        swatch.style.background = color;

        const text = document.createElement('span');
        text.className = 'legend-label';
        text.textContent = label;

        item.append(swatch, text);
        legend.append(item);
      });

      panel.append(legend);
    }
  });
}

function toggleLayer(id, visible) {
  if (id === 'overlay') {
    layerState.overlay = visible;
    map.setLayoutProperty('product-layer', 'visibility', visible ? 'visible' : 'none');
    updateFooter();
  } else if (id === 'naip') {
    layerState.naip = visible;
    map.getSource('basemap')?.setTiles([visible ? NAIP_TILE_URL : ESRI_BASEMAP_URL]);
    map.setLayoutProperty('product-layer', 'visibility',
      (!visible && layerState.overlay) ? 'visible' : 'none');
    updateFooter();
  } else if (id === 'cd') {
    const vis = visible ? 'visible' : 'none';
    if (map.getLayer('cd-fill')) map.setLayoutProperty('cd-fill', 'visibility', vis);
    if (map.getLayer('cd-line')) map.setLayoutProperty('cd-line', 'visibility', vis);
  } else if (id === 'parcels') {
    layerState.parcels = visible;
    const vis = visible ? 'visible' : 'none';
    if (map.getLayer('parcel-fill')) map.setLayoutProperty('parcel-fill', 'visibility', vis);
    if (map.getLayer('parcel-line')) map.setLayoutProperty('parcel-line', 'visibility', vis);
    const countRow = document.getElementById('parcel-count-row');
    if (countRow) countRow.hidden = !visible;
    const legend = document.getElementById('parcel-legend');
    if (legend) legend.hidden = !visible;
    updateFooter();
  }
}

// ── Threshold change ────────────────────────────────
function onThresholdChange(cp) {
  currentTStr = cp.tStr;
  updateTileSource();
  const count = updateParcelThreshold(map, cp.tStr);
  if (count !== null) {
    parcelCount = count;
    const val = document.getElementById('parcel-count-value');
    if (val) val.textContent = parcelCount.toLocaleString();
  }
}

// ── Imagery metadata ───────────────────────────────
let imageryDebounce = null;
function onMapMove() {
  clearTimeout(imageryDebounce);
  imageryDebounce = setTimeout(async () => {
    const { lng, lat } = map.getCenter();
    imagerySource = await fetchImageryInfo(lng, lat, map.getZoom());
    updateFooter();
  }, 500);
}

// ── Init ────────────────────────────────────────────
map.on('load', () => {
  addCDLayer();
  addParcelLayer(map, currentTStr).then(info => {
    if (info) {
      parcelCount = info.count;
      plutoVersion = info.version;
      const val = document.getElementById('parcel-count-value');
      if (val) val.textContent = parcelCount.toLocaleString();
    }
  });
  buildLayerPanel();
  loadThresholds();
  onMapMove();

  map.on('moveend', onMapMove);
});

async function addCDLayer() {
  let cdStyle;
  try {
    const resp = await fetch('product_treatment.json');
    const treatment = await resp.json();
    cdStyle = treatment.cd;
    applyBasemapTreatment(treatment.basemap);
  } catch { /* use defaults */ }

  await addDistrictLayer(map, {
    style: cdStyle,
    onSelect(boroCD) {
      selectedCD = boroCD;
      updateFooter();
    },
  });
}

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
