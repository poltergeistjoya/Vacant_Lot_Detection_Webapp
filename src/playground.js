import { createMap } from './lib/map.js';
import { DEFAULTS } from './lib/layers.js';
import {
  applyBasemapFilter, applyVacantFilter, applyNonVacantFilter,
  applyOutlineChrome, applyGlowChrome, applyShadowChrome,
  applyAllEffects, clearAllEffects, renderAllShapes,
} from './lib/effects.js';
import {
  loadActiveState, saveActiveState, defaultState,
  listSnapshots, saveSnapshot, deleteSnapshot,
  exportAllAsJSON, importFromJSON,
} from './lib/state.js';

const ctl = id => document.getElementById(id);
const val = id => document.getElementById(`val-${id}`);

let state, panes, boundary;
let comparingOriginal = false;
const compareBtn = ctl('compare-btn');

// ── Compare toggle ──────────────────────────────────
function exitCompare() {
  if (!comparingOriginal) return;
  comparingOriginal = false;
  compareBtn.textContent = 'Original';
  compareBtn.classList.remove('compare-active');
}

function setComparing(on) {
  comparingOriginal = on;
  compareBtn.textContent = on ? 'Styled' : 'Original';
  compareBtn.classList.toggle('compare-active', on);
  if (on) {
    clearAllEffects(panes);
  } else {
    applyAllEffects(panes, boundary, state);
  }
}

// ── Effect appliers (exit compare, delegate to lib) ─
function onBasemapFilter() { exitCompare(); applyBasemapFilter(panes, state); saveActiveState(state); }
function onVacantFilter() { exitCompare(); applyVacantFilter(panes, state); saveActiveState(state); }
function onNonVacantFilter() { exitCompare(); applyNonVacantFilter(panes, state); saveActiveState(state); }
function onOutlineChrome() { exitCompare(); applyOutlineChrome(panes, state); saveActiveState(state); }
function onGlowChrome() { exitCompare(); applyGlowChrome(panes, state); saveActiveState(state); }
function onShadowChrome() { exitCompare(); applyShadowChrome(panes, state); saveActiveState(state); }
function onOutlineShape() { exitCompare(); boundary.renderOutline(state); saveActiveState(state); }
function onGlowShape() { exitCompare(); boundary.renderGlow(state); saveActiveState(state); }
function onShadowShape() { exitCompare(); boundary.renderShadow(state); saveActiveState(state); }

// ── Wiring ──────────────────────────────────────────
function bindRange(id, key, { onChange, format = v => v } = {}) {
  const input = ctl(`ctl-${id}`);
  input.addEventListener('input', () => {
    state[key] = parseFloat(input.value);
    val(id).textContent = format(state[key]);
    onChange();
  });
}

