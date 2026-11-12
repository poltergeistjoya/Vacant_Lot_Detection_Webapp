import * as pmtiles from 'pmtiles';
import * as maplibregl from 'maplibre-gl';

const PMTILES_BASE_URL = __PMTILES_BASE_URL__;
// Archives uploaded under PMTILES_BASE_URL ('both', 'pluto_nonvacant', 'model_levels');
// vacancy sources whose archives are missing fall back to server tiles
const PMTILES_SOURCES = __PMTILES_SOURCES__;

// Highest zoom the map allows
export const MAP_MAX_ZOOM = 19;
// Highest zoom baked into PMTiles archives (prerender_tiles.py --zoom default)
export const PMTILES_MAX_ZOOM = 19;
// Highest zoom of the server's low-zoom placeholder layer (no PMTiles)
const SERVER_CACHED_MAX_ZOOM = 18;

// Product layers, bottom to top. 'product-cached' is the PMTiles archive (or a
// server placeholder up to z18); 'product' is server tiles for zooms the archive
// doesn't cover.
export const PRODUCT_LAYERS = [
  { layerId: 'product-cached-layer', sourceId: 'product-cached' },
  { layerId: 'product-layer', sourceId: 'product' },
];

let _protocol = null;

export function initPMTilesProtocol() {
  if (_protocol) return;
  _protocol = new pmtiles.Protocol();
  maplibregl.addProtocol('pmtiles', _protocol.tile);
  maplibregl.addProtocol(MODEL_ONLY_PROTOCOL, makeModelOnlyHandler({
    getArchive, decodePixels, pixelsToImage,
  }));
}

// One PMTiles instance per archive, shared with the pmtiles:// protocol so headers,
// directories and tiles fetched for Model + PLUTO are reused for Model-only.
function getArchive(url) {
  let archive = _protocol.get(url);
  if (!archive) {
    archive = new pmtiles.PMTiles(url);
    _protocol.add(archive);
  }
  return archive;
}

// No pixel is model-vacant at t1000, so the Model + PLUTO archive at t1000 is
// exactly the PLUTO-only product (PLUTO vacant, rest of boundary non-vacant).
// Guarded by test_pluto_only_equals_both_at_max_threshold in tests/py.
const PLUTO_ONLY_ARCHIVE = { source: 'both', threshold: 't1000' };

// Which archive holds a vacancy source (PLUTO-only is threshold-independent)
export function archiveFor(threshold, source) {
  return source === 'pluto' ? PLUTO_ONLY_ARCHIVE : { source, threshold };
}

// Archives each vacancy source needs
const REQUIRED_ARCHIVES = {
  both: ['both'],
  pluto: ['both'],
  model: ['both', 'pluto_nonvacant', 'model_levels'],
};

export function usesPMTiles(source, base = PMTILES_BASE_URL, available = PMTILES_SOURCES) {
  return !!base && (REQUIRED_ARCHIVES[source] ?? [source]).every(a => available.includes(a));
}

// ── Model-only from Model + PLUTO ────────────────────
// See "Model-only from Model + PLUTO" in server/app.py. All color treatment is prerendered in
// Python; the browser only picks, per pixel, between two prerendered tiles.

export const MODEL_ONLY_PROTOCOL = 'vacancy-model';
const LEVEL_NOT_PLUTO = 255;

export function modelOnlyTileUrl(threshold) {
  return `${MODEL_ONLY_PROTOCOL}://{z}/{x}/{y}?t=${threshold}`;
}

export function modelOnlyUrls(base = PMTILES_BASE_URL) {
  return {
    nonvacant: `${base}/pluto_nonvacant.pmtiles`,
    levels: `${base}/model_levels.pmtiles`,
  };
}

/**
 * Turn a Model + PLUTO tile into Model-only in place: wherever the level tile says
 * "PLUTO, but not model-vacant at this threshold" (level <= index), take the
 * pluto_nonvacant pixel. RGBA arrays of equal length.
 */
export function selectModelOnly(baseRGBA, nonvacantRGBA, levelRGBA, thresholdIndex) {
  for (let i = 0; i < baseRGBA.length; i += 4) {
    if (levelRGBA[i] <= thresholdIndex) {
      baseRGBA[i] = nonvacantRGBA[i];
      baseRGBA[i + 1] = nonvacantRGBA[i + 1];
      baseRGBA[i + 2] = nonvacantRGBA[i + 2];
    }
  }
  return baseRGBA;
}

/**
 * MapLibre protocol handler for vacancy-model://{z}/{x}/{y}?t=<threshold>.
 * Dependencies are injected so the logic is testable without a browser.
 */
