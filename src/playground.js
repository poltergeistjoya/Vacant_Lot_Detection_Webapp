import { createMap } from './lib/map.js';
import {
  TREATMENT_DEFAULTS, VACANT_EXTRA_DEFAULTS, BOUNDARY_DEFAULTS,
} from './lib/layers.js';
import { DistrictLayer, DISTRICT_DEFAULTS } from './lib/districts.js';
import {
  loadActiveState, saveActiveState,
  listSnapshots, saveSnapshot, deleteSnapshot,
  exportAllAsJSON, importFromJSON,
} from './lib/state.js';

const ctl = id => document.getElementById(id);
const val = id => document.getElementById(`val-${id}`);

let state, panes, boundary, mapCtl, districtLayer;
let comparingOriginal = false;
let debounceTimers = {};

// ── State shape ─────────────────────────────────────
// state.bm = { sc, sb, g, gr, gg, gb, sat, gray, br }
// state.vc = { sc, sb, g, gr, gg, gb, sat, gray, br, tint, to }
// state.nv = { sc, sb, g, gr, gg, gb, sat, gray, br }
// state.boundary = { outlineEnabled, outlineColor, ... bloomEnabled, ... shadowEnabled, ... }

function buildDefaultState() {
  return {
    bm: { ...TREATMENT_DEFAULTS },
    vc: { ...TREATMENT_DEFAULTS, ...VACANT_EXTRA_DEFAULTS },
    nv: { ...TREATMENT_DEFAULTS },
    boundary: { ...BOUNDARY_DEFAULTS },
    district: { ...DISTRICT_DEFAULTS },
  };
}

// ── Tile URL update (debounced) ─────────────────────
function updateBasemapTiles() {
  clearTimeout(debounceTimers.bm);
  debounceTimers.bm = setTimeout(() => {
    mapCtl.setBasemapUrl(prefixParams('bm_', state.bm));
    saveActiveState(state);
  }, 200);
}

function updateVacantTiles() {
  clearTimeout(debounceTimers.vc);
  debounceTimers.vc = setTimeout(() => {
    mapCtl.setVacantUrl(state.vc);
    saveActiveState(state);
  }, 200);
}

function updateNonVacantTiles() {
  clearTimeout(debounceTimers.nv);
  debounceTimers.nv = setTimeout(() => {
    mapCtl.setNonVacantUrl(state.nv);
    saveActiveState(state);
  }, 200);
}

/** Prefix keys for the combined basemap endpoint */
function prefixParams(prefix, params) {
  const out = {};
  for (const [k, v] of Object.entries(params)) {
    out[prefix + k] = v;
  }
  return out;
}

// ── Compare ─────────────────────────────────────────
function exitCompare() {
  if (!comparingOriginal) return;
  comparingOriginal = false;
  ctl('compare-btn').textContent = 'Original';
  ctl('compare-btn').classList.remove('compare-active');
}

function setComparing(on) {
  comparingOriginal = on;
  const btn = ctl('compare-btn');
  btn.textContent = on ? 'Styled' : 'Original';
  btn.classList.toggle('compare-active', on);
  if (on) {
    // Reset all tile layers to plain Esri
    mapCtl.setBasemapUrl({});
    mapCtl.setVacantUrl({});
    mapCtl.setNonVacantUrl({});
    // Hide boundary effects
    panes.outlinePane.style.opacity = 0;
    panes.glowPane.style.opacity = 0;
    panes.shadowPane.style.opacity = 0;
  } else {
    // Restore
    updateBasemapTiles();
    updateVacantTiles();
    updateNonVacantTiles();
    applyBoundaryEffects();
  }
}

// ── Boundary effects (still CSS/canvas, not backend) ─
function applyBoundaryEffects() {
  const b = state.boundary;
  // Outline
  panes.outlinePane.style.opacity = b.outlineEnabled ? b.outlineOpacity : 0;
  boundary.renderOutline({ outlineColor: b.outlineColor, outlineWidth: b.outlineWidth });

  // Bloom (uses glow pane with CSS blur)
  panes.glowPane.style.opacity = b.bloomEnabled ? b.bloomIntensity : 0;
  panes.glowPane.style.filter = `blur(${b.bloomRadius}px)`;
  boundary.renderGlow({ glowColor: b.bloomColor, glowStrength: b.bloomIntensity });

  // Shadow
  panes.shadowPane.style.opacity = b.shadowEnabled ? 1 : 0;
  panes.shadowPane.style.filter = `blur(${b.shadowRadius}px)`;
  boundary.renderShadow({ shadowStrength: b.shadowStrength });

  saveActiveState(state);
}