function wireControls() {
  // Basemap treatment
  bindRange('basemap-brightness', 'basemapBrightness', { onChange: onBasemapFilter, format: v => v.toFixed(2) });
  bindRange('basemap-contrast', 'basemapContrast', { onChange: onBasemapFilter, format: v => v.toFixed(2) });
  bindRange('basemap-saturation', 'basemapSaturation', { onChange: onBasemapFilter, format: v => v.toFixed(2) });
  bindRange('basemap-hue', 'basemapHue', { onChange: onBasemapFilter, format: v => `${v}°` });
  bindRange('basemap-blur', 'basemapBlur', { onChange: onBasemapFilter, format: v => `${v.toFixed(1)}px` });

  // Vacant treatment
  bindRange('vacant-brightness', 'vacantBrightness', { onChange: onVacantFilter, format: v => v.toFixed(2) });
  bindRange('vacant-contrast', 'vacantContrast', { onChange: onVacantFilter, format: v => v.toFixed(2) });
  bindRange('vacant-saturation', 'vacantSaturation', { onChange: onVacantFilter, format: v => v.toFixed(2) });
  bindRange('vacant-hue', 'vacantHue', { onChange: onVacantFilter, format: v => `${v}°` });
  bindRange('vacant-blur', 'vacantBlur', { onChange: onVacantFilter, format: v => `${v.toFixed(1)}px` });

  // Non-vacant treatment
  bindRange('nonvacant-brightness', 'nonVacantBrightness', { onChange: onNonVacantFilter, format: v => v.toFixed(2) });
  bindRange('nonvacant-contrast', 'nonVacantContrast', { onChange: onNonVacantFilter, format: v => v.toFixed(2) });
  bindRange('nonvacant-saturation', 'nonVacantSaturation', { onChange: onNonVacantFilter, format: v => v.toFixed(2) });
  bindRange('nonvacant-hue', 'nonVacantHue', { onChange: onNonVacantFilter, format: v => `${v}°` });
  bindRange('nonvacant-blur', 'nonVacantBlur', { onChange: onNonVacantFilter, format: v => `${v.toFixed(1)}px` });

  // Boundary — outline
  ctl('ctl-outline-enabled').addEventListener('change', (e) => {
    state.outlineEnabled = e.target.checked;
    onOutlineChrome();
  });
  ctl('ctl-outline-color').addEventListener('input', (e) => {
    state.outlineColor = e.target.value;
    onOutlineShape();
  });
  bindRange('outline-width', 'outlineWidth', { onChange: onOutlineShape, format: v => `${v}px` });
  bindRange('outline-opacity', 'outlineOpacity', { onChange: onOutlineChrome, format: v => v.toFixed(2) });

  // Boundary — glow
  ctl('ctl-glow-enabled').addEventListener('change', (e) => {
    state.glowEnabled = e.target.checked;
    onGlowChrome();
  });
  ctl('ctl-glow-color').addEventListener('input', (e) => {
    state.glowColor = e.target.value;
    onGlowShape();
  });
  bindRange('glow-radius', 'glowRadius', { onChange: onGlowChrome, format: v => `${v}px` });
  bindRange('glow-strength', 'glowStrength', { onChange: onGlowShape, format: v => v.toFixed(2) });
  bindRange('glow-opacity', 'glowOpacity', { onChange: onGlowChrome, format: v => v.toFixed(2) });

  // Boundary — shadow
  ctl('ctl-shadow-enabled').addEventListener('change', (e) => {
    state.shadowEnabled = e.target.checked;
    onShadowChrome();
  });
  bindRange('shadow-radius', 'shadowRadius', { onChange: onShadowChrome, format: v => `${v}px` });
  bindRange('shadow-strength', 'shadowStrength', { onChange: onShadowShape, format: v => v.toFixed(2) });

  // Reset
  ctl('reset-btn').addEventListener('click', () => {
    Object.assign(state, defaultState());
    syncControlsFromState();
    applyAllEffects(panes, boundary, state);
    saveActiveState(state);
    exitCompare();
  });

  // Compare
  compareBtn.addEventListener('click', () => setComparing(!comparingOriginal));
}

