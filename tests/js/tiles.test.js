import { describe, it, expect, vi } from 'vitest';

vi.mock('maplibre-gl', () => ({ addProtocol: vi.fn() }));
vi.mock('pmtiles', () => ({ Protocol: class { tile() {} } }));

import {
  productSources, productVisible, setRasterSource, usesPMTiles,
  PRODUCT_LAYERS, PMTILES_MAX_ZOOM, MAP_MAX_ZOOM,
} from '../../src/lib/tiles.js';
import { FakeMap } from './fakeMap.js';

const BASE = 'https://storage.googleapis.com/bucket/pmtiles';
const UPLOADED = ['both'];
const SOURCES = ['both', 'model', 'pluto'];

const layers = (t, src, base = BASE, avail = UPLOADED, pmMax = PMTILES_MAX_ZOOM) =>
  productSources(t, src, base, avail, pmMax);
const specs = (...args) => Object.fromEntries(Object.entries(layers(...args)).map(([id, l]) => [id, l.spec]));

// Layer stack as main.js + districts.js + parcels.js build it
function buildMap(t = 't0298', src = 'both') {
  const map = new FakeMap({
    sources: { basemap: { type: 'raster', tiles: ['esri'] }, ...specs(t, src) },
    layers: [
      { id: 'basemap-layer', type: 'raster', source: 'basemap' },
      ...PRODUCT_LAYERS.map(({ layerId, sourceId }) => ({ id: layerId, type: 'raster', source: sourceId })),
    ],
  });
  map.addLayer({ id: 'cd-fill', type: 'fill', source: 'cd' });
  map.addLayer({ id: 'cd-line', type: 'line', source: 'cd' });
  map.addLayer({ id: 'parcel-fill', type: 'fill', source: 'parcels' }, 'cd-fill');
  map.addLayer({ id: 'parcel-line', type: 'line', source: 'parcels' }, 'cd-fill');
  return map;
}

// Same logic as main.js updateTileSource()
function update(map, t, src, state = { overlay: true, naip: false }) {
  const ls = layers(t, src);
  const show = productVisible(state);
  for (const { layerId, sourceId } of PRODUCT_LAYERS) {
    setRasterSource(map, layerId, sourceId, ls[sourceId].spec);
    map.setLayoutProperty(layerId, 'visibility', show && ls[sourceId].enabled ? 'visible' : 'none');
  }
}

function expectProductBelowVectors(map) {
  const ids = map.layerIds();
  const topRaster = Math.max(...PRODUCT_LAYERS.map(l => ids.indexOf(l.layerId)));
  for (const vec of ['parcel-fill', 'parcel-line', 'cd-fill', 'cd-line']) {
    expect(ids.indexOf(vec), `${vec} must be above product rasters: ${ids}`).toBeGreaterThan(topRaster);
  }
  expect(ids.indexOf('product-cached-layer')).toBeLessThan(ids.indexOf('product-layer'));
  expect(ids.indexOf('basemap-layer')).toBe(0);
}

describe('productSources', () => {
  it('archives cover every map zoom, so z19 is never an upscale of z18', () => {
    expect(PMTILES_MAX_ZOOM).toBeGreaterThanOrEqual(MAP_MAX_ZOOM);
  });

  it('serves uploaded sources entirely from PMTiles, with no server detail layer', () => {
    const l = layers('t0298', 'both');
    expect(l['product-cached'].spec.url).toBe(`pmtiles://${BASE}/both/t0298.pmtiles`);
    expect(l['product-cached'].spec.maxzoom).toBe(MAP_MAX_ZOOM);
    expect(l.product.enabled).toBe(false);
  });

  it('fills zooms above a shorter archive with live server tiles', () => {
    const l = layers('t0298', 'both', BASE, UPLOADED, 18);
    expect(l['product-cached'].spec.maxzoom).toBe(18);
    expect(l.product.enabled).toBe(true);
    expect(l.product.spec.minzoom).toBe(19);
    expect(l.product.spec.tiles[0]).toContain('/api/tile/product/');
  });

  it('serves PLUTO-only from the Model + PLUTO t1000 archive at every threshold', () => {
    for (const t of ['t0000', 't0298', 't1000']) {
      const l = layers(t, 'pluto');
      expect(l['product-cached'].spec.url).toBe(`pmtiles://${BASE}/both/t1000.pmtiles`);
      expect(l.product.enabled).toBe(false);
    }
  });

  it('falls back to server tiles for PLUTO-only when the Model + PLUTO archives are not available', () => {
    const s = specs('t0298', 'pluto', BASE, ['model']);
    expect(s['product-cached'].tiles[0]).toContain('source=pluto');
  });

  it('falls back to server tiles for sources without archives (model)', () => {
    for (const src of ['model']) {
      const s = specs('t0298', src);
      expect(s['product-cached'].url).toBeUndefined();
      expect(s['product-cached'].tiles[0]).toContain(`source=${src}`);
      expect(s.product.tiles[0]).toContain(`source=${src}`);
      expect(s.product.minzoom).toBe(0);
      expect(layers('t0298', src).product.enabled).toBe(true);
    }
  });

  it('every source and zoom up to the map max has full-resolution tiles', () => {
    for (const avail of [[], ['both'], SOURCES]) {
      for (const src of SOURCES) {
        const l = layers('t0400', src, BASE, avail);
        const enabledMax = Math.max(...Object.values(l).filter(x => x.enabled).map(x => x.spec.maxzoom));
        expect(enabledMax).toBeGreaterThanOrEqual(MAP_MAX_ZOOM);
        const s = specs('t0400', src, BASE, avail);
        const cachedUrl = s['product-cached'].url ?? s['product-cached'].tiles[0];
        if (s['product-cached'].url && src === 'pluto') {
          expect(cachedUrl).toContain('both/t1000');
        } else {
          expect(cachedUrl).toContain(src);
          expect(cachedUrl).toContain('t0400');
        }
      }
    }
  });

  it('uses server tiles everywhere when no PMTiles base URL is configured', () => {
    expect(usesPMTiles('both', '', SOURCES)).toBe(false);
    const s = specs('t0298', 'both', '');
    expect(s['product-cached'].tiles[0]).toContain('/api/tile/product/');
  });
});