// ── District update ─────────────────────────────────
function updateDistricts() {
  if (districtLayer) {
    districtLayer.update(state.district);
    saveActiveState(state);
  }
}

function bindDistrictRange(ctlId, key, format) {
  const input = ctl(ctlId);
  if (!input) return;
  input.addEventListener('input', () => {
    state.district[key] = parseFloat(input.value);
    const valEl = val(ctlId.replace('ctl-', ''));
    if (valEl) valEl.textContent = format(state.district[key]);
    updateDistricts();
  });
}

// ── Wiring ──────────────────────────────────────────
function bindRange(ctlId, group, key, { onChange, format = v => v } = {}) {
  const input = ctl(ctlId);
  if (!input) return;
  input.addEventListener('input', () => {
    exitCompare();
    state[group][key] = parseFloat(input.value);
    const valEl = val(ctlId.replace('ctl-', ''));
    if (valEl) valEl.textContent = format(state[group][key]);
    onChange();
  });
}

function bindBoundaryRange(ctlId, key, { onChange, format = v => v } = {}) {
  const input = ctl(ctlId);
  if (!input) return;
  input.addEventListener('input', () => {
    exitCompare();
    state.boundary[key] = parseFloat(input.value);
    const valEl = val(ctlId.replace('ctl-', ''));
    if (valEl) valEl.textContent = format(state.boundary[key]);
    onChange();
  });
}

const COMMON_CONTROLS = [
  { suffix: 'gray', key: 'gray', format: v => v.toFixed(2) },
  { suffix: 'br',   key: 'br',  format: v => v.toFixed(2) },
  { suffix: 'sc',   key: 'sc',  format: v => v.toFixed(1) },
  { suffix: 'sb',   key: 'sb',  format: v => v.toFixed(2) },
  { suffix: 'sat',  key: 'sat', format: v => v.toFixed(2) },
  { suffix: 'g',    key: 'g',   format: v => v.toFixed(2) },
  { suffix: 'gr',   key: 'gr',  format: v => v.toFixed(2) },
  { suffix: 'gg',   key: 'gg',  format: v => v.toFixed(2) },
  { suffix: 'gb',   key: 'gb',  format: v => v.toFixed(2) },
];

