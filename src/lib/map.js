import L from 'leaflet';
import 'leaflet/dist/leaflet.css';
import {
  ESRI_BASEMAP_URL, ESRI_ATTRIBUTION, BRONX_CENTER, DEFAULT_ZOOM,
  MASK_PNG_URL, NONVACANT_MASK_PNG_URL, MASK_BOUNDS_URL,
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

function loadImageCanvas(url) {
  return new Promise((resolve, reject) => {
    const img = new Image();
    img.onload = () => {
      const c = document.createElement('canvas');
      c.width = img.naturalWidth;
      c.height = img.naturalHeight;
      c.getContext('2d').drawImage(img, 0, 0);
      resolve(c);
    };
    img.onerror = reject;
    img.src = url;
  });
}

/**
 * Build a tile URL template with query params from a params object.
 */
function buildTileUrl(base, params) {
  const qs = Object.entries(params)
    .filter(([, v]) => v !== undefined && v !== null)
    .map(([k, v]) => `${k}=${encodeURIComponent(v)}`)
    .join('&');
  return qs ? `${base}?${qs}` : base;
}

/**
 * Creates the Leaflet map with three treatment panes (basemap, nonvacant,
 * vacant) plus boundary effect panes. Tile layers point at the backend
 * API for server-side color processing.
 *
 * Returns controls for updating tile URLs when params change.
 */
export async function createMap(containerId) {
  const map = L.map(containerId, {
    center: BRONX_CENTER,
    zoom: DEFAULT_ZOOM,
    maxZoom: 19,
    zoomControl: false,
  });

  L.control.zoom({ position: 'bottomright' }).addTo(map);

  // ── Panes ──
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
  // Start with plain Esri tiles; playground.js will swap URLs with params
  const basemapLayer = L.tileLayer(ESRI_BASEMAP_URL, {
    attribution: ESRI_ATTRIBUTION,
    pane: 'basemapPane',
    maxZoom: 19,
    className: 'seamless-tiles',
  }).addTo(map);

  const nonVacantLayer = L.tileLayer(ESRI_BASEMAP_URL, {
    pane: 'nonVacantPane',
    maxZoom: 19,
    className: 'seamless-tiles',
  }).addTo(map);

  const vacantLayer = L.tileLayer(ESRI_BASEMAP_URL, {
    pane: 'vacantPane',
    maxZoom: 19,
    className: 'seamless-tiles',
  }).addTo(map);

  // ── Load mask + boundary ──
  const boundary = new VacancyBoundary();

  const [bounds, , nonvacantSrcCanvas] = await Promise.all([
    fetch(MASK_BOUNDS_URL).then(r => r.json()),
    boundary.load(MASK_PNG_URL),
    loadImageCanvas(NONVACANT_MASK_PNG_URL),
  ]);

  const maskBounds = L.latLngBounds(
    [bounds.south, bounds.west],
    [bounds.north, bounds.east],
  );

  new CanvasOverlay(boundary.shadowCanvas, maskBounds, { pane: 'shadowPane' }).addTo(map);
  new CanvasOverlay(boundary.glowCanvas, maskBounds, { pane: 'glowPane' }).addTo(map);
  new CanvasOverlay(boundary.outlineCanvas, maskBounds, { pane: 'outlinePane' }).addTo(map);

  map.fitBounds(maskBounds);

  // ── Mask geometry sync ──
  // Render only the viewport-visible portion of each mask to a canvas,
  // then use the canvas data URL as the CSS mask-image. This keeps the
  // mask at viewport resolution regardless of zoom level — the old
  // approach scaled the full PNG via mask-size, which exceeded browser
  // texture limits (~16 384 px) at high zoom and disappeared entirely.
  const vacantSrcCanvas = boundary.maskCanvas;
  const vacantWorkCanvas = document.createElement('canvas');
  const nonvacantWorkCanvas = document.createElement('canvas');

  function renderCroppedMask(src, work, viewW, viewH, nw, maskW, maskH) {
    work.width = viewW;
    work.height = viewH;
    const ctx = work.getContext('2d');
    const srcW = src.width;
    const srcH = src.height;
    const scaleX = srcW / maskW;
    const scaleY = srcH / maskH;
    const sx = -nw.x * scaleX;
    const sy = -nw.y * scaleY;
    const sw = viewW * scaleX;
    const sh = viewH * scaleY;
    const cx0 = Math.max(0, sx);
    const cy0 = Math.max(0, sy);
    const cx1 = Math.min(srcW, sx + sw);
    const cy1 = Math.min(srcH, sy + sh);
    if (cx1 <= cx0 || cy1 <= cy0) return;
    ctx.drawImage(src, cx0, cy0, cx1 - cx0, cy1 - cy0,
                  (cx0 - sx) / scaleX, (cy0 - sy) / scaleY,
                  (cx1 - cx0) / scaleX, (cy1 - cy0) / scaleY);
  }

  function applyCanvasMask(pane, dataUrl, viewW, viewH) {
    const s = pane.style;
    s.width = `${viewW}px`;
    s.height = `${viewH}px`;
    s.maskImage = s.webkitMaskImage = `url(${dataUrl})`;
    s.maskRepeat = s.webkitMaskRepeat = 'no-repeat';
    s.maskSize = s.webkitMaskSize = `${viewW}px ${viewH}px`;
    s.maskPosition = s.webkitMaskPosition = '0px 0px';
  }

  function updateMaskGeometry() {
    const nw = map.latLngToLayerPoint(maskBounds.getNorthWest());
    const se = map.latLngToLayerPoint(maskBounds.getSouthEast());
    const maskW = se.x - nw.x;
    const maskH = se.y - nw.y;
    if (maskW <= 0 || maskH <= 0) return;

    const size = map.getSize();
    const viewW = size.x;
    const viewH = size.y;

    renderCroppedMask(vacantSrcCanvas, vacantWorkCanvas, viewW, viewH, nw, maskW, maskH);
    renderCroppedMask(nonvacantSrcCanvas, nonvacantWorkCanvas, viewW, viewH, nw, maskW, maskH);

    applyCanvasMask(vacantPane, vacantWorkCanvas.toDataURL(), viewW, viewH);
    applyCanvasMask(nonVacantPane, nonvacantWorkCanvas.toDataURL(), viewW, viewH);
  }

  updateMaskGeometry();
  map.on('moveend zoomend', updateMaskGeometry);

  // ── URL update helpers ──
  // Call these when slider params change to swap tile URLs
  function setBasemapUrl(params) {
    const url = buildTileUrl('/api/tile/{z}/{x}/{y}.png', params);
    basemapLayer.setUrl(url);
  }

  function setVacantUrl(params) {
    const url = buildTileUrl('/api/tile/vacant/{z}/{x}/{y}.png', params);
    vacantLayer.setUrl(url);
  }

  function setNonVacantUrl(params) {
    const url = buildTileUrl('/api/tile/nonvacant/{z}/{x}/{y}.png', params);
    nonVacantLayer.setUrl(url);
  }

  return {
    map,
    boundary,
    maskBounds,
    panes: { basemapPane, nonVacantPane, vacantPane, shadowPane, glowPane, outlinePane },
    setBasemapUrl,
    setVacantUrl,
    setNonVacantUrl,
  };
}
