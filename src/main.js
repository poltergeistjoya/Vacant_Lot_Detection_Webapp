import * as maplibregl from 'maplibre-gl';
import 'maplibre-gl/dist/maplibre-gl.css';
import {
  ESRI_BASEMAP_URL, ESRI_ATTRIBUTION, ESRI_METADATA_URL,
  BRONX_CENTER_LNG_LAT, DEFAULT_ZOOM, MIN_ZOOM, MAX_BOUNDS,
  CHECKPOINTS, NAIP_TILE_URL,
  BRONX_CD_NAMES,
} from './lib/layers.js';
import { addDistrictLayer } from './lib/districts.js';
import {
  addParcelLayer,
  updateParcelThreshold,
  updateParcelSource,
  countParcels,
  hasDistrictField,
} from './lib/parcels.js';
import { addAthleticLayer, updateAthleticThreshold } from './lib/athletic.js';
import { initSlider, setThresholdsData, getDefaultIndex } from './slider.js';
import { TOOLTIPS } from './tooltips.js';

const defaultCP = CHECKPOINTS[getDefaultIndex()];
let currentTStr = defaultCP.tStr;
const DEV_MODE = new URLSearchParams(window.location.search).has('dev');

// ── Layer state ────────────────────────────────────
const layerState = {
  overlay: true,
  naip: false,
  parcels: false,
  athletic: false,
};

let selectedCD = null;
let plutoVersion = '';
let osmDate = '';
let imagerySource = 'Esri World Imagery';
let vacancySource = 'both';

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

// ── Stats ─────────────────────────────────────────
const VACANT_TIP = 'Lots flagged by model predictions or NYC PLUTO records';

function statRow(label, value, tip) {
  const row = document.createElement('div');
  row.className = 'stat-row';

  const name = document.createElement('span');
  name.textContent = `${label} `;

  const val = document.createElement('strong');
  val.textContent = value;

  row.append(name, val);
  if (tip) row.append(makeTooltipChip(tip));
  return row;
}

function note(text) {
  const el = document.createElement('p');
  el.className = 'stat-note';
  el.textContent = text;
  return el;
}

function renderBronxStats() {
  const el = document.getElementById('stat-bronx');
  if (!el) return;
  el.replaceChildren();

  const total = countParcels();
  el.append(statRow(
    'Vacant lots',
    total === null ? '—' : total.toLocaleString(),
  ));
}

function renderDistrictStats() {
  const el = document.getElementById('stat-cd');
  if (!el) return;
  el.replaceChildren();

  if (!selectedCD) {
    el.append(note('Click a district on the map to select it.'));
    return;
  }

  const cdNum = selectedCD % 100;
  const cdName = BRONX_CD_NAMES[selectedCD] || `District ${cdNum}`;

  const heading = document.createElement('h3');
  heading.className = 'stats-subtitle';
  heading.textContent = cdName;
  el.append(heading);

  const num = document.createElement('div');
  num.className = 'cd-name';
  num.textContent = `Bronx CD ${cdNum}`;
  el.append(num);

  if (hasDistrictField()) {
    el.append(statRow(
      'Vacant lots',
      (countParcels({ cd: selectedCD }) ?? 0).toLocaleString(),
    ));
  } else {
    el.append(note('Per-district counts need a regenerated parcels.geojson.'));
  }
}

