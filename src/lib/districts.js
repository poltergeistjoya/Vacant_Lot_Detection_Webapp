import * as maplibregl from 'maplibre-gl';
import { CD_GEOJSON_URL, BRONX_CD_NAMES } from './layers.js';

/**
 * Add Community District boundaries to a MapLibre map.
 * Returns controls for updating styles and responding to selection.
 */
const _cdDataPromise = fetch(CD_GEOJSON_URL)
  .then(r => r.json())
  .then(geojson => ({
    type: 'FeatureCollection',
    features: geojson.features.filter(f => {
      const cd = f.properties.BoroCD;
      return cd >= 200 && cd < 300;
    }),
  }));

export async function addDistrictLayer(map, { onSelect, style: styleOverrides } = {}) {
  const bronxFeatures = await _cdDataPromise;

  map.addSource('districts', {
    type: 'geojson',
    data: bronxFeatures,
    promoteId: 'BoroCD',
  });

  const s = { ...styleOverrides };

  map.addLayer({
    id: 'cd-fill',
    type: 'fill',
    source: 'districts',
    paint: {
      'fill-color': s.fillColor,
      'fill-opacity': [
        'case',
        ['boolean', ['feature-state', 'hover'], false],
        s.hoverFillOpacity,
        s.fillOpacity,
      ],
    },
  });

  map.addLayer({
    id: 'cd-line',
    type: 'line',
    source: 'districts',
    paint: {
      'line-color': s.strokeColor,
      'line-width': [
        'case',
        ['boolean', ['feature-state', 'hover'], false],
        s.hoverStrokeWidth,
        s.strokeWidth,
      ],
      'line-opacity': [
        'case',
        ['boolean', ['feature-state', 'hover'], false],
        s.hoverStrokeOpacity,
        s.strokeOpacity,
      ],
    },
  });

  // ── Hover ──
  let hoveredId = null;
  let selectedId = null;    // district clicked into; only its label goes quiet
  let selectedZoom = null;  // zoom at which that district fills the view
  // Slack before a zoom-out counts as leaving the district, so small nudges
  // around the fitted zoom don't flip the label on and off.
  const ZOOM_RELEASE = 0.5;
  let pointerInside = false;
  let lastPoint = null;
  const popup = new maplibregl.Popup({
    closeButton: false,
    closeOnClick: false,
    offset: 12,
    className: 'cd-tooltip',
  });

  // Once you have clicked into a district you know where you are, so its name
  // stops following the cursor. Every other district still labels itself.
  function showLabel(id, lngLat) {
    if (id === selectedId) {
      popup.remove();
      return;
    }
    const cdNum = id % 100;
    const name = BRONX_CD_NAMES[id] || `District ${cdNum}`;
    popup
      .setLngLat(lngLat)
      .setHTML(`<strong>CD ${cdNum}</strong><br>${name}`)
      .addTo(map);
  }

  function setHovered(id) {
    map.getCanvas().style.cursor = 'pointer';
    if (hoveredId !== null && hoveredId !== id) {
      map.setFeatureState({ source: 'districts', id: hoveredId }, { hover: false });
    }
    hoveredId = id;
    map.setFeatureState({ source: 'districts', id }, { hover: true });
  }

  map.on('mousemove', (e) => {
    pointerInside = true;
    lastPoint = e.point;
  });

  map.on('mousemove', 'cd-fill', (e) => {
    if (e.features.length === 0) return;
    const id = e.features[0].properties.BoroCD;
    setHovered(id);
    showLabel(id, e.lngLat);
  });

  map.on('mouseleave', 'cd-fill', () => {
    map.getCanvas().style.cursor = '';
    if (hoveredId !== null) {
      map.setFeatureState({ source: 'districts', id: hoveredId }, { hover: false });
      hoveredId = null;
    }
    popup.remove();
  });

  // A camera move under a stationary cursor fires no pointer event at all, which
  // is how a label gets stranded mid-map. Hide it for the duration, then resolve
  // it once the camera settles.
  map.on('movestart', () => { popup.remove(); });

  map.on('moveend', () => {
    // Zoomed back out past the district you clicked into: it is no longer where
    // you are, so it stops being the quiet one and labels itself again.
    if (selectedZoom !== null && map.getZoom() < selectedZoom - ZOOM_RELEASE) {
      selectedId = null;
      selectedZoom = null;
    }

    if (!pointerInside || !lastPoint) return;
    const feats = map.queryRenderedFeatures(lastPoint, { layers: ['cd-fill'] });
    // An empty result here is usually the source mid-retile, never a reason to
    // drop the highlight — only the pointer leaving a district does that.
    if (feats.length === 0) return;
    const id = feats[0].properties.BoroCD;
    setHovered(id);
    showLabel(id, map.unproject(lastPoint));
  });

  // A layer mouseleave is not guaranteed when the pointer exits the map itself.
  const canvasContainer = map.getCanvasContainer();
  canvasContainer.addEventListener('mouseenter', () => { pointerInside = true; });
  canvasContainer.addEventListener('mouseleave', () => {
    pointerInside = false;
    lastPoint = null;
  });

  // ── Click → zoom ──
  map.on('click', 'cd-fill', (e) => {
    if (e.features.length === 0) return;
    // Don't zoom to district when clicking a parcel
    if (map.getLayer('parcel-fill')) {
      const parcelFeats = map.queryRenderedFeatures(e.point, { layers: ['parcel-fill'] });
      if (parcelFeats.length > 0) return;
    }
    popup.remove();
    const id = e.features[0].properties.BoroCD;

    const fullFeat = bronxFeatures.features.find(f => f.properties.BoroCD === id);
    if (fullFeat) {
      const coords = [];
      const geom = fullFeat.geometry;
      if (geom.type === 'Polygon') {
        geom.coordinates[0].forEach(c => coords.push(c));
      } else if (geom.type === 'MultiPolygon') {
        geom.coordinates.forEach(poly => poly[0].forEach(c => coords.push(c)));
      }
      if (coords.length > 0) {
        const bounds = coords.reduce(
          (b, c) => b.extend(c),
          new maplibregl.LngLatBounds(coords[0], coords[0]),
        );
        const cam = map.cameraForBounds(bounds, { padding: 40 });
        const targetZoom = cam ? cam.zoom : map.getZoom();
        const alreadySelected = selectedId === id;
        selectedId = id;
        selectedZoom = targetZoom;
        if (!alreadySelected || map.getZoom() <= targetZoom) {
          map.fitBounds(bounds, { padding: 40, duration: 600 });
        }
      }
    }

    if (onSelect) onSelect(id, fullFeat || e.features[0]);
  });

  // ── Style update API ──
  function updateStyle(newStyle) {
    Object.assign(s, newStyle);

    map.setPaintProperty('cd-fill', 'fill-color', s.fillColor);
    map.setPaintProperty('cd-fill', 'fill-opacity', [
      'case',
      ['boolean', ['feature-state', 'hover'], false],
      s.hoverFillOpacity,
      s.fillOpacity,
    ]);

    map.setPaintProperty('cd-line', 'line-color', s.strokeColor);
    map.setPaintProperty('cd-line', 'line-width', [
      'case',
      ['boolean', ['feature-state', 'hover'], false],
      s.hoverStrokeWidth,
      s.strokeWidth,
    ]);
    map.setPaintProperty('cd-line', 'line-opacity', [
      'case',
      ['boolean', ['feature-state', 'hover'], false],
      s.hoverStrokeOpacity,
      s.strokeOpacity,
    ]);
  }

  return { updateStyle, getStyle: () => ({ ...s }) };
}