export function makeModelOnlyHandler({ getArchive, decodePixels, pixelsToImage, base = PMTILES_BASE_URL }) {
  const archives = modelOnlyUrls(base);
  let thresholds = null;

  return async (params, abortController) => {
    const m = params.url.match(/^[\w-]+:\/\/(\d+)\/(\d+)\/(\d+)\?t=(t\d+)$/);
    if (!m) throw new Error(`Bad Model-only tile URL: ${params.url}`);
    const [z, x, y] = m.slice(1, 4).map(Number);
    const threshold = m[4];
    const signal = abortController?.signal;

    // A missing tile is only a directory lookup, so all three can start at once
    const [baseTile, levelTile, nonvacantTile] = await Promise.all([
      getArchive(`${base}/both/${threshold}.pmtiles`).getZxy(z, x, y, signal),
      getArchive(archives.levels).getZxy(z, x, y, signal),
      getArchive(archives.nonvacant).getZxy(z, x, y, signal),
    ]);
    if (!baseTile) return { data: new Uint8Array(0) };
    // No PLUTO pixels in this tile: Model-only is identical to Model + PLUTO
    if (!levelTile || !nonvacantTile) return { data: baseTile.data };

    thresholds ??= getArchive(archives.levels).getMetadata().then(meta => meta.thresholds);
    const index = (await thresholds).indexOf(threshold);
    if (index < 0) throw new Error(`Threshold ${threshold} not in model_levels`);

    const [basePx, nonvacantPx, levelPx] = await Promise.all(
      [baseTile, nonvacantTile, levelTile].map(t => decodePixels(t.data)),
    );
    selectModelOnly(basePx.data, nonvacantPx.data, levelPx.data, index);
    return { data: await pixelsToImage(basePx) };
  };
}

async function decodePixels(buffer) {
  // 'none': level values and pixel colors must come through unaltered
  const bitmap = await createImageBitmap(new Blob([buffer]), {
    colorSpaceConversion: 'none', premultiplyAlpha: 'none',
  });
  const canvas = typeof OffscreenCanvas !== 'undefined'
    ? new OffscreenCanvas(bitmap.width, bitmap.height)
    : Object.assign(document.createElement('canvas'), { width: bitmap.width, height: bitmap.height });
  const ctx = canvas.getContext('2d', { willReadFrequently: true });
  ctx.drawImage(bitmap, 0, 0);
  bitmap.close();
  return ctx.getImageData(0, 0, canvas.width, canvas.height);
}

function pixelsToImage(imageData) {
  return createImageBitmap(imageData);
}

export function pmtilesProductUrl(threshold, source, base = PMTILES_BASE_URL) {
  const archive = archiveFor(threshold, source);
  return `pmtiles://${base}/${archive.source}/${archive.threshold}.pmtiles`;
}

export function serverProductUrl(threshold, source) {
  return `/api/tile/product/{z}/{x}/{y}.jpg?t=${threshold}&source=${source}`;
}

/**
 * Product layer specs keyed by source id, plus whether each layer is needed.
 *
 * With PMTiles for this vacancy source the archive serves every zoom it has; server
 * tiles only fill zooms above PMTILES_MAX_ZOOM (otherwise those are blurry upscales).
 * Without PMTiles: server tiles at every zoom, as before the PMTiles migration.
 */
export function productSources(threshold, source, base = PMTILES_BASE_URL, available = PMTILES_SOURCES,
                               pmMaxZoom = PMTILES_MAX_ZOOM) {
  const pm = usesPMTiles(source, base, available);
  const server = serverProductUrl(threshold, source);
  const detailMinZoom = pm ? Math.min(pmMaxZoom + 1, MAP_MAX_ZOOM) : 0;
  let cached;
  if (!pm) cached = { type: 'raster', tiles: [server], tileSize: 256, maxzoom: SERVER_CACHED_MAX_ZOOM };
  else if (source === 'model') cached = { type: 'raster', tiles: [modelOnlyTileUrl(threshold)], tileSize: 256, maxzoom: pmMaxZoom };
  else cached = { type: 'raster', url: pmtilesProductUrl(threshold, source, base), tileSize: 256, maxzoom: pmMaxZoom };
  return {
    'product-cached': { enabled: true, spec: cached },
    product: {
      enabled: !pm || pmMaxZoom < MAP_MAX_ZOOM,
      spec: { type: 'raster', tiles: [server], tileSize: 256, minzoom: detailMinZoom, maxzoom: MAP_MAX_ZOOM },
    },
  };
}

/** Whether the vacancy product should be drawn (NAIP and overlay-off show the plain basemap). */
export function productVisible({ overlay, naip }) {
  return overlay && !naip;
}

function sameShape(a, b) {
  return !!a.url === !!b.url && a.minzoom === b.minzoom && a.maxzoom === b.maxzoom;
}

/**
 * Point a raster layer at a new source spec without changing its position in the
 * layer stack or its visibility. Updates in place when possible to avoid a flash.
 */
export function setRasterSource(map, layerId, sourceId, spec) {
  const existing = map.getSource(sourceId);
  const current = existing?.serialize?.();
  if (current && map.getLayer(layerId) && sameShape(current, spec)) {
    if (spec.url && current.url !== spec.url) existing.setUrl(spec.url);
    else if (spec.tiles && current.tiles?.[0] !== spec.tiles[0]) existing.setTiles(spec.tiles);
    return;
  }

  const layers = map.getStyle().layers;
  const idx = layers.findIndex(l => l.id === layerId);
  const beforeId = idx >= 0 ? layers[idx + 1]?.id : undefined;
  const visibility = idx >= 0 ? (map.getLayoutProperty(layerId, 'visibility') ?? 'visible') : 'visible';

  if (idx >= 0) map.removeLayer(layerId);
  if (existing) map.removeSource(sourceId);
  map.addSource(sourceId, spec);
  map.addLayer({ id: layerId, type: 'raster', source: sourceId, layout: { visibility } }, beforeId);
}
