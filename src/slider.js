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
    <div style="display:flex;align-items:center;gap:6px">
      <label class="slider-label" style="margin-bottom:0">Confidence Threshold</label>
      <span class="tooltip-chip" id="slider-tip-chip">?<span class="tooltip-text" id="slider-tip-text">Slide to make the model predictions more or less strict.</span></span>
    </div>
    <div class="slider-wrap" id="slider-wrap">
      <div class="good-zone-bar" id="good-zone-bar"></div>
      <div class="slider-tooltip" id="slider-tooltip">${DEFAULT_THRESHOLD.toFixed(3)}</div>
      <input type="range" id="threshold-slider" min="0" max="${CHECKPOINTS.length - 1}" step="1" value="${defaultIdx}">
    </div>
    <div class="threshold-value" id="t-display">${DEFAULT_THRESHOLD.toFixed(3)}</div>
    <details class="metrics-details">
      <summary class="metrics-summary">Model Metrics</summary>
      <div class="metrics" id="metrics">
        <div class="metric"><span class="metric-label">Precision</span><span class="metric-value" id="mv-precision">—</span></div>
        <div class="metric"><span class="metric-label">Recall</span><span class="metric-value" id="mv-recall">—</span></div>
        <div class="metric"><span class="metric-label">F1</span><span class="metric-value" id="mv-f1">—</span></div>
        <div class="metric"><span class="metric-label">F2</span><span class="metric-value" id="mv-f2">—</span></div>
      </div>
    </details>
  `;
  positionGoodZone();

  // Slider tooltip chip
  const sliderTipChip = document.getElementById('slider-tip-chip');
  const sliderTipText = document.getElementById('slider-tip-text');
  sliderTipChip.addEventListener('click', (e) => {
    e.stopPropagation();
    e.preventDefault();
    const isVisible = sliderTipText.style.display === 'block';
    document.querySelectorAll('.tooltip-text').forEach(t => { t.style.display = 'none'; });
    if (!isVisible) {
      const r = sliderTipChip.getBoundingClientRect();
      const sidebar = document.querySelector('.sidebar');
      const sidebarRight = sidebar ? sidebar.getBoundingClientRect().right : r.right;
      sliderTipText.style.top = `${r.top}px`;
      sliderTipText.style.left = `${sidebarRight + 8}px`;
      sliderTipText.style.display = 'block';
    }
  });

  const slider = document.getElementById('threshold-slider');
  const tooltip = document.getElementById('slider-tooltip');
  const wrap = document.getElementById('slider-wrap');

  function positionTooltip() {
    const pct = slider.value / (CHECKPOINTS.length - 1);
    // Account for thumb width (14px) within track
    const trackWidth = slider.offsetWidth;
    const thumbOffset = 7; // half thumb width
    const pos = thumbOffset + pct * (trackWidth - 2 * thumbOffset);
    tooltip.style.left = `${pos}px`;
  }

  positionTooltip();

  slider.addEventListener('input', () => {
    const idx = parseInt(slider.value, 10);
    const cp = CHECKPOINTS[idx];
    const display = cp.t.toFixed(3);
    document.getElementById('t-display').textContent = display;
    tooltip.textContent = display;
    positionTooltip();
    updateMetrics(idx);
    clearTimeout(debounceTimer);
    debounceTimer = setTimeout(() => { if (onChangeCb) onChangeCb(cp); }, 150);
  });

  slider.addEventListener('mousedown', () => wrap.classList.add('active'));
  slider.addEventListener('touchstart', () => wrap.classList.add('active'), { passive: true });
  ['mouseup', 'touchend', 'touchcancel'].forEach(evt =>
    document.addEventListener(evt, () => wrap.classList.remove('active'))
  );
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
  if (!thresholdsData) return;
  const cp = thresholdsData.checkpoints[idx];
  if (!cp) return;
  const m = cp.test;
  document.getElementById('mv-precision').textContent = `${(m.precision * 100).toFixed(1)}%`;
  document.getElementById('mv-recall').textContent = `${(m.recall * 100).toFixed(1)}%`;
  document.getElementById('mv-f1').textContent = `${(m.f1 * 100).toFixed(1)}%`;
  document.getElementById('mv-f2').textContent = `${(m.f2 * 100).toFixed(1)}%`;
}
