import { createMap } from './lib/map.js';
import { addDistrictLayer } from './lib/districts.js';
import {
  TREATMENT_DEFAULTS, VACANT_EXTRA_DEFAULTS, BOUNDARY_DEFAULTS,
  CD_STYLE_DEFAULTS,
} from './lib/layers.js';
import {
  loadActiveState, saveActiveState,
  listSnapshots, saveSnapshot, deleteSnapshot,
  exportAllAsJSON, importFromJSON,
} from './lib/state.js';

const ctl = id => document.getElementById(id);
const val = id => document.getElementById(`val-${id}`);

let state, mapCtl, districtCtl;
let comparingOriginal = false;
let debounceTimer = null;

// ── State shape ─────────────────────────────────────
function buildDefaultState() {
  return {
    bm: { ...TREATMENT_DEFAULTS },
    vc: { ...TREATMENT_DEFAULTS, ...VACANT_EXTRA_DEFAULTS },
    nv: { ...TREATMENT_DEFAULTS },
    boundary: { ...BOUNDARY_DEFAULTS },
    cd: { ...CD_STYLE_DEFAULTS, enabled: true },
  };
}

// ── Tile URL update (debounced) ─────────────────────
function updateProductTiles() {
  clearTimeout(debounceTimer);
  debounceTimer = setTimeout(() => {
    mapCtl.setTreatmentParams(state.bm, state.vc, state.nv);
    saveActiveState(state);
  }, 200);
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
    mapCtl.clearTreatments();
    mapCtl.hideBoundaryEffects();
  } else {
    updateProductTiles();
    applyBoundaryEffects();
  }
}

