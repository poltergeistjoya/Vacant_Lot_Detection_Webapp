import * as maplibregl from 'maplibre-gl';
import { PARCELS_GEOJSON_URL } from './layers.js';

const CATEGORY_COLORS = {
  both:       '#ef4444',  // red   — model + PLUTO agree
  model_only: '#f97316',  // orange — model predicts, PLUTO doesn't record
  pluto_only: '#3b82f6',  // blue  — PLUTO records, model missed
};

const DEFAULT_COLOR = '#888888';

function categoryColor(category) {
  return [
    'match', ['get', 'vacancy_category'],
    'both',       CATEGORY_COLORS.both,
    'model_only', CATEGORY_COLORS.model_only,
    'pluto_only', CATEGORY_COLORS.pluto_only,
    DEFAULT_COLOR,
  ];
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

function categoryLabel(cat) {
  if (cat === 'both')       return 'Predicted vacant + PLUTO recorded';
  if (cat === 'model_only') return 'Model predicted only';
  if (cat === 'pluto_only') return 'PLUTO recorded only';
  return cat;
}

export async function addParcelLayer(map) {
  let geojson;
  try {
    const resp = await fetch(PARCELS_GEOJSON_URL);
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    geojson = await resp.json();
  } catch (err) {
    console.warn('parcels.geojson unavailable — parcel layer disabled.', err);
    return;
  }

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
      minzoom: 15,
      layout: { visibility: 'none' },
      paint: {
        'fill-color': categoryColor(),
        'fill-opacity': [
          'case',
          ['boolean', ['feature-state', 'hover'], false],
          0.55,
          0.30,
        ],
      },
    },
    'cd-fill',
  );

  map.addLayer(
    {
      id: 'parcel-line',
      type: 'line',
      source: 'parcels',
      minzoom: 15,
      layout: { visibility: 'none' },
      paint: {
        'line-color': categoryColor(),
        'line-width': [
          'case',
          ['boolean', ['feature-state', 'hover'], false],
          2,
          0.8,
        ],
        'line-opacity': 0.8,
      },
    },
    'cd-fill',
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
    const cat  = categoryLabel(feat.properties.vacancy_category);
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

    const p = e.features[0].properties;
    const rows = [
      ['Address',      p.address || '—'],
      ['BBL',          p.bbl || '—'],
      ['Owner',        p.owner_name || '—'],
      ['Owner type',   ownerTypeLabel(p.owner_type)],
      ['Lot area',     p.lot_area ? `${Number(p.lot_area).toLocaleString()} sq ft` : '—'],
      ['Zoning',       p.zoning || '—'],
      ['Land use',     p.land_use || '—'],
      ['Vacancy',      categoryLabel(p.vacancy_category)],
    ];

    const tableRows = rows
      .map(([k, v]) => `<tr><td class="pk">${k}</td><td class="pv">${v}</td></tr>`)
      .join('');

    clickPopup.setLngLat(e.lngLat)
      .setHTML(`<table class="parcel-table">${tableRows}</table>`)
      .addTo(map);
  });
}
