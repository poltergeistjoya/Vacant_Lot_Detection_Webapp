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
 * Creates the Leaflet map with panes for basemap treatment and vacant
 * area treatment. The basemap pane is the base Esri imagery — filtering
 * it changes how everything outside the mask looks (i.e. non-vacant areas).
 * The vacant pane is a second copy of Esri tiles, CSS-masked to mask==1,
 * so filtering it only affects vacant areas.
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
  // basemapPane: base tiles, filtered = non-vacant treatment
  // vacantPane: masked tiles, filtered = vacant treatment
  // shadow/glow/outline: boundary effects
  map.createPane('basemapPane');
  map.createPane('shadowPane');
  map.createPane('glowPane');
  map.createPane('vacantPane');
  map.createPane('outlinePane');
  map.getPane('basemapPane').style.zIndex = 200;
  map.getPane('shadowPane').style.zIndex = 340;
  map.getPane('glowPane').style.zIndex = 350;
  map.getPane('vacantPane').style.zIndex = 400;
  map.getPane('outlinePane').style.zIndex = 450;

  const basemapPane = map.getPane('basemapPane');
  const shadowPane = map.getPane('shadowPane');
  const glowPane = map.getPane('glowPane');
  const vacantPane = map.getPane('vacantPane');
  const outlinePane = map.getPane('outlinePane');

  // ── Tile layers ──
  L.tileLayer(ESRI_BASEMAP_URL, {
    attribution: ESRI_ATTRIBUTION,
    pane: 'basemapPane',
    maxZoom: 19,
    className: 'seamless-tiles',
  }).addTo(map);

  // Vacant: same tiles, CSS-masked to mask==1
  L.tileLayer(ESRI_BASEMAP_URL, {
    pane: 'vacantPane',
    maxZoom: 19,
    className: 'seamless-tiles',
  }).addTo(map);

  // ── Load mask + boundary data ──
  const boundary = new VacancyBoundary();
  const [bounds] = await Promise.all([
    fetch(MASK_BOUNDS_URL).then(r => r.json()),
    boundary.load(MASK_PNG_URL),
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
  function updateMaskGeometry() {
    const nw = map.latLngToLayerPoint(maskBounds.getNorthWest());
    const se = map.latLngToLayerPoint(maskBounds.getSouthEast());
    const w = Math.max(0, se.x - nw.x);
    const h = Math.max(0, se.y - nw.y);

    const vs = vacantPane.style;
    vs.maskImage = vs.webkitMaskImage = `url(${MASK_PNG_URL})`;
    vs.maskRepeat = vs.webkitMaskRepeat = 'no-repeat';
    vs.maskSize = vs.webkitMaskSize = `${w}px ${h}px`;
    vs.maskPosition = vs.webkitMaskPosition = `${nw.x}px ${nw.y}px`;
  }

  updateMaskGeometry();
  map.on('move zoom zoomend', updateMaskGeometry);

  return {
    map,
    boundary,
    maskBounds,
    panes: { basemapPane, vacantPane, shadowPane, glowPane, outlinePane },
  };
}
