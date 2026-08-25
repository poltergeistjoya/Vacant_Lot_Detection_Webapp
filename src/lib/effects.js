/**
 * Apply CSS filter strings to map panes. Two treatment groups:
 *   basemap — the base Esri tile layer (everything outside the mask shows through)
 *   vacant  — clipped to mask == 1, independently filtered
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
  applyOutlineChrome(panes, state);
  applyGlowChrome(panes, state);
  applyShadowChrome(panes, state);
}

/** Temporarily hides all effects (compare-to-original). */
export function clearAllEffects(panes) {
  panes.basemapPane.style.filter = 'none';
  panes.vacantPane.style.filter = 'none';
  panes.outlinePane.style.opacity = 0;
  panes.glowPane.style.opacity = 0;
  panes.shadowPane.style.opacity = 0;
}
