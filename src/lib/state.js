import {
  TREATMENT_DEFAULTS, VACANT_EXTRA_DEFAULTS, BOUNDARY_DEFAULTS,
} from './layers.js';

const STORAGE_KEY = 'vacancy-playground-snapshot';
const SNAPSHOTS_KEY = 'vacancy-playground-snapshots';

/** Returns a fresh copy of defaults. */
export function defaultState() {
  return {
    bm: { ...TREATMENT_DEFAULTS },
    vc: { ...TREATMENT_DEFAULTS, ...VACANT_EXTRA_DEFAULTS },
    nv: { ...TREATMENT_DEFAULTS },
    boundary: { ...BOUNDARY_DEFAULTS },
  };
}

/** Load the active snapshot from localStorage, or null. */
export function loadActiveState() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (raw) return JSON.parse(raw);
  } catch { /* corrupt */ }
  return null;
}

/** Persist the active state to localStorage. */
export function saveActiveState(state) {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
}

/** List saved named snapshots: [{name, state, timestamp}] */
export function listSnapshots() {
  try {
    const raw = localStorage.getItem(SNAPSHOTS_KEY);
    return raw ? JSON.parse(raw) : [];
  } catch { return []; }
}

/** Save a named snapshot. */
export function saveSnapshot(name, state) {
  const list = listSnapshots();
  const entry = { name, state: JSON.parse(JSON.stringify(state)), timestamp: Date.now() };
  const idx = list.findIndex(s => s.name === name);
  if (idx >= 0) list[idx] = entry;
  else list.push(entry);
  localStorage.setItem(SNAPSHOTS_KEY, JSON.stringify(list));
}

/** Delete a named snapshot. */
export function deleteSnapshot(name) {
  const list = listSnapshots().filter(s => s.name !== name);
  localStorage.setItem(SNAPSHOTS_KEY, JSON.stringify(list));
}

/** Export all snapshots + active state as a JSON string. */
export function exportAllAsJSON(activeState) {
  return JSON.stringify({
    active: activeState,
    snapshots: listSnapshots(),
    exportedAt: new Date().toISOString(),
  }, null, 2);
}

/** Import from a JSON string. Returns {active, snapshots} or null. */
export function importFromJSON(jsonStr) {
  try {
    const data = JSON.parse(jsonStr);
    if (!data.active || !data.active.bm) return null;
    return {
      active: data.active,
      snapshots: Array.isArray(data.snapshots) ? data.snapshots : [],
    };
  } catch { return null; }
}
