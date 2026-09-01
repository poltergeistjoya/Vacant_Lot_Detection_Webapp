// Playground state persistence — backed by a JSON file on disk
// (data/playground_snapshots.json) via the FastAPI backend, so snapshots
// survive clearing browser data and are portable across browsers on this
// machine. See server/app.py's /api/snapshots endpoints.

const API_BASE = '/api/snapshots';

/** Load the active working state from disk, or null. */
export async function loadActiveState() {
  try {
    const resp = await fetch(API_BASE);
    if (!resp.ok) return null;
    const data = await resp.json();
    return data.active || null;
  } catch {
    return null;
  }
}

/** Persist the active working state to disk. Fire-and-forget. */
export function saveActiveState(state) {
  return fetch(`${API_BASE}/active`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(state),
  }).catch(() => { /* backend may be down; state stays in memory */ });
}

/** List saved named snapshots: [{name, state, timestamp}] */
export async function listSnapshots() {
  try {
    const resp = await fetch(API_BASE);
    if (!resp.ok) return [];
    const data = await resp.json();
    return data.snapshots || [];
  } catch {
    return [];
  }
}

/** Save (or overwrite, by name) a named snapshot. */
export function saveSnapshot(name, state) {
  return fetch(API_BASE, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name, state }),
  });
}

/** Delete a named snapshot. */
export function deleteSnapshot(name) {
  return fetch(`${API_BASE}/${encodeURIComponent(name)}`, { method: 'DELETE' });
}

/** Export all snapshots + active state as a JSON string. */
export async function exportAllAsJSON(activeState) {
  return JSON.stringify({
    active: activeState,
    snapshots: await listSnapshots(),
    exportedAt: new Date().toISOString(),
  }, null, 2);
}

/** Import from a JSON string, pushing snapshots to disk. Returns {active, snapshots} or null. */
export async function importFromJSON(jsonStr) {
  try {
    const data = JSON.parse(jsonStr);
    if (!data.active || !data.active.bm) return null;
    const snapshots = Array.isArray(data.snapshots) ? data.snapshots : [];
    for (const s of snapshots) {
      await saveSnapshot(s.name, s.state);
    }
    return { active: data.active, snapshots };
  } catch {
    return null;
  }
}
