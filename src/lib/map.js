import * as maplibregl from 'maplibre-gl';
import 'maplibre-gl/dist/maplibre-gl.css';
import {
  ESRI_ATTRIBUTION, BRONX_CENTER_LNG_LAT, DEFAULT_ZOOM,
} from './layers.js';
import { VacancyBoundary } from './overlay.js';

const BOUNDARY_MASK_URL = 'masks/boundary.png';
const MASK_BOUNDS_URL = 'masks/bounds.json';
const DEFAULT_THRESHOLD = 't0298';

const TRANSPARENT_1PX =
  'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAAC0lEQVQI12NgAAIABQABNjN9GQAAAAlwSFlzAAAWJQAAFiUBSVIk8AAAAA0lEQVQI12P4z8BQDwAEgAF/QualzQAAAABJRU5ErkJggg==';

function productTileUrl(threshold, bm, vc, nv) {
  const params = new URLSearchParams();
  params.set('t', threshold);
  params.set('mode', 'playground');

  const prefixes = { bm_: bm, vc_: vc, nv_: nv };
  for (const [prefix, obj] of Object.entries(prefixes)) {
    for (const [k, v] of Object.entries(obj)) {
      if (v !== undefined && v !== null) params.set(prefix + k, v);
    }
  }

  return `/api/tile/product/{z}/{x}/{y}.png?${params}`;
}

/**
 * Creates a MapLibre map for the playground with server-side composited
 * tiles and client-side boundary effect overlays.
 */
export async function createMap(containerId) {
  const map = new maplibregl.Map({
    container: containerId,
    style: {
      version: 8,
      sources: {
        product: {
          type: 'raster',
          tiles: [productTileUrl(DEFAULT_THRESHOLD, {}, {}, {})],
          tileSize: 256,
          attribution: ESRI_ATTRIBUTION,
        },
      },
      layers: [{ id: 'product', type: 'raster', source: 'product' }],
    },
    center: BRONX_CENTER_LNG_LAT,
    zoom: DEFAULT_ZOOM,
    maxZoom: 18,
  });

  map.addControl(new maplibregl.NavigationControl(), 'bottom-right');

  const boundary = new VacancyBoundary();
  const [bounds] = await Promise.all([
    fetch(MASK_BOUNDS_URL).then(r => r.json()),
    boundary.load(BOUNDARY_MASK_URL),
  ]);

  const imageCoords = [
    [bounds.west, bounds.north],
    [bounds.east, bounds.north],
    [bounds.east, bounds.south],
    [bounds.west, bounds.south],
  ];

  await new Promise(resolve => {
    if (map.loaded()) resolve();
    else map.on('load', resolve);
  });

  for (const id of ['shadow', 'glow', 'outline']) {
    map.addSource(id, {
      type: 'image',
      url: TRANSPARENT_1PX,
      coordinates: imageCoords,
    });
    map.addLayer({
      id,
      type: 'raster',
      source: id,
      paint: { 'raster-opacity': 0 },
    });
  }

  map.fitBounds(
    [[bounds.west, bounds.south], [bounds.east, bounds.north]],
    { padding: 20, animate: false },
  );

  // ── State ──
  let currentThreshold = DEFAULT_THRESHOLD;
  let currentBm = {};
  let currentVc = {};
  let currentNv = {};

  function _rebuildTileSource() {
    const url = productTileUrl(currentThreshold, currentBm, currentVc, currentNv);
    if (map.getLayer('product')) map.removeLayer('product');
    if (map.getSource('product')) map.removeSource('product');

    map.addSource('product', {
      type: 'raster',
      tiles: [url],
      tileSize: 256,
      attribution: ESRI_ATTRIBUTION,
    });
    map.addLayer(
      { id: 'product', type: 'raster', source: 'product' },
      map.getLayer('shadow') ? 'shadow' : undefined,
    );
  }

  function setTreatmentParams(bm, vc, nv) {
    currentBm = bm;
    currentVc = vc;
    currentNv = nv;
    _rebuildTileSource();
  }

  function setThreshold(tStr) {
    currentThreshold = tStr;
    _rebuildTileSource();
  }

  function clearTreatments() {
    currentBm = {};
    currentVc = {};
    currentNv = {};
    _rebuildTileSource();
  }

  function updateBoundaryImage(layerId, canvas, opacity, blur) {
    let src = canvas;
    if (blur && blur > 0) {
      const blurred = document.createElement('canvas');
      blurred.width = canvas.width;
      blurred.height = canvas.height;
      const ctx = blurred.getContext('2d');
      ctx.filter = `blur(${blur}px)`;
      ctx.drawImage(canvas, 0, 0);
      src = blurred;
    }
    map.getSource(layerId).updateImage({ url: src.toDataURL(), coordinates: imageCoords });
    map.setPaintProperty(layerId, 'raster-opacity', opacity);
  }

  function hideBoundaryEffects() {
    for (const id of ['shadow', 'glow', 'outline']) {
      map.setPaintProperty(id, 'raster-opacity', 0);
    }
  }

  return {
    map,
    boundary,
    imageCoords,
    setTreatmentParams,
    setThreshold,
    clearTreatments,
    updateBoundaryImage,
    hideBoundaryEffects,
  };
}
