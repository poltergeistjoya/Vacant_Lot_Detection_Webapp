import L from 'leaflet';
import 'leaflet/dist/leaflet.css';
import {
  ESRI_BASEMAP_URL, ESRI_ATTRIBUTION, BRONX_CENTER, DEFAULT_ZOOM,
  MASK_PNG_URL, MASK_BOUNDS_URL,
} from './layers.js';
import { VacancyBoundary } from './overlay.js';

// L.ImageOverlay subclass that accepts a <canvas> element directly.
const CanvasOverlay = L.ImageOverlay.extend({
  _initImage: function () {
    const img = this._image = this._url;
    L.DomUtil.addClass(img, 'leaflet-image-layer');
    if (this._zoomAnimated) L.DomUtil.addClass(img, 'leaflet-zoom-animated');
    if (this.options.className) L.DomUtil.addClass(img, this.options.className);
    img.onselectstart = L.Util.falseFn;
    img.onmousemove = L.Util.falseFn;
    if (this.options.zIndex) this._updateZIndex();
  },
});

/**
 * Generate an inverted-alpha version of the mask image. Where the original
 * mask has opaque pixels (vacant), the inverse is transparent, and vice versa.
 * Returns a data URL suitable for CSS mask-image.
 */
function invertMaskAlpha(img) {
  const c = document.createElement('canvas');
  c.width = img.naturalWidth;
  c.height = img.naturalHeight;
  const ctx = c.getContext('2d');
  ctx.drawImage(img, 0, 0);
  const imageData = ctx.getImageData(0, 0, c.width, c.height);
  const d = imageData.data;
  for (let i = 3; i < d.length; i += 4) {
    d[i] = 255 - d[i]; // invert alpha
  }
  ctx.putImageData(imageData, 0, 0);
  return c.toDataURL();
}

/**
 * Creates the Leaflet map with six panes (basemap, vacant, non-vacant,
 * shadow, glow, outline) and boundary overlays. Returns everything
 * callers need to drive treatments.
 */
export async function createMap(containerId) {
  const map = L.map(containerId, {
    center: BRONX_CENTER,
    zoom: DEFAULT_ZOOM,
    maxZoom: 19,
    zoomControl: false,
  });

  L.control.zoom({ position: 'bottomright' }).addTo(map);

  // ── Panes (z-order: basemap < nonVacant < shadow < glow < vacant < outline) ──
  // Each treatment group gets its own pane so CSS filters are independent.
  map.createPane('basemapPane');
  map.createPane('nonVacantPane');
  map.createPane('shadowPane');
  map.createPane('glowPane');
  map.createPane('vacantPane');
  map.createPane('outlinePane');
  map.getPane('basemapPane').style.zIndex = 200;
  map.getPane('nonVacantPane').style.zIndex = 300;
  map.getPane('shadowPane').style.zIndex = 340;
  map.getPane('glowPane').style.zIndex = 350;
  map.getPane('vacantPane').style.zIndex = 400;
  map.getPane('outlinePane').style.zIndex = 450;

  const basemapPane = map.getPane('basemapPane');
  const nonVacantPane = map.getPane('nonVacantPane');
  const shadowPane = map.getPane('shadowPane');
  const glowPane = map.getPane('glowPane');
  const vacantPane = map.getPane('vacantPane');
  const outlinePane = map.getPane('outlinePane');

  // ── Tile layers ──
  // Base: targeted by basemap treatment filter
  L.tileLayer(ESRI_BASEMAP_URL, {
    attribution: ESRI_ATTRIBUTION,
    pane: 'basemapPane',
    maxZoom: 19,
    className: 'seamless-tiles',
  }).addTo(map);

  // Non-vacant: clipped to inverted mask
  L.tileLayer(ESRI_BASEMAP_URL, {
    pane: 'nonVacantPane',
    maxZoom: 19,
    className: 'seamless-tiles',
  }).addTo(map);

  // Vacant: clipped to mask
  L.tileLayer(ESRI_BASEMAP_URL, {
    pane: 'vacantPane',
    maxZoom: 19,
    className: 'seamless-tiles',
  }).addTo(map);

  // ── Load mask + boundary data ──
  const boundary = new VacancyBoundary();
  const maskImg = new Image();
  const maskImgLoaded = new Promise((resolve, reject) => {
    maskImg.onload = () => resolve(maskImg);
    maskImg.onerror = reject;
    maskImg.src = MASK_PNG_URL;
  });

  const [bounds, loadedMaskImg] = await Promise.all([
    fetch(MASK_BOUNDS_URL).then(r => r.json()),
    maskImgLoaded,
    boundary.load(MASK_PNG_URL),
  ]);

  const invertedMaskUrl = invertMaskAlpha(loadedMaskImg);

  const maskBounds = L.latLngBounds(
    [bounds.south, bounds.west],
    [bounds.north, bounds.east],
  );

  new CanvasOverlay(boundary.shadowCanvas, maskBounds, { pane: 'shadowPane' }).addTo(map);
  new CanvasOverlay(boundary.glowCanvas, maskBounds, { pane: 'glowPane' }).addTo(map);
  new CanvasOverlay(boundary.outlineCanvas, maskBounds, { pane: 'outlinePane' }).addTo(map);

  map.fitBounds(maskBounds);

  // ── Mask geometry sync ──
  function updateMaskGeometry() {
    const nw = map.latLngToLayerPoint(maskBounds.getNorthWest());
    const se = map.latLngToLayerPoint(maskBounds.getSouthEast());
    const w = Math.max(0, se.x - nw.x);
    const h = Math.max(0, se.y - nw.y);

    // Vacant pane: original mask
    const vs = vacantPane.style;
    vs.maskImage = vs.webkitMaskImage = `url(${MASK_PNG_URL})`;
    vs.maskRepeat = vs.webkitMaskRepeat = 'no-repeat';
    vs.maskSize = vs.webkitMaskSize = `${w}px ${h}px`;
    vs.maskPosition = vs.webkitMaskPosition = `${nw.x}px ${nw.y}px`;

    // Non-vacant pane: inverted mask
    const nvs = nonVacantPane.style;
    nvs.maskImage = nvs.webkitMaskImage = `url(${invertedMaskUrl})`;
    nvs.maskRepeat = nvs.webkitMaskRepeat = 'no-repeat';
    nvs.maskSize = nvs.webkitMaskSize = `${w}px ${h}px`;
    nvs.maskPosition = nvs.webkitMaskPosition = `${nw.x}px ${nw.y}px`;
  }

  updateMaskGeometry();
  map.on('move zoom zoomend', updateMaskGeometry);

  return {
    map,
    boundary,
    maskBounds,
    panes: {
      basemapPane,
      vacantPane,
      nonVacantPane,
      shadowPane,
      glowPane,
      outlinePane,
    },
  };
}