function wireControls() {
  // Basemap controls
  for (const c of COMMON_CONTROLS) {
    bindRange(`ctl-bm-${c.suffix}`, 'bm', c.key, { onChange: updateBasemapTiles, format: c.format });
  }

  // Vacant controls
  for (const c of COMMON_CONTROLS) {
    bindRange(`ctl-vc-${c.suffix}`, 'vc', c.key, { onChange: updateVacantTiles, format: c.format });
  }
  // Vacant tint
  ctl('ctl-vc-tint')?.addEventListener('input', (e) => {
    exitCompare();
    state.vc.tint = e.target.value.replace('#', '');
    updateVacantTiles();
  });
  bindRange('ctl-vc-to', 'vc', 'to', { onChange: updateVacantTiles, format: v => v.toFixed(2) });

  // Non-vacant controls
  for (const c of COMMON_CONTROLS) {
    bindRange(`ctl-nv-${c.suffix}`, 'nv', c.key, { onChange: updateNonVacantTiles, format: c.format });
  }

  // Boundary — outline
  ctl('ctl-outline-enabled')?.addEventListener('change', (e) => {
    exitCompare();
    state.boundary.outlineEnabled = e.target.checked;
    applyBoundaryEffects();
  });
  ctl('ctl-outline-color')?.addEventListener('input', (e) => {
    exitCompare();
    state.boundary.outlineColor = e.target.value;
    applyBoundaryEffects();
  });
  bindBoundaryRange('ctl-outline-width', 'outlineWidth', { onChange: applyBoundaryEffects, format: v => `${v}px` });
  bindBoundaryRange('ctl-outline-opacity', 'outlineOpacity', { onChange: applyBoundaryEffects, format: v => v.toFixed(2) });

  // Boundary — bloom
  ctl('ctl-bloom-enabled')?.addEventListener('change', (e) => {
    exitCompare();
    state.boundary.bloomEnabled = e.target.checked;
    applyBoundaryEffects();
  });
  ctl('ctl-bloom-color')?.addEventListener('input', (e) => {
    exitCompare();
    state.boundary.bloomColor = e.target.value;
    applyBoundaryEffects();
  });
  bindBoundaryRange('ctl-bloom-radius', 'bloomRadius', { onChange: applyBoundaryEffects, format: v => `${v}px` });
  bindBoundaryRange('ctl-bloom-intensity', 'bloomIntensity', { onChange: applyBoundaryEffects, format: v => v.toFixed(2) });

  // Boundary — shadow
  ctl('ctl-shadow-enabled')?.addEventListener('change', (e) => {
    exitCompare();
    state.boundary.shadowEnabled = e.target.checked;
    applyBoundaryEffects();
  });
  bindBoundaryRange('ctl-shadow-radius', 'shadowRadius', { onChange: applyBoundaryEffects, format: v => `${v}px` });
  bindBoundaryRange('ctl-shadow-strength', 'shadowStrength', { onChange: applyBoundaryEffects, format: v => v.toFixed(2) });

  // District controls
  ctl('ctl-cd-fill-color')?.addEventListener('input', (e) => {
    state.district.fillColor = e.target.value;
    updateDistricts();
  });
  bindDistrictRange('ctl-cd-fill-opacity', 'fillOpacity', v => v.toFixed(2));
  ctl('ctl-cd-stroke-color')?.addEventListener('input', (e) => {
    state.district.strokeColor = e.target.value;
    updateDistricts();
  });
  bindDistrictRange('ctl-cd-stroke-width', 'strokeWidth', v => `${v}px`);
  bindDistrictRange('ctl-cd-stroke-opacity', 'strokeOpacity', v => v.toFixed(2));
  bindDistrictRange('ctl-cd-hover-fill', 'hoverFillOpacity', v => v.toFixed(2));
  bindDistrictRange('ctl-cd-hover-stroke-w', 'hoverStrokeWidth', v => `${v}px`);
  bindDistrictRange('ctl-cd-hover-stroke-o', 'hoverStrokeOpacity', v => v.toFixed(2));
  bindDistrictRange('ctl-cd-hover-sat', 'hoverSaturate', v => `${v.toFixed(1)}x`);
  ctl('ctl-cd-scale-enabled')?.addEventListener('change', (e) => {
    state.district.hoverScaleEnabled = e.target.checked;
    updateDistricts();
  });
  bindDistrictRange('ctl-cd-scale-amount', 'hoverScale', v => `${v.toFixed(3)}x`);
  ctl('ctl-cd-label-enabled')?.addEventListener('change', (e) => {
    state.district.hoverLabelEnabled = e.target.checked;
    updateDistricts();
  });

  // Reset
  ctl('reset-btn').addEventListener('click', () => {
    Object.assign(state, buildDefaultState());
    syncControlsFromState();
    updateBasemapTiles();
    updateVacantTiles();
    updateNonVacantTiles();
    applyBoundaryEffects();
    updateDistricts();
    exitCompare();
  });

  // Compare
  ctl('compare-btn').addEventListener('click', () => setComparing(!comparingOriginal));
}

// ── Sync UI ← state ─────────────────────────────────
function syncGroup(prefix, group) {
  for (const c of COMMON_CONTROLS) {
    const input = ctl(`ctl-${prefix}-${c.suffix}`);
    if (input) input.value = group[c.key];
    const valEl = val(`${prefix}-${c.suffix}`);
    if (valEl) valEl.textContent = c.format(group[c.key]);
  }
}