// ── Boundary effects ────────────────────────────────
function applyBoundaryEffects() {
  const b = state.boundary;

  mapCtl.boundary.renderOutline({ outlineColor: b.outlineColor, outlineWidth: b.outlineWidth });
  mapCtl.updateBoundaryImage('outline', mapCtl.boundary.outlineCanvas,
    b.outlineEnabled ? b.outlineOpacity : 0);

  mapCtl.boundary.renderGlow({ glowColor: b.bloomColor, glowStrength: b.bloomIntensity });
  mapCtl.updateBoundaryImage('glow', mapCtl.boundary.glowCanvas,
    b.bloomEnabled ? b.bloomIntensity : 0, b.bloomRadius);

  mapCtl.boundary.renderShadow({ shadowStrength: b.shadowStrength });
  mapCtl.updateBoundaryImage('shadow', mapCtl.boundary.shadowCanvas,
    b.shadowEnabled ? 1 : 0, b.shadowRadius);

  saveActiveState(state);
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
  for (const c of COMMON_CONTROLS) {
    bindRange(`ctl-bm-${c.suffix}`, 'bm', c.key, { onChange: updateProductTiles, format: c.format });
  }

  for (const c of COMMON_CONTROLS) {
    bindRange(`ctl-vc-${c.suffix}`, 'vc', c.key, { onChange: updateProductTiles, format: c.format });
  }
  ctl('ctl-vc-tint')?.addEventListener('input', (e) => {
    exitCompare();
    state.vc.tint = e.target.value.replace('#', '');
    updateProductTiles();
  });
  bindRange('ctl-vc-to', 'vc', 'to', { onChange: updateProductTiles, format: v => v.toFixed(2) });

  for (const c of COMMON_CONTROLS) {
    bindRange(`ctl-nv-${c.suffix}`, 'nv', c.key, { onChange: updateProductTiles, format: c.format });
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

  // Reset
  ctl('reset-btn').addEventListener('click', () => {
    Object.assign(state, buildDefaultState());
    syncControlsFromState();
    updateProductTiles();
    applyBoundaryEffects();
    exitCompare();
  });

  // Compare
  ctl('compare-btn').addEventListener('click', () => setComparing(!comparingOriginal));

  // Community Districts
  ctl('ctl-cd-enabled')?.addEventListener('change', (e) => {
    state.cd.enabled = e.target.checked;
    updateCDVisibility();
    saveActiveState(state);
  });
  ctl('ctl-cd-fill-color')?.addEventListener('input', (e) => {
    state.cd.fillColor = e.target.value;
    updateCDStyle();
  });
  bindCDRange('ctl-cd-fill-opacity', 'fillOpacity', v => v.toFixed(2));
  ctl('ctl-cd-stroke-color')?.addEventListener('input', (e) => {
    state.cd.strokeColor = e.target.value;
    updateCDStyle();
  });
  bindCDRange('ctl-cd-stroke-width', 'strokeWidth', v => `${v}px`);
  bindCDRange('ctl-cd-stroke-opacity', 'strokeOpacity', v => v.toFixed(2));
  bindCDRange('ctl-cd-hover-fill', 'hoverFillOpacity', v => v.toFixed(2));
  bindCDRange('ctl-cd-hover-stroke-w', 'hoverStrokeWidth', v => `${v}px`);
  bindCDRange('ctl-cd-hover-stroke-o', 'hoverStrokeOpacity', v => v.toFixed(2));
}

function bindCDRange(ctlId, key, format) {
  const input = ctl(ctlId);
  if (!input) return;
  input.addEventListener('input', () => {
    state.cd[key] = parseFloat(input.value);
    const valEl = val(ctlId.replace('ctl-', ''));
    if (valEl) valEl.textContent = format(state.cd[key]);
    updateCDStyle();
  });
}

function updateCDStyle() {
  if (districtCtl) {
    districtCtl.updateStyle(state.cd);
    saveActiveState(state);
  }
}

function updateCDVisibility() {
  const map = mapCtl.map;
  const vis = state.cd.enabled ? 'visible' : 'none';
  if (map.getLayer('cd-fill')) map.setLayoutProperty('cd-fill', 'visibility', vis);
  if (map.getLayer('cd-line')) map.setLayoutProperty('cd-line', 'visibility', vis);
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

  const tintInput = ctl('ctl-vc-tint');
  if (tintInput) tintInput.value = '#' + (state.vc.tint || '000000');
  const toInput = ctl('ctl-vc-to');
  if (toInput) toInput.value = state.vc.to;
  const toVal = val('vc-to');
  if (toVal) toVal.textContent = (state.vc.to || 0).toFixed(2);

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

  // CD controls
  const cd = state.cd;
  const setCDVal = (id, v) => { const el = ctl(id); if (el) el.value = v; };
  const setCDTxt = (id, t) => { const el = val(id); if (el) el.textContent = t; };
  if (ctl('ctl-cd-enabled')) ctl('ctl-cd-enabled').checked = cd.enabled;
  setCDVal('ctl-cd-fill-color', cd.fillColor);
  setCDVal('ctl-cd-fill-opacity', cd.fillOpacity);
  setCDTxt('cd-fill-opacity', cd.fillOpacity.toFixed(2));
  setCDVal('ctl-cd-stroke-color', cd.strokeColor);
  setCDVal('ctl-cd-stroke-width', cd.strokeWidth);
  setCDTxt('cd-stroke-width', `${cd.strokeWidth}px`);
  setCDVal('ctl-cd-stroke-opacity', cd.strokeOpacity);
  setCDTxt('cd-stroke-opacity', cd.strokeOpacity.toFixed(2));
  setCDVal('ctl-cd-hover-fill', cd.hoverFillOpacity);
  setCDTxt('cd-hover-fill', cd.hoverFillOpacity.toFixed(2));
  setCDVal('ctl-cd-hover-stroke-w', cd.hoverStrokeWidth);
  setCDTxt('cd-hover-stroke-w', `${cd.hoverStrokeWidth}px`);
  setCDVal('ctl-cd-hover-stroke-o', cd.hoverStrokeOpacity);
  setCDTxt('cd-hover-stroke-o', cd.hoverStrokeOpacity.toFixed(2));
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
      Object.assign(state.bm, { ...TREATMENT_DEFAULTS, ...(p.basemap || {}) });
      Object.assign(state.vc, { ...TREATMENT_DEFAULTS, ...VACANT_EXTRA_DEFAULTS, ...(p.vacant || {}) });
      Object.assign(state.nv, { ...TREATMENT_DEFAULTS, ...(p.nonvacant || {}) });
      syncControlsFromState();
      updateProductTiles();
      exitCompare();
      select.value = '';
    });
  } catch {
    // Backend not running
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
        updateProductTiles();
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
      updateProductTiles();
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
  mapCtl = await createMap('map');

  const saved = await loadActiveState();
  state = buildDefaultState();
  if (saved && saved.bm) {
    Object.assign(state.bm, saved.bm);
    Object.assign(state.vc, saved.vc);
    Object.assign(state.nv, saved.nv);
    if (saved.boundary) Object.assign(state.boundary, saved.boundary);
    if (saved.cd) Object.assign(state.cd, saved.cd);
  }

  syncControlsFromState();
  updateProductTiles();
  applyBoundaryEffects();
  wireControls();
  wireSnapshots();
  loadPresets();

  // Load CD layer
  districtCtl = await addDistrictLayer(mapCtl.map, {
    style: state.cd,
    onSelect(boroCD) {
      console.log('Playground: selected CD', boroCD);
    },
  });
  updateCDVisibility();
}

init();
