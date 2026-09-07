import { CHECKPOINTS, GOOD_ZONE, DEFAULT_THRESHOLD } from './lib/layers.js';

let thresholdsData = null;
let onChangeCb = null;
let debounceTimer = null;

export function getDefaultIndex() {
  return CHECKPOINTS.findIndex(c => c.t === DEFAULT_THRESHOLD);
}

export function initSlider(container, onChange) {
  onChangeCb = onChange;
  const defaultIdx = getDefaultIndex();
  container.innerHTML = `
    <label class="slider-label">Confidence Threshold</label>
    <div class="slider-wrap">
      <div class="good-zone-bar" id="good-zone-bar"></div>
      <input type="range" id="threshold-slider" min="0" max="${CHECKPOINTS.length - 1}" step="1" value="${defaultIdx}">
    </div>
    <div class="threshold-value" id="t-display">${DEFAULT_THRESHOLD.toFixed(3)}</div>
    <div class="metrics" id="metrics"></div>
  `;
  positionGoodZone();
  const slider = document.getElementById('threshold-slider');
  slider.addEventListener('input', () => {
    const idx = parseInt(slider.value, 10);
    const cp = CHECKPOINTS[idx];
    document.getElementById('t-display').textContent = cp.t.toFixed(3);
    updateMetrics(idx);
    clearTimeout(debounceTimer);
    debounceTimer = setTimeout(() => { if (onChangeCb) onChangeCb(cp); }, 150);
  });
}

function positionGoodZone() {
  const bar = document.getElementById('good-zone-bar');
  const startIdx = CHECKPOINTS.findIndex(c => c.t >= GOOD_ZONE[0]);
  const endIdx = CHECKPOINTS.findIndex(c => c.t >= GOOD_ZONE[1]);
  const total = CHECKPOINTS.length - 1;
  bar.style.left = `${(startIdx / total) * 100}%`;
  bar.style.width = `${((endIdx - startIdx) / total) * 100}%`;
}

export function setThresholdsData(data) {
  thresholdsData = data;
  updateMetrics(getDefaultIndex());
}

function updateMetrics(idx) {
  const el = document.getElementById('metrics');
  if (!thresholdsData) { el.textContent = 'Loading metrics\u2026'; return; }
  const cp = thresholdsData.checkpoints[idx];
  if (!cp) return;
  const m = cp.test;
  el.innerHTML = `
    <div class="metric"><span class="metric-label">Precision</span><span class="metric-value">${(m.precision * 100).toFixed(1)}%</span></div>
    <div class="metric"><span class="metric-label">Recall</span><span class="metric-value">${(m.recall * 100).toFixed(1)}%</span></div>
    <div class="metric"><span class="metric-label">F1</span><span class="metric-value">${(m.f1 * 100).toFixed(1)}%</span></div>
    <div class="metric"><span class="metric-label">F2</span><span class="metric-value">${(m.f2 * 100).toFixed(1)}%</span></div>
  `;
}