function syncControlsFromState() {
  syncGroup('bm', state.bm);
  syncGroup('vc', state.vc);
  syncGroup('nv', state.nv);

  // Vacant tint
  const tintInput = ctl('ctl-vc-tint');
  if (tintInput) tintInput.value = '#' + (state.vc.tint || '000000');
  const toInput = ctl('ctl-vc-to');
  if (toInput) toInput.value = state.vc.to;
  const toVal = val('vc-to');
  if (toVal) toVal.textContent = (state.vc.to || 0).toFixed(2);

  // Boundary
  const b = state.boundary;
  ctl('ctl-outline-enabled').checked = b.outlineEnabled;
  ctl('ctl-outline-color').value = b.outlineColor;
  ctl('ctl-outline-width').value = b.outlineWidth;
  val('outline-width').textContent = `${b.outlineWidth}px`;
  ctl('ctl-outline-opacity').value = b.outlineOpacity;
  val('outline-opacity').textContent = b.outlineOpacity.toFixed(2);

  ctl('ctl-bloom-enabled').checked = b.bloomEnabled;
  ctl('ctl-bloom-color').value = b.bloomColor;
  ctl('ctl-bloom-radius').value = b.bloomRadius;
  val('bloom-radius').textContent = `${b.bloomRadius}px`;
  ctl('ctl-bloom-intensity').value = b.bloomIntensity;
  val('bloom-intensity').textContent = b.bloomIntensity.toFixed(2);

  ctl('ctl-shadow-enabled').checked = b.shadowEnabled;
  ctl('ctl-shadow-radius').value = b.shadowRadius;
  val('shadow-radius').textContent = `${b.shadowRadius}px`;
  ctl('ctl-shadow-strength').value = b.shadowStrength;
  val('shadow-strength').textContent = b.shadowStrength.toFixed(2);

  // District
  const d = state.district;
  const setVal = (id, v) => { const el = ctl(id); if (el) el.value = v; };
  const setTxt = (id, t) => { const el = val(id); if (el) el.textContent = t; };
  setVal('ctl-cd-fill-color', d.fillColor);
  setVal('ctl-cd-fill-opacity', d.fillOpacity);
  setTxt('cd-fill-opacity', d.fillOpacity.toFixed(2));
  setVal('ctl-cd-stroke-color', d.strokeColor);
  setVal('ctl-cd-stroke-width', d.strokeWidth);
  setTxt('cd-stroke-width', `${d.strokeWidth}px`);
  setVal('ctl-cd-stroke-opacity', d.strokeOpacity);
  setTxt('cd-stroke-opacity', d.strokeOpacity.toFixed(2));
  setVal('ctl-cd-hover-fill', d.hoverFillOpacity);
  setTxt('cd-hover-fill', d.hoverFillOpacity.toFixed(2));
  setVal('ctl-cd-hover-stroke-w', d.hoverStrokeWidth);
  setTxt('cd-hover-stroke-w', `${d.hoverStrokeWidth}px`);
  setVal('ctl-cd-hover-stroke-o', d.hoverStrokeOpacity);
  setTxt('cd-hover-stroke-o', d.hoverStrokeOpacity.toFixed(2));
  setVal('ctl-cd-hover-sat', d.hoverSaturate);
  setTxt('cd-hover-sat', `${d.hoverSaturate.toFixed(1)}x`);
  ctl('ctl-cd-scale-enabled').checked = d.hoverScaleEnabled;
  setVal('ctl-cd-scale-amount', d.hoverScale);
  setTxt('cd-scale-amount', `${d.hoverScale.toFixed(3)}x`);
  ctl('ctl-cd-label-enabled').checked = d.hoverLabelEnabled;
}

// ── Presets ──────────────────────────────────────────
async function loadPresets() {
  try {
    const resp = await fetch('/api/presets');
    if (!resp.ok) return;
    const presets = await resp.json();
    const select = ctl('preset-select');
    for (const [key, preset] of Object.entries(presets)) {
      const opt = document.createElement('option');
      opt.value = key;
      opt.textContent = preset.label;
      select.appendChild(opt);
    }
    select.addEventListener('change', () => {
      const key = select.value;
      if (!key || !presets[key]) return;
      const p = presets[key];
      // Merge preset values into state
      Object.assign(state.bm, { ...TREATMENT_DEFAULTS, ...(p.basemap || {}) });
      Object.assign(state.vc, { ...TREATMENT_DEFAULTS, ...VACANT_EXTRA_DEFAULTS, ...(p.vacant || {}) });
      Object.assign(state.nv, { ...TREATMENT_DEFAULTS, ...(p.nonvacant || {}) });
      syncControlsFromState();
      updateBasemapTiles();
      updateVacantTiles();
      updateNonVacantTiles();
      exitCompare();
      select.value = '';
    });
  } catch {
    // Backend not running — presets unavailable
  }
}

