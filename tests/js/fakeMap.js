// Minimal stand-in for maplibregl.Map: tracks sources, layer order, and visibility.
export class FakeMap {
  constructor({ sources = {}, layers = [] } = {}) {
    this.sources = new Map();
    this.layers = [];
    this.calls = [];
    for (const [id, spec] of Object.entries(sources)) this.addSource(id, spec);
    for (const l of layers) this.addLayer(l);
    this.calls = [];
  }

  getStyle() {
    return { layers: this.layers.map(l => ({ ...l })) };
  }

  layerIds() {
    return this.layers.map(l => l.id);
  }

  getLayer(id) {
    return this.layers.find(l => l.id === id);
  }

  addLayer(layer, beforeId) {
    if (this.getLayer(layer.id)) throw new Error(`layer ${layer.id} exists`);
    if (!this.sources.has(layer.source) && layer.type === 'raster') {
      throw new Error(`source ${layer.source} missing`);
    }
    const entry = { ...layer, layout: { ...(layer.layout || {}) } };
    const idx = beforeId ? this.layers.findIndex(l => l.id === beforeId) : -1;
    if (beforeId && idx < 0) throw new Error(`beforeId ${beforeId} not found`);
    if (idx >= 0) this.layers.splice(idx, 0, entry);
    else this.layers.push(entry);
    this.calls.push(['addLayer', layer.id, beforeId]);
  }

  removeLayer(id) {
    this.layers = this.layers.filter(l => l.id !== id);
    this.calls.push(['removeLayer', id]);
  }

  moveLayer(id, beforeId) {
    const layer = this.getLayer(id);
    this.removeLayer(id);
    this.addLayer(layer, beforeId);
  }

  getLayoutProperty(id, prop) {
    return this.getLayer(id)?.layout?.[prop];
  }

  setLayoutProperty(id, prop, value) {
    this.getLayer(id).layout[prop] = value;
  }

  getSource(id) {
    return this.sources.get(id);
  }

  addSource(id, spec) {
    if (this.sources.has(id)) throw new Error(`source ${id} exists`);
    const options = { ...spec };
    this.sources.set(id, {
      serialize: () => ({ ...options }),
      setUrl: (url) => { options.url = url; this.calls.push(['setUrl', id, url]); },
      setTiles: (tiles) => { options.tiles = tiles; this.calls.push(['setTiles', id, tiles[0]]); },
    });
    this.calls.push(['addSource', id]);
  }

  removeSource(id) {
    if (this.layers.some(l => l.source === id)) throw new Error(`source ${id} in use`);
    this.sources.delete(id);
    this.calls.push(['removeSource', id]);
  }
}
