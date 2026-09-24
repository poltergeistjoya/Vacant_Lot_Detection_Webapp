import * as maplibregl from 'maplibre-gl';
import { PARCELS_GEOJSON_URL } from './layers.js';

const DEFAULT_COVERAGE = 0.20;

const COLORS = {
  both:       '#22c55e',
  model_only: '#f97316',
  pluto_only: '#3b82f6',
};

let _currentTStr = 't0298';
let _currentSource = 'both';
let _metadata = null;
let _coverageThreshold = DEFAULT_COVERAGE;
let _geojson = null;

function filterExpr(tStr, source) {
  const isModel = ['>=', ['get', tStr], _coverageThreshold];
  const isPluto = ['==', ['get', 'pluto_vacant'], true];
  if (source === 'model') return isModel;
  if (source === 'pluto') return isPluto;
  return ['any', isPluto, isModel];
}

function colorExpr(tStr, source) {
  const isModel = ['>=', ['get', tStr], _coverageThreshold];
  const isPluto = ['==', ['get', 'pluto_vacant'], true];
  if (source === 'model') return COLORS.model_only;
  if (source === 'pluto') return COLORS.pluto_only;
  return [
    'case',
    ['all', isPluto, isModel], COLORS.both,
    isModel, COLORS.model_only,
    COLORS.pluto_only,
  ];
}

const LAND_USE_LABELS = {
  '01': 'One & Two Family Buildings',
  '02': 'Multi-Family Walk-Up Buildings',
  '03': 'Multi-Family Elevator Buildings',
  '04': 'Mixed Residential & Commercial',
  '05': 'Commercial & Office Buildings',
  '06': 'Industrial & Manufacturing',
  '07': 'Transportation & Utility',
  '08': 'Public Facilities & Institutions',
  '09': 'Open Space & Outdoor Recreation',
  '10': 'Parking Facilities',
  '11': 'Vacant Land',
};

function landUseLabel(code) {
  if (!code) return '—';
  const key = String(code).padStart(2, '0');
  const label = LAND_USE_LABELS[key];
  return label ? `${key} — ${label}` : code;
}

function ownerTypeLabel(code) {
  const map = {
    C: 'City of New York',
    M: 'Mixed city/private',
    O: 'Other public',
    P: 'Private',
    X: 'Fully tax-exempt',
  };
  return map[code] || code || 'Unknown';
}

function categoryLabel(isPluto, isModel) {
  if (isPluto && isModel) return 'Predicted vacant + PLUTO recorded';
  if (isModel) return 'Model predicted only';
  return 'PLUTO recorded only';
}

