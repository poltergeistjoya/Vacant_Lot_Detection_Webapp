import * as maplibregl from 'maplibre-gl';
import { ATHLETIC_GEOJSON_URL } from './layers.js';

const DEFAULT_COVERAGE = 0.20;

const COLORS = {
  false_positive: '#e11d48',
  clean:          '#10b981',
};

const SPORT_LABELS = {
  baseball: 'Baseball',
  softball: 'Softball',
  basketball: 'Basketball',
  tennis: 'Tennis',
  soccer: 'Soccer',
  american_football: 'Football',
  athletics: 'Track & Field',
  running: 'Running Track',
  multi: 'Multi-sport',
};

let _currentTStr = 't0298';
let _metadata = null;
let _coverageThreshold = DEFAULT_COVERAGE;
let _queryDate = null;

function sportLabel(sport) {
  if (!sport) return 'Unknown';
  return SPORT_LABELS[sport] || sport.charAt(0).toUpperCase() + sport.slice(1);
}

function colorExpr(tStr) {
  return [
    'case',
    ['>=', ['get', tStr], _coverageThreshold],
    COLORS.false_positive,
    COLORS.clean,
  ];
}

export async function addAthleticLayer(map, initialTStr) {
  _currentTStr = initialTStr || 't0298';

  let geojson;
  try {
    const resp = await fetch(ATHLETIC_GEOJSON_URL);
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    geojson = await resp.json();
  } catch (err) {
    console.warn('athletic_surfaces_enriched.geojson unavailable — athletic layer disabled.', err);
    return null;
  }

  _metadata = geojson.metadata || {};
  _coverageThreshold = _metadata.coverage_threshold || DEFAULT_COVERAGE;
  _queryDate = _metadata.query_date || null;
  const counts = _metadata.counts_by_threshold || {};

  map.addSource('athletic', {
    type: 'geojson',
    data: geojson,
    generateId: true,
  });

  map.addLayer(
    {
      id: 'athletic-fill',
      type: 'fill',
      source: 'athletic',
      minzoom: 13,
      layout: { visibility: 'none' },
      paint: {
        'fill-color': colorExpr(_currentTStr),
        'fill-opacity': [
          'case',
          ['boolean', ['feature-state', 'hover'], false],
          0.45,
          0.25,
        ],
      },
    },
    map.getLayer('cd-fill') ? 'cd-fill' : undefined,
  );

  map.addLayer(
    {
      id: 'athletic-line',
      type: 'line',
      source: 'athletic',
      minzoom: 13,
      layout: { visibility: 'none' },
      paint: {
        'line-color': colorExpr(_currentTStr),
        'line-width': [
          'case',
          ['boolean', ['feature-state', 'hover'], false],
          2.5,
          1,
        ],
        'line-opacity': 0.9,
      },
    },
    map.getLayer('cd-fill') ? 'cd-fill' : undefined,
  );

  // ── Hover tooltip ─────────────────────────────────
  let hoveredId = null;
  const tooltip = new maplibregl.Popup({
    closeButton: false,
    closeOnClick: false,
    offset: 10,
    className: 'parcel-tooltip',
  });

  map.on('mousemove', 'athletic-fill', (e) => {
    if (!e.features.length) return;
    map.getCanvas().style.cursor = 'pointer';

    const feat = e.features[0];
    const id = feat.id;

    if (hoveredId !== null && hoveredId !== id) {
      map.setFeatureState({ source: 'athletic', id: hoveredId }, { hover: false });
    }
    hoveredId = id;
    map.setFeatureState({ source: 'athletic', id }, { hover: true });

    const p = feat.properties;
    const sport = sportLabel(p.sport);
    const name = p.name || sport;
    const cov = p[_currentTStr] || 0;
    const status = cov >= _coverageThreshold ? 'Model thinks vacant' : 'Not flagged';
    tooltip.setLngLat(e.lngLat)
      .setHTML(`<strong>${name}</strong><br><span class="parcel-cat">${sport} · ${status}</span>`)
      .addTo(map);
  });

  map.on('mouseleave', 'athletic-fill', () => {
    map.getCanvas().style.cursor = '';
    if (hoveredId !== null) {
      map.setFeatureState({ source: 'athletic', id: hoveredId }, { hover: false });
      hoveredId = null;
    }
    tooltip.remove();
  });

  // ── Click popup ───────────────────────────────────
  const clickPopup = new maplibregl.Popup({
    closeButton: true,
    closeOnClick: true,
    className: 'parcel-popup',
    maxWidth: '280px',
  });

  map.on('click', 'athletic-fill', (e) => {
    if (!e.features.length) return;
    tooltip.remove();

    const feat = e.features[0];
    const geom = feat.geometry;
    if (geom) {
      const coords = [];
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
        map.fitBounds(bounds, { padding: 60, maxZoom: 18, duration: 400 });
      }
    }

    const p = feat.properties;
    const cov = p[_currentTStr] || 0;
    const rows = [
      ['Name',     p.name || '—'],
      ['Sport',    sportLabel(p.sport)],
      ['Surface',  p.surface || '—'],
      ['Coverage', cov > 0 ? `${(cov * 100).toFixed(1)}%` : '—'],
      ['Status',   cov >= _coverageThreshold ? 'False positive' : 'Clean'],
      ['OSM ID',   p.osm_id || '—'],
    ];

    const tableRows = rows
      .map(([k, v]) => `<tr><td class="pk">${k}</td><td class="pv">${v}</td></tr>`)
      .join('');

    clickPopup.setLngLat(e.lngLat)
      .setHTML(`<table class="parcel-table">${tableRows}</table>`)
      .addTo(map);
  });

  return {
    count: counts[_currentTStr] || 0,
    counts,
    queryDate: _queryDate,
  };
}

export function updateAthleticThreshold(map, tStr) {
  _currentTStr = tStr;
  if (!map.getLayer('athletic-fill')) return null;

  map.setPaintProperty('athletic-fill', 'fill-color', colorExpr(tStr));
  map.setPaintProperty('athletic-line', 'line-color', colorExpr(tStr));

  return _metadata?.counts_by_threshold?.[tStr] || 0;
}