describe('productVisible', () => {
  it('hides the product when the vacancy overlay is off (no grayed-out streets)', () => {
    expect(productVisible({ overlay: false, naip: false })).toBe(false);
  });
  it('hides the product when NAIP imagery is on', () => {
    expect(productVisible({ overlay: true, naip: true })).toBe(false);
  });
  it('shows the product otherwise', () => {
    expect(productVisible({ overlay: true, naip: false })).toBe(true);
  });
});

describe('setRasterSource / layer ordering', () => {
  it('keeps product rasters below parcel and district layers across source switches', () => {
    const map = buildMap();
    expectProductBelowVectors(map);
    for (const src of ['model', 'pluto', 'both', 'model', 'both']) {
      update(map, 't0298', src);
      expectProductBelowVectors(map);
    }
  });

  it('keeps product rasters below vectors across threshold changes and overlay toggles', () => {
    const map = buildMap();
    for (const t of ['t0100', 't0500', 't1000']) {
      update(map, t, 'both');
      update(map, t, 'both', { overlay: false, naip: false });
      update(map, t, 'model', { overlay: true, naip: true });
      expectProductBelowVectors(map);
    }
  });

  it('applies overlay-off / NAIP visibility to every product layer', () => {
    const map = buildMap();
    update(map, 't0298', 'model', { overlay: false, naip: false });
    for (const { layerId } of PRODUCT_LAYERS) expect(map.getLayoutProperty(layerId, 'visibility')).toBe('none');
    update(map, 't0298', 'model', { overlay: true, naip: false });
    for (const { layerId } of PRODUCT_LAYERS) expect(map.getLayoutProperty(layerId, 'visibility')).toBe('visible');
    update(map, 't0298', 'both', { overlay: true, naip: false });
    expect(map.getLayoutProperty('product-cached-layer', 'visibility')).toBe('visible');
    expect(map.getLayoutProperty('product-layer', 'visibility')).toBe('none');
  });

  it('preserves visibility when the source is rebuilt', () => {
    const map = buildMap();
    map.setLayoutProperty('product-cached-layer', 'visibility', 'none');
    setRasterSource(map, 'product-cached-layer', 'product-cached', specs('t0298', 'model')['product-cached']);
    expect(map.getLayoutProperty('product-cached-layer', 'visibility')).toBe('none');
  });

  it('updates in place (no remove/re-add flash) for a threshold change', () => {
    const map = buildMap();
    map.calls = [];
    update(map, 't0500', 'both');
    expect(map.calls.map(c => c[0])).not.toContain('removeLayer');
    expect(map.calls).toContainEqual(['setUrl', 'product-cached', `pmtiles://${BASE}/both/t0500.pmtiles`]);
    expect(map.getSource('product').serialize().tiles[0]).toContain('t=t0500');

    map.calls = [];
    update(map, 't0500', 'model');
    update(map, 't0600', 'model');
    const last = map.calls.slice(-4).map(c => c[0]);
    expect(last).not.toContain('removeLayer');
  });
});

describe('Model-only layer handling', () => {
  it('keeps product rasters below vectors when switching into and out of Model-only', () => {
    const all = ['both', 'pluto_nonvacant', 'model_levels'];
    const map = buildMap();
    for (const [t, src] of [['t0298', 'model'], ['t0500', 'model'], ['t0500', 'both'], ['t0500', 'pluto'], ['t0100', 'model']]) {
      const ls = productSources(t, src, BASE, all);
      for (const { layerId, sourceId } of PRODUCT_LAYERS) {
        setRasterSource(map, layerId, sourceId, ls[sourceId].spec);
      }
      expectProductBelowVectors(map);
    }
    expect(map.getSource('product-cached').serialize().tiles[0]).toBe('vacancy-model://{z}/{x}/{y}?t=t0100');
  });
});