export async function addParcelLayer(map, initialTStr) {
  _currentTStr = initialTStr || 't0298';

  let geojson;
  try {
    const resp = await fetch(PARCELS_GEOJSON_URL);
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    geojson = await resp.json();
  } catch (err) {
    console.warn('parcels.geojson unavailable — parcel layer disabled.', err);
    return null;
  }

  _geojson = geojson;
  _metadata = geojson.metadata || {};
  _coverageThreshold = _metadata.coverage_threshold || DEFAULT_COVERAGE;
  const plutoVersion = _metadata.pluto_version || 'unknown';
  const counts = _metadata.counts_by_threshold || {};

  map.addSource('parcels', {
    type: 'geojson',
    data: geojson,
    promoteId: 'bbl',
  });

  map.addLayer(
    {
      id: 'parcel-fill',
      type: 'fill',
      source: 'parcels',
      minzoom: 12,
      layout: { visibility: 'none' },
      filter: filterExpr(_currentTStr, _currentSource),
      paint: {
        'fill-color': colorExpr(_currentTStr, _currentSource),
        'fill-opacity': [
          'case',
          ['boolean', ['feature-state', 'hover'], false],
          0.30,
          0.12,
        ],
      },
    },
    map.getLayer('cd-fill') ? 'cd-fill' : undefined,
  );

  map.addLayer(
    {
      id: 'parcel-line',
      type: 'line',
      source: 'parcels',
      minzoom: 12,
      layout: { visibility: 'none' },
      filter: filterExpr(_currentTStr, _currentSource),
      paint: {
        'line-color': colorExpr(_currentTStr, _currentSource),
        'line-width': [
          'case',
          ['boolean', ['feature-state', 'hover'], false],
          3,
          1.5,
        ],
        'line-opacity': 0.8,
      },
    },
    map.getLayer('cd-fill') ? 'cd-fill' : undefined,
  );

  // ── Hover tooltip ─────────────────────────────────
  let hoveredBbl = null;
  const tooltip = new maplibregl.Popup({
    closeButton: false,
    closeOnClick: false,
    offset: 10,
    className: 'parcel-tooltip',
  });

  map.on('mousemove', 'parcel-fill', (e) => {
    if (!e.features.length) return;
    map.getCanvas().style.cursor = 'pointer';

    const feat = e.features[0];
    const bbl = feat.properties.bbl;

    if (hoveredBbl !== null && hoveredBbl !== bbl) {
      map.setFeatureState({ source: 'parcels', id: hoveredBbl }, { hover: false });
    }
    hoveredBbl = bbl;
    map.setFeatureState({ source: 'parcels', id: bbl }, { hover: true });

    const addr = feat.properties.address || 'No address';
    const cov = feat.properties[_currentTStr] || 0;
    const isModel = cov >= _coverageThreshold;
    const isPluto = feat.properties.pluto_vacant === true;
    const cat = categoryLabel(isPluto, isModel);
    tooltip.setLngLat(e.lngLat)
      .setHTML(`<strong>${addr}</strong><br><span class="parcel-cat">${cat}</span>`)
      .addTo(map);
  });

  map.on('mouseleave', 'parcel-fill', () => {
    map.getCanvas().style.cursor = '';
    if (hoveredBbl !== null) {
      map.setFeatureState({ source: 'parcels', id: hoveredBbl }, { hover: false });
      hoveredBbl = null;
    }
    tooltip.remove();
  });

  // ── Click → ownership popup ───────────────────────
  const clickPopup = new maplibregl.Popup({
    closeButton: true,
    closeOnClick: true,
    className: 'parcel-popup',
    maxWidth: '280px',
  });

  map.on('click', 'parcel-fill', (e) => {
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
    const isModel = cov >= _coverageThreshold;
    const isPluto = p.pluto_vacant === true;
    const rows = [
      ['Address',      p.address || '—'],
      ['BBL',          p.bbl || '—'],
      ['Owner',        p.owner_name || '—'],
      ['Owner type',   ownerTypeLabel(p.owner_type)],
      ['Lot area',     p.lot_area ? `${Number(p.lot_area).toLocaleString()} sq ft` : '—'],
      ['Zoning',       p.zoning || '—'],
      ['Land use',     landUseLabel(p.land_use)],
      ['Coverage',     cov > 0 ? `${(cov * 100).toFixed(1)}%` : '—'],
      ['Vacancy',      categoryLabel(isPluto, isModel)],
    ];

    const tableRows = rows
      .map(([k, v]) => `<tr><td class="pk">${k}</td><td class="pv">${v}</td></tr>`)
      .join('');

    clickPopup.setLngLat(e.lngLat)
      .setHTML(`<table class="parcel-table">${tableRows}</table>`)
      .addTo(map);
  });

  return {
    count: counts[_currentTStr] || geojson.features.length,
    version: plutoVersion,
    counts,
  };
}

function isVacantAt(props, tStr) {
  return props.pluto_vacant === true || (props[tStr] || 0) >= _coverageThreshold;
}

/** Whether parcels.geojson carries the district code (added 2026-09-22). */
export function hasDistrictField() {
  return !!_geojson?.features?.length
    && _geojson.features[0].properties.cd !== undefined;
}

/**
 * Count vacant parcels at the current threshold, optionally scoped to one
 * community district. Returns null when parcel data never loaded.
 */
export function countParcels({ cd = null } = {}) {
  if (!_geojson) return null;
  if (cd === null && _currentSource === 'both') {
    return _metadata?.counts_by_threshold?.[_currentTStr] ?? 0;
  }
  let n = 0;
  for (const f of _geojson.features) {
    const props = f.properties;
    if (cd !== null && Number(props.cd) !== Number(cd)) continue;
    if (_currentSource === 'model') {
      if ((props[_currentTStr] || 0) < _coverageThreshold) continue;
    } else if (_currentSource === 'pluto') {
      if (!props.pluto_vacant) continue;
    } else {
      if (!isVacantAt(props, _currentTStr)) continue;
    }
    n++;
  }
  return n;
}

export function updateParcelThreshold(map, tStr) {
  _currentTStr = tStr;
  if (!map.getLayer('parcel-fill')) return null;

  map.setFilter('parcel-fill', filterExpr(tStr, _currentSource));
  map.setFilter('parcel-line', filterExpr(tStr, _currentSource));
  map.setPaintProperty('parcel-fill', 'fill-color', colorExpr(tStr, _currentSource));
  map.setPaintProperty('parcel-line', 'line-color', colorExpr(tStr, _currentSource));

  return _metadata?.counts_by_threshold?.[tStr] || 0;
}

export function updateParcelSource(map, source) {
  _currentSource = source;
  if (!map.getLayer('parcel-fill')) return;

  map.setFilter('parcel-fill', filterExpr(_currentTStr, source));
  map.setFilter('parcel-line', filterExpr(_currentTStr, source));
  map.setPaintProperty('parcel-fill', 'fill-color', colorExpr(_currentTStr, source));
  map.setPaintProperty('parcel-line', 'line-color', colorExpr(_currentTStr, source));
}