// ── Sync UI ← state ─────────────────────────────────
function syncControlsFromState() {
  // Basemap
  ctl('ctl-basemap-brightness').value = state.basemapBrightness;
  val('basemap-brightness').textContent = state.basemapBrightness.toFixed(2);
  ctl('ctl-basemap-contrast').value = state.basemapContrast;
  val('basemap-contrast').textContent = state.basemapContrast.toFixed(2);
  ctl('ctl-basemap-saturation').value = state.basemapSaturation;
  val('basemap-saturation').textContent = state.basemapSaturation.toFixed(2);
  ctl('ctl-basemap-hue').value = state.basemapHue;
  val('basemap-hue').textContent = `${state.basemapHue}°`;
  ctl('ctl-basemap-blur').value = state.basemapBlur;
  val('basemap-blur').textContent = `${state.basemapBlur.toFixed(1)}px`;

  // Vacant
  ctl('ctl-vacant-brightness').value = state.vacantBrightness;
  val('vacant-brightness').textContent = state.vacantBrightness.toFixed(2);
  ctl('ctl-vacant-contrast').value = state.vacantContrast;
  val('vacant-contrast').textContent = state.vacantContrast.toFixed(2);
  ctl('ctl-vacant-saturation').value = state.vacantSaturation;
  val('vacant-saturation').textContent = state.vacantSaturation.toFixed(2);
  ctl('ctl-vacant-hue').value = state.vacantHue;
  val('vacant-hue').textContent = `${state.vacantHue}°`;
  ctl('ctl-vacant-blur').value = state.vacantBlur;
  val('vacant-blur').textContent = `${state.vacantBlur.toFixed(1)}px`;

  // Non-vacant
  ctl('ctl-nonvacant-brightness').value = state.nonVacantBrightness;
  val('nonvacant-brightness').textContent = state.nonVacantBrightness.toFixed(2);
  ctl('ctl-nonvacant-contrast').value = state.nonVacantContrast;
  val('nonvacant-contrast').textContent = state.nonVacantContrast.toFixed(2);
  ctl('ctl-nonvacant-saturation').value = state.nonVacantSaturation;
  val('nonvacant-saturation').textContent = state.nonVacantSaturation.toFixed(2);
  ctl('ctl-nonvacant-hue').value = state.nonVacantHue;
  val('nonvacant-hue').textContent = `${state.nonVacantHue}°`;
  ctl('ctl-nonvacant-blur').value = state.nonVacantBlur;
  val('nonvacant-blur').textContent = `${state.nonVacantBlur.toFixed(1)}px`;

  // Boundary effects
  ctl('ctl-outline-enabled').checked = state.outlineEnabled;
  ctl('ctl-outline-color').value = state.outlineColor;
  ctl('ctl-outline-width').value = state.outlineWidth;
  val('outline-width').textContent = `${state.outlineWidth}px`;
  ctl('ctl-outline-opacity').value = state.outlineOpacity;
  val('outline-opacity').textContent = state.outlineOpacity.toFixed(2);

  ctl('ctl-glow-enabled').checked = state.glowEnabled;
  ctl('ctl-glow-color').value = state.glowColor;
  ctl('ctl-glow-radius').value = state.glowRadius;
  val('glow-radius').textContent = `${state.glowRadius}px`;
  ctl('ctl-glow-strength').value = state.glowStrength;
  val('glow-strength').textContent = state.glowStrength.toFixed(2);
  ctl('ctl-glow-opacity').value = state.glowOpacity;
  val('glow-opacity').textContent = state.glowOpacity.toFixed(2);

  ctl('ctl-shadow-enabled').checked = state.shadowEnabled;
  ctl('ctl-shadow-radius').value = state.shadowRadius;
  val('shadow-radius').textContent = `${state.shadowRadius}px`;
  ctl('ctl-shadow-strength').value = state.shadowStrength;
  val('shadow-strength').textContent = state.shadowStrength.toFixed(2);
}

// ── Snapshots UI ────────────────────────────────────
function renderSnapshotList() {
  const list = ctl('snapshot-list');
  const snapshots = listSnapshots();
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

  // Load on click
  list.querySelectorAll('.snapshot-item').forEach(el => {
    el.addEventListener('click', (e) => {
      if (e.target.classList.contains('snapshot-delete')) return;
      const snap = snapshots.find(s => s.name === el.dataset.name);
      if (snap) {
        Object.assign(state, { ...DEFAULTS, ...snap.state });
        syncControlsFromState();
        applyAllEffects(panes, boundary, state);
        saveActiveState(state);
        exitCompare();
      }
    });
  });

  // Delete
  list.querySelectorAll('.snapshot-delete').forEach(btn => {
    btn.addEventListener('click', (e) => {
      e.stopPropagation();
      deleteSnapshot(btn.dataset.name);
      renderSnapshotList();
    });
  });
}

function wireSnapshots() {
  ctl('snapshot-save-btn').addEventListener('click', () => {
    const nameInput = ctl('snapshot-name');
    const name = nameInput.value.trim();
    if (!name) return;
    saveSnapshot(name, state);
    nameInput.value = '';
    renderSnapshotList();
  });

  ctl('export-btn').addEventListener('click', () => {
    const json = exportAllAsJSON(state);
    const blob = new Blob([json], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `vacancy-settings-${new Date().toISOString().slice(0, 10)}.json`;
    a.click();
    URL.revokeObjectURL(url);
  });

  ctl('import-btn').addEventListener('click', () => {
    ctl('import-file').click();
  });

  ctl('import-file').addEventListener('change', (e) => {
    const file = e.target.files[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = () => {
      const result = importFromJSON(reader.result);
      if (!result) {
        alert('Invalid snapshot file.');
        return;
      }
      Object.assign(state, result.active);
      syncControlsFromState();
      applyAllEffects(panes, boundary, state);
      saveActiveState(state);
      if (result.snapshots.length) {
        for (const s of result.snapshots) {
          saveSnapshot(s.name, s.state);
        }
        renderSnapshotList();
      }
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

  state = loadActiveState();
  syncControlsFromState();
  applyAllEffects(panes, boundary, state);
  wireControls();
  wireSnapshots();
}

init();
