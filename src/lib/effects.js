/**
 * Apply CSS filter strings to map panes. Three treatment groups:
 *   basemap  — the base Esri tile layer (whole map)
 *   vacant   — clipped to mask == 1
 *   nonVacant — clipped to inverted mask (mask == 0)
 * Plus boundary chrome (outline/glow/shadow opacity + blur).
 */

function filterString(brightness, contrast, saturation, hue, blur) {
  return `brightness(${brightness}) contrast(${contrast}) ` +
    `saturate(${saturation}) hue-rotate(${hue}deg) blur(${blur}px)`;
}

export function applyBasemapFilter(panes, state) {
  panes.basemapPane.style.filter = filterString(
    state.basemapBrightness, state.basemapContrast,
    state.basemapSaturation, state.basemapHue, state.basemapBlur,
  );
}

export function applyVacantFilter(panes, state) {
  panes.vacantPane.style.filter = filterString(
    state.vacantBrightness, state.vacantContrast,
    state.vacantSaturation, state.vacantHue, state.vacantBlur,
  );
}

export function applyNonVacantFilter(panes, state) {
  panes.nonVacantPane.style.filter = filterString(
    state.nonVacantBrightness, state.nonVacantContrast,
    state.nonVacantSaturation, state.nonVacantHue, state.nonVacantBlur,
  );
}

export function applyOutlineChrome(panes, state) {
  panes.outlinePane.style.opacity = state.outlineEnabled ? state.outlineOpacity : 0;
}

export function applyGlowChrome(panes, state) {
  panes.glowPane.style.opacity = state.glowEnabled ? state.glowOpacity : 0;
  panes.glowPane.style.filter = `blur(${state.glowRadius}px)`;
}

export function applyShadowChrome(panes, state) {
  panes.shadowPane.style.opacity = state.shadowEnabled ? 1 : 0;
  panes.shadowPane.style.filter = `blur(${state.shadowRadius}px)`;
}

export function renderAllShapes(boundary, state) {
  boundary.renderOutline(state);
  boundary.renderGlow(state);
  boundary.renderShadow(state);
}

export function applyAllEffects(panes, boundary, state) {
  renderAllShapes(boundary, state);
  applyBasemapFilter(panes, state);
  applyVacantFilter(panes, state);
  applyNonVacantFilter(panes, state);
  applyOutlineChrome(panes, state);
  applyGlowChrome(panes, state);
  applyShadowChrome(panes, state);
}

/** Temporarily hides all effects (compare-to-original). */
export function clearAllEffects(panes) {
  panes.basemapPane.style.filter = 'none';
  panes.vacantPane.style.filter = 'none';
  panes.nonVacantPane.style.filter = 'none';
  panes.outlinePane.style.opacity = 0;
  panes.glowPane.style.opacity = 0;
  panes.shadowPane.style.opacity = 0;
}
