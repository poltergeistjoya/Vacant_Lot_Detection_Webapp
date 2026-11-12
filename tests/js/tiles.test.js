import { describe, it, expect, vi } from 'vitest';

vi.mock('maplibre-gl', () => ({ addProtocol: vi.fn() }));
vi.mock('pmtiles', () => ({ Protocol: class { tile() {} } }));

import {
  productSource, productVisible, setRasterSource, PRODUCT_LAYER, MAP_MAX_ZOOM,
} from '../../src/lib/tiles.js';
import { FakeMap } from './fakeMap.js';

const BASE = 'https://storage.googleapis.com/bucket/pmtiles';
const { layerId, sourceId } = PRODUCT_LAYER;

// Layer stack as main.js + districts.js + parcels.js build it
function buildMap(t = 't0298', src = 'both') {
  const map = new FakeMap({
    sources: { basemap: { type: 'raster', tiles: ['esri'] }, [sourceId]: productSource(t, src, BASE) },
    layers: [
      { id: 'basemap-layer', type: 'raster', source: 'basemap' },
      { id: layerId, type: 'raster', source: sourceId },
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
  setRasterSource(map, layerId, sourceId, productSource(t, src, BASE));
  map.setLayoutProperty(layerId, 'visibility', productVisible(state) ? 'visible' : 'none');
}

function expectProductBelowVectors(map) {
  const ids = map.layerIds();
  for (const vec of ['parcel-fill', 'parcel-line', 'cd-fill', 'cd-line']) {
    expect(ids.indexOf(vec), `${vec} must be above the product raster: ${ids}`).toBeGreaterThan(ids.indexOf(layerId));
  }
  expect(ids.indexOf('basemap-layer')).toBe(0);
}

describe('productSource', () => {
  it('serves Model + PLUTO from its threshold archive at every map zoom', () => {
    const s = productSource('t0298', 'both', BASE);
    expect(s.url).toBe(`pmtiles://${BASE}/both/t0298.pmtiles`);
    expect(s.maxzoom).toBe(MAP_MAX_ZOOM);
  });

  it('serves PLUTO-only from the Model + PLUTO t1000 archive at every threshold', () => {
    for (const t of ['t0000', 't0298', 't1000']) {
      expect(productSource(t, 'pluto', BASE).url).toBe(`pmtiles://${BASE}/both/t1000.pmtiles`);
    }
  });

  it('never points at a live server tile route', () => {
    for (const src of ['both', 'model', 'pluto']) {
      const s = productSource('t0400', src, BASE);
      expect(s.url ?? s.tiles[0]).not.toContain('/api/tile/');
    }
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
  it('keeps the product raster below parcel and district layers across source switches', () => {
    const map = buildMap();
    expectProductBelowVectors(map);
    for (const src of ['model', 'pluto', 'both', 'model', 'both']) {
      update(map, 't0298', src);
      expectProductBelowVectors(map);
    }
  });

  it('keeps the product raster below vectors across threshold changes and overlay toggles', () => {
    const map = buildMap();
    for (const t of ['t0100', 't0500', 't1000']) {
      update(map, t, 'both');
      update(map, t, 'both', { overlay: false, naip: false });
      update(map, t, 'model', { overlay: true, naip: true });
      expectProductBelowVectors(map);
    }
  });

  it('applies overlay-off / NAIP visibility', () => {
    const map = buildMap();
    update(map, 't0298', 'model', { overlay: false, naip: false });
    expect(map.getLayoutProperty(layerId, 'visibility')).toBe('none');
    update(map, 't0298', 'model', { overlay: true, naip: false });
    expect(map.getLayoutProperty(layerId, 'visibility')).toBe('visible');
  });

  it('preserves visibility when the source is rebuilt', () => {
    const map = buildMap();
    map.setLayoutProperty(layerId, 'visibility', 'none');
    setRasterSource(map, layerId, sourceId, productSource('t0298', 'model', BASE));
    expect(map.getLayoutProperty(layerId, 'visibility')).toBe('none');
  });

  it('updates in place (no remove/re-add flash) for a threshold change', () => {
    const map = buildMap();
    map.calls = [];
    update(map, 't0500', 'both');
    expect(map.calls.map(c => c[0])).not.toContain('removeLayer');
    expect(map.calls).toContainEqual(['setUrl', sourceId, `pmtiles://${BASE}/both/t0500.pmtiles`]);

    update(map, 't0500', 'model');
    map.calls = [];
    update(map, 't0600', 'model');
    expect(map.calls.map(c => c[0])).not.toContain('removeLayer');
    expect(map.getSource(sourceId).serialize().tiles[0]).toBe('vacancy-model://{z}/{x}/{y}?t=t0600');
  });
});