// ── Snapshots UI ────────────────────────────────────
async function renderSnapshotList() {
  const list = ctl('snapshot-list');
  const snapshots = await listSnapshots();
  if (snapshots.length === 0) {
    list.innerHTML = '<div class="text-muted" style="font-size:11px;padding:4px 0;">No saved snapshots</div>';
    return;
  }
  list.innerHTML = snapshots.map(s => `
    <div class="snapshot-item" data-name="${s.name}">
      <span class="snapshot-name">${s.name}</span>
      <button class="btn btn-danger btn-sm snapshot-delete" data-name="${s.name}">&times;</button>
    </div>
  `).join('');

  list.querySelectorAll('.snapshot-item').forEach(el => {
    el.addEventListener('click', (e) => {
      if (e.target.classList.contains('snapshot-delete')) return;
      const snap = snapshots.find(s => s.name === el.dataset.name);
      if (snap) {
        Object.assign(state, buildDefaultState(), snap.state);
        syncControlsFromState();
        updateBasemapTiles();
        updateVacantTiles();
        updateNonVacantTiles();
        applyBoundaryEffects();
        exitCompare();
      }
    });
  });

  list.querySelectorAll('.snapshot-delete').forEach(btn => {
    btn.addEventListener('click', async (e) => {
      e.stopPropagation();
      await deleteSnapshot(btn.dataset.name);
      renderSnapshotList();
    });
  });
}

function wireSnapshots() {
  ctl('snapshot-save-btn').addEventListener('click', async () => {
    const nameInput = ctl('snapshot-name');
    const name = nameInput.value.trim();
    if (!name) return;
    await saveSnapshot(name, state);
    nameInput.value = '';
    renderSnapshotList();
  });

  ctl('export-btn').addEventListener('click', async () => {
    const json = await exportAllAsJSON(state);
    const blob = new Blob([json], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `vacancy-settings-${new Date().toISOString().slice(0, 10)}.json`;
    a.click();
    URL.revokeObjectURL(url);
  });

  ctl('import-btn').addEventListener('click', () => ctl('import-file').click());

  ctl('import-file').addEventListener('change', (e) => {
    const file = e.target.files[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = async () => {
      const result = await importFromJSON(reader.result);
      if (!result) { alert('Invalid snapshot file.'); return; }
      Object.assign(state, buildDefaultState(), result.active);
      syncControlsFromState();
      updateBasemapTiles();
      updateVacantTiles();
      updateNonVacantTiles();
      applyBoundaryEffects();
      if (result.snapshots.length) renderSnapshotList();
      exitCompare();
    };
    reader.readAsText(file);
    e.target.value = '';
  });

  renderSnapshotList();
}

// ── Init ────────────────────────────────────────────
async function init() {
  const result = await createMap('map');
  panes = result.panes;
  boundary = result.boundary;
  mapCtl = result;

  // Load state or defaults
  const saved = await loadActiveState();
  state = buildDefaultState();
  if (saved && saved.bm) {
    Object.assign(state.bm, saved.bm);
    Object.assign(state.vc, saved.vc);
    Object.assign(state.nv, saved.nv);
    if (saved.boundary) Object.assign(state.boundary, saved.boundary);
    if (saved.district) Object.assign(state.district, saved.district);
  }

  syncControlsFromState();
  updateBasemapTiles();
  updateVacantTiles();
  updateNonVacantTiles();
  applyBoundaryEffects();
  wireControls();
  wireSnapshots();
  loadPresets();

  // Load district boundaries
  districtLayer = new DistrictLayer(mapCtl.map, state.district);
  districtLayer.load('community_districts.geojson');
}

init();
