import { describe, it, expect, vi } from 'vitest';

vi.mock('maplibre-gl', () => ({ addProtocol: vi.fn() }));
vi.mock('pmtiles', () => ({ Protocol: class {}, PMTiles: class {} }));

import {
  selectModelOnly, makeModelOnlyHandler, productSource, modelOnlyUrls,
} from '../../src/lib/tiles.js';
import { CHECKPOINTS } from '../../src/lib/layers.js';

const BASE = 'https://storage.googleapis.com/bucket/pmtiles';
const THRESHOLDS = CHECKPOINTS.map(c => c.tStr);

// RGBA pixels: one value per pixel, repeated in R, G, B
const px = (...vals) => {
  const a = new Uint8ClampedArray(vals.length * 4);
  vals.forEach((v, i) => { a.set([v, v, v, 255], i * 4); });
  return a;
};
const values = a => Array.from({ length: a.length / 4 }, (_, i) => a[i * 4]);

describe('selectModelOnly', () => {
  it('replaces only PLUTO pixels the model does not call vacant at this threshold', () => {
    // levels: not PLUTO, PLUTO never model-vacant, PLUTO vacant at first 3, PLUTO vacant at all 18
    const level = px(255, 0, 3, 18);
    expect(values(selectModelOnly(px(10, 10, 10, 10), px(99, 99, 99, 99), level, 0))).toEqual([10, 99, 10, 10]);
    expect(values(selectModelOnly(px(10, 10, 10, 10), px(99, 99, 99, 99), level, 3))).toEqual([10, 99, 99, 10]);
    // level 18 = model-vacant at every threshold, so never replaced
    expect(values(selectModelOnly(px(10, 10, 10, 10), px(99, 99, 99, 99), level, 17))).toEqual([10, 99, 99, 10]);
  });

  it('never touches alpha', () => {
    const base = px(10);
    base[3] = 7;
    selectModelOnly(base, px(99), px(0), 5);
    expect(base[3]).toBe(7);
  });
});

describe('Model-only sources', () => {
  it('uses the vacancy-model protocol per threshold', () => {
    const s = productSource('t0298', 'model', BASE);
    expect(s.tiles[0]).toBe('vacancy-model://{z}/{x}/{y}?t=t0298');
    expect(s.maxzoom).toBe(19);
  });
});

describe('Model-only protocol handler', () => {
  const archives = modelOnlyUrls(BASE);

  function setup({ base = true, level = true } = {}) {
    const tiles = {
      [`${BASE}/both/t0298.pmtiles`]: base ? { data: 'BASE' } : undefined,
      [archives.levels]: level ? { data: 'LEVEL' } : undefined,
      [archives.nonvacant]: level ? { data: 'NONVACANT' } : undefined,
    };
    const getZxy = vi.fn();
    const getArchive = url => ({
      getZxy: (...args) => { getZxy(url, ...args); return Promise.resolve(tiles[url]); },
      getMetadata: () => Promise.resolve({ thresholds: THRESHOLDS }),
    });
    const pixels = { BASE: px(10, 10, 10), NONVACANT: px(99, 99, 99), LEVEL: px(255, 0, 18) };
    const decodePixels = vi.fn(async d => ({ data: pixels[d].slice(), width: 3, height: 1 }));
    const pixelsToImage = vi.fn(async img => ({ image: values(img.data) }));
    const handler = makeModelOnlyHandler({ getArchive, decodePixels, pixelsToImage, base: BASE });
    return { handler, getZxy, decodePixels };
  }

  const req = url => [{ url }, new AbortController()];

  it('returns the Model + PLUTO tile untouched when the tile has no PLUTO pixels', async () => {
    const { handler, decodePixels } = setup({ level: false });
    const res = await handler(...req('vacancy-model://19/1/2?t=t0298'));
    expect(res.data).toBe('BASE');
    expect(decodePixels).not.toHaveBeenCalled();
  });

  it('selects pluto_nonvacant pixels using the threshold index from the levels metadata', async () => {
    const { handler, getZxy } = setup();
    const res = await handler(...req('vacancy-model://19/1/2?t=t0298'));
    // t0298 is index 3: level 0 replaced, level 18 kept, 255 never
    expect(res.data.image).toEqual([10, 99, 10]);
    expect(getZxy).toHaveBeenCalledWith(`${BASE}/both/t0298.pmtiles`, 19, 1, 2, expect.anything());
  });

  it('returns an empty tile outside the archive', async () => {
    const { handler } = setup({ base: false, level: false });
    const res = await handler(...req('vacancy-model://11/0/0?t=t0298'));
    expect(res.data.byteLength).toBe(0);
  });

  it('rejects malformed URLs', async () => {
    const { handler } = setup();
    await expect(handler(...req('vacancy-model://19/1?t=t0298'))).rejects.toThrow(/Bad Model-only tile URL/);
  });
});