// Single entry point: every handler that changes what the stats depend on
// calls this, rather than each one writing to its own element.
function updateStats() {
  renderBronxStats();
  renderDistrictStats();
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

  if (layerState.athletic) {
    const date = osmDate ? ` · ${osmDate}` : '';
    sources.push(`OSM Athletic${date}`);
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
const map = window._map = new maplibregl.Map({
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
      'product-cached': {
        type: 'raster',
        tiles: [`/api/tile/product/{z}/{x}/{y}.jpg?t=${currentTStr}&source=both`],
        tileSize: 256,
        maxzoom: 18,
      },
      product: {
        type: 'raster',
        tiles: [`/api/tile/product/{z}/{x}/{y}.jpg?t=${currentTStr}&source=both`],
        tileSize: 256,
        maxzoom: 19,
      },
    },
    layers: [
      { id: 'basemap-layer', type: 'raster', source: 'basemap' },
      { id: 'product-cached-layer', type: 'raster', source: 'product-cached' },
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

// ── Loading bar ──────────────────────────────────
const loadingBar = document.getElementById('map-loading-bar');
map.on('dataloading', (e) => {
  if (e.dataType === 'source' && loadingBar) loadingBar.hidden = false;
});
map.on('idle', () => {
  if (loadingBar) loadingBar.hidden = true;
});

// ── Tile URL logic ─────────────────────────────────
function updateTileSource() {
  if (layerState.naip) {
    map.getSource('product')?.setTiles([NAIP_TILE_URL]);
    return;
  }
  const url = `/api/tile/product/{z}/{x}/{y}.jpg?t=${currentTStr}&source=${vacancySource}`;
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

// ── Tooltip chip ────────────────────────────────────
// Chips escape the sidebar's scroll container by positioning against the
// viewport, so the text is placed on hover rather than in CSS.
function makeTooltipChip(text) {
  const chip = document.createElement('span');
  chip.className = 'tooltip-chip';
  chip.textContent = '?';

  const tipText = document.createElement('span');
  tipText.className = 'tooltip-text';
  tipText.textContent = text;
  chip.append(tipText);

  chip.addEventListener('click', (e) => {
    e.stopPropagation();
    e.preventDefault();
    const isVisible = tipText.style.display === 'block';
    document.querySelectorAll('.tooltip-text').forEach(t => { t.style.display = 'none'; });
    if (!isVisible) {
      const r = chip.getBoundingClientRect();
      const sidebar = document.querySelector('.sidebar');
      const sidebarRight = sidebar ? sidebar.getBoundingClientRect().right : r.right;
      tipText.style.top = `${r.top}px`;
      tipText.style.left = `${sidebarRight + 8}px`;
      tipText.style.display = 'block';
    }
  });

  return chip;
}

document.addEventListener('click', () => {
  document.querySelectorAll('.tooltip-text').forEach(t => { t.style.display = 'none'; });
});

// ── Layer panel ─────────────────────────────────────
const LAYERS = [
  { id: 'overlay', label: 'Vacant Overlay',      defaultOn: true },
  { id: 'cd',      label: 'Community Districts', defaultOn: true,  tooltip: TOOLTIPS.cd },
  { id: 'parcels',  label: 'Parcel Ownership',    defaultOn: false, tooltip: TOOLTIPS.parcels },
];
if (DEV_MODE) {
  LAYERS.push({ id: 'athletic', label: 'Athletic Surfaces', defaultOn: false, tooltip: TOOLTIPS.athletic });
}

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

    if (l.tooltip) {
      const tip = makeTooltipChip(l.tooltip);
      row.append(cb, label, tip);
    } else {
      row.append(cb, label);
    }
    panel.append(row);

    if (l.id === 'overlay') {
      row.style.borderBottom = 'none';
      const sourceCtrl = document.createElement('div');
      sourceCtrl.id = 'vacancy-source-control';
      sourceCtrl.className = 'vacancy-source-control';

      const options = [
        { value: 'both',  label: 'Model + PLUTO',          tooltip: TOOLTIPS.overlay_both },
        { value: 'model', label: 'Model predicted vacancy', tooltip: TOOLTIPS.overlay_model },
        { value: 'pluto', label: 'NYC tracked vacant lots', tooltip: TOOLTIPS.overlay_pluto },
      ];
      options.forEach(opt => {
        const optRow = document.createElement('label');
        optRow.className = 'source-option';

        const radio = document.createElement('input');
        radio.type = 'radio';
        radio.name = 'vacancy-source';
        radio.value = opt.value;
        radio.checked = opt.value === vacancySource;
        radio.addEventListener('change', () => {
          vacancySource = opt.value;
          updateTileSource();
          updateParcelSource(map, opt.value);
          updateSliderMute();
        });

        const text = document.createElement('span');
        text.textContent = opt.label;
        const tip = makeTooltipChip(opt.tooltip);
        optRow.append(radio, text, tip);
        sourceCtrl.append(optRow);
      });
      panel.append(sourceCtrl);
    }

    if (l.id === 'parcels') {
      const legend = document.createElement('div');
      legend.id = 'parcel-legend';
      legend.className = 'legend';
      legend.hidden = true;
      legend.style.paddingLeft = '24px';

      const items = [
        { color: '#22c55e', label: 'Model + PLUTO agree' },
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

      const peekBtn = document.createElement('button');
      peekBtn.id = 'peek-btn';
      peekBtn.className = 'peek-btn';
      peekBtn.textContent = 'Peek (hold)';
      peekBtn.addEventListener('mousedown', () => setPeek(true));
      peekBtn.addEventListener('mouseup', () => setPeek(false));
      peekBtn.addEventListener('mouseleave', () => setPeek(false));
      peekBtn.addEventListener('touchstart', (e) => { e.preventDefault(); setPeek(true); });
      peekBtn.addEventListener('touchend', () => setPeek(false));
      peekBtn.addEventListener('touchcancel', () => setPeek(false));
      legend.append(peekBtn);

      panel.append(legend);
    }

    if (l.id === 'athletic') {
      const fpRow = document.createElement('div');
      fpRow.id = 'athletic-fp-row';
      fpRow.className = 'layer-stat';
      fpRow.hidden = true;

      const fpLabel = document.createElement('span');
      fpLabel.textContent = 'False Positives ';

      const fpValue = document.createElement('strong');
      fpValue.id = 'athletic-fp-value';

      fpRow.append(fpLabel, fpValue);
      panel.append(fpRow);

      const legend = document.createElement('div');
      legend.id = 'athletic-legend';
      legend.className = 'legend';
      legend.hidden = true;
      legend.style.paddingLeft = '24px';

      const items = [
        { color: '#e11d48', label: 'Model thinks vacant (false positive)' },
        { color: '#10b981', label: 'Correctly classified' },
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

// ── Peek overlay ──────────────────────────────────
let _peeking = false;

function setPeek(on) {
  if (on === _peeking) return;
  if (on && !layerState.parcels) return;
  _peeking = on;
  const vis = on ? 'none' : 'visible';
  if (map.getLayer('parcel-fill')) map.setLayoutProperty('parcel-fill', 'visibility', vis);
  if (map.getLayer('parcel-line')) map.setLayoutProperty('parcel-line', 'visibility', vis);
  const btn = document.getElementById('peek-btn');
  if (btn) btn.classList.toggle('active', on);
}

document.addEventListener('keydown', (e) => {
  if (e.key === 'v' || e.key === 'V') {
    if (e.repeat) return;
    setPeek(true);
  }
});
document.addEventListener('keyup', (e) => {
  if (e.key === 'v' || e.key === 'V') setPeek(false);
});

function updateSliderMute() {
  const container = document.getElementById('slider-container');
  if (!container) return;
  const existing = container.querySelector('.slider-note');
  if (vacancySource === 'pluto') {
    container.classList.add('slider-muted');
    if (!existing) {
      const note = document.createElement('div');
      note.className = 'slider-note';
      note.textContent = 'Threshold does not affect PLUTO-only overlay';
      container.append(note);
    }
  } else {
    container.classList.remove('slider-muted');
    if (existing) existing.remove();
  }
}

function toggleLayer(id, visible) {
  if (id === 'overlay') {
    layerState.overlay = visible;
    map.setLayoutProperty('product-layer', 'visibility', visible ? 'visible' : 'none');
    const sourceCtrl = document.getElementById('vacancy-source-control');
    if (sourceCtrl) sourceCtrl.hidden = !visible;
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
    const legend = document.getElementById('parcel-legend');
    if (legend) legend.hidden = !visible;
    if (!visible && _peeking) setPeek(false);
    updateFooter();
  } else if (id === 'athletic') {
    layerState.athletic = visible;
    const vis = visible ? 'visible' : 'none';
    if (map.getLayer('athletic-fill')) map.setLayoutProperty('athletic-fill', 'visibility', vis);
    if (map.getLayer('athletic-line')) map.setLayoutProperty('athletic-line', 'visibility', vis);
    const fpRow = document.getElementById('athletic-fp-row');
    if (fpRow) fpRow.hidden = !visible;
    const legend = document.getElementById('athletic-legend');
    if (legend) legend.hidden = !visible;
    updateFooter();
  }
}

// ── Threshold change ────────────────────────────────
function onThresholdChange(cp) {
  currentTStr = cp.tStr;
  _prefetched.clear();
  updateTileSource();
  
    const count = updateParcelThreshold(map, cp.tStr);
  if (count !== null) {
    parcelCount = count;
    const val = document.getElementById('parcel-count-value');
    if (val) val.textContent = parcelCount.toLocaleString();
  }
  if (DEV_MODE) {
    const fpCount = updateAthleticThreshold(map, cp.tStr);
    if (fpCount !== null) {
      const val = document.getElementById('athletic-fp-value');
      if (val) val.textContent = fpCount.toLocaleString();
    }
  }
  updateStats();
}

// ── PLUTO tile prefetch ────────────────────────────
const _prefetched = new Set();
let _prefetchDebounce = null;

function prefetchTilesAtZoom(zoom) {
  const bounds = map.getBounds();
  const n = 2 ** zoom;
  const toTileX = lng => Math.floor((lng + 180) / 360 * n);
  const toTileY = lat => {
    const r = lat * Math.PI / 180;
    return Math.floor((1 - Math.log(Math.tan(r) + 1 / Math.cos(r)) / Math.PI) / 2 * n);
  };
  const minX = toTileX(bounds.getWest());
  const maxX = toTileX(bounds.getEast());
  const minY = toTileY(bounds.getNorth());
  const maxY = toTileY(bounds.getSouth());
  for (let x = minX; x <= maxX; x++) {
    for (let y = minY; y <= maxY; y++) {
      const key = `${zoom}/${x}/${y}/${currentTStr}`;
      if (_prefetched.has(key)) continue;
      _prefetched.add(key);
      fetch(`/api/tile/product/${zoom}/${x}/${y}.jpg?t=${currentTStr}&source=${vacancySource}`)
        .catch(() => {});
    }
  }
}

function prefetchPlutoTiles() {
  clearTimeout(_prefetchDebounce);
  _prefetchDebounce = setTimeout(() => {
    const zoom = Math.round(map.getZoom());
    prefetchTilesAtZoom(zoom);
    if (zoom >= 16 && zoom <= 18) {
      prefetchTilesAtZoom(zoom + 1);
    } else if (zoom === 19) {
      prefetchTilesAtZoom(18);
    }
  }, 1000);
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
  prefetchPlutoTiles();
}

// ── Init ────────────────────────────────────────────
buildLayerPanel();
loadThresholds();

map.on('load', () => {
  window._map = map;
  addCDLayer();
  addParcelLayer(map, currentTStr).then(info => {
    if (info) {
      plutoVersion = info.version;
      updateStats();
    }
  });
  if (DEV_MODE) {
    addAthleticLayer(map, currentTStr).then(info => {
      if (info) {
        const val = document.getElementById('athletic-fp-value');
        if (val) val.textContent = info.count.toLocaleString();
        if (info.queryDate) osmDate = info.queryDate;
      }
    });
  }
  onMapMove();
  map.on('moveend', onMapMove);
  prefetchPlutoTiles();
});

async function addCDLayer() {
  let cdStyle;
  try {
    const resp = await fetch('product_treatment.json');
    const treatment = await resp.json();
    cdStyle = treatment.cd;
    applyBasemapTreatment(treatment.basemap);
  } catch (e) { console.warn('product_treatment.json load failed:', e); }

  try {
    await addDistrictLayer(map, {
      style: cdStyle,
      onSelect(boroCD) {
        selectedCD = boroCD;
        updateStats();
        updateFooter();
      },
    });
  } catch (e) { console.error('addDistrictLayer failed:', e); }
}

updateStats();
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
