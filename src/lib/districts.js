import * as maplibregl from 'maplibre-gl';
import { CD_GEOJSON_URL, BRONX_CD_NAMES } from './layers.js';

/**
 * Add Community District boundaries to a MapLibre map.
 * Returns controls for updating styles and responding to selection.
 */
export async function addDistrictLayer(map, { onSelect, style: styleOverrides } = {}) {
  const resp = await fetch(CD_GEOJSON_URL);
  const geojson = await resp.json();

  const bronxFeatures = {
    type: 'FeatureCollection',
    features: geojson.features.filter(f => {
      const cd = f.properties.BoroCD;
      return cd >= 200 && cd < 300;
    }),
  };

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
  const popup = new maplibregl.Popup({
    closeButton: false,
    closeOnClick: false,
    offset: 12,
  });

  map.on('mousemove', 'cd-fill', (e) => {
    if (e.features.length === 0) return;
    map.getCanvas().style.cursor = 'pointer';

    const feat = e.features[0];
    const id = feat.properties.BoroCD;

    if (hoveredId !== null && hoveredId !== id) {
      map.setFeatureState({ source: 'districts', id: hoveredId }, { hover: false });
    }
    hoveredId = id;
    map.setFeatureState({ source: 'districts', id }, { hover: true });

    const cdNum = id % 100;
    const name = BRONX_CD_NAMES[id] || `District ${cdNum}`;
    popup
      .setLngLat(e.lngLat)
      .setHTML(`<strong>CD ${cdNum}</strong><br>${name}`)
      .addTo(map);
  });

  map.on('mouseleave', 'cd-fill', () => {
    map.getCanvas().style.cursor = '';
    if (hoveredId !== null) {
      map.setFeatureState({ source: 'districts', id: hoveredId }, { hover: false });
      hoveredId = null;
    }
    popup.remove();
  });

  // ── Click → zoom ──
  map.on('click', 'cd-fill', (e) => {
    if (e.features.length === 0) return;
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
        map.fitBounds(bounds, { padding: 40, duration: 600 });
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
