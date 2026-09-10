import L from 'leaflet';

const BRONX_CD_NAMES = {
  201: 'Mott Haven / Melrose',
  202: 'Hunts Point / Longwood',
  203: 'Morrisania / Crotona',
  204: 'Highbridge / Concourse',
  205: 'Fordham / University Heights',
  206: 'Belmont / East Tremont',
  207: 'Kingsbridge / Riverdale',
  208: 'Riverdale / Fieldston',
  209: 'Parkchester / Soundview',
  210: 'Throgs Neck / Co-op City',
  211: 'Morris Park / Pelham Parkway',
  212: 'Williamsbridge / Baychester',
  226: 'Van Cortlandt Park',
  227: 'Bronx Park / NY Botanical Garden',
  228: 'Pelham Bay Park',
};

export const DISTRICT_DEFAULTS = {
  fillColor: '#4fc3f7',
  fillOpacity: 0.08,
  strokeColor: '#4fc3f7',
  strokeWidth: 2,
  strokeOpacity: 0.6,

  hoverFillOpacity: 0.25,
  hoverStrokeWidth: 4,
  hoverStrokeOpacity: 1.0,
  hoverSaturate: 1.5,
  hoverScale: 1.02,
  hoverScaleEnabled: false,
  hoverLabelEnabled: true,
};

export function getCDName(boroCD) {
  return BRONX_CD_NAMES[boroCD] || `CD ${boroCD}`;
}

export function isBronxCD(feature) {
  const cd = feature.properties.BoroCD;
  return cd >= 200 && cd < 300;
}

export class DistrictLayer {
  constructor(map, opts = {}) {
    this._map = map;
    this._state = { ...DISTRICT_DEFAULTS, ...opts };
    this._layer = null;
    this._label = null;
    this._hoveredLayer = null;
  }

  async load(url) {
    const resp = await fetch(url);
    const geojson = await resp.json();

    const bronxFeatures = {
      type: 'FeatureCollection',
      features: geojson.features.filter(isBronxCD),
    };

    this._map.createPane('districtPane');
    this._map.getPane('districtPane').style.zIndex = 460;

    this._layer = L.geoJSON(bronxFeatures, {
      pane: 'districtPane',
      style: () => this._baseStyle(),
      onEachFeature: (feature, layer) => {
        layer.on('mouseover', () => this._onHover(feature, layer));
        layer.on('mouseout', () => this._onHoverEnd(layer));
      },
    }).addTo(this._map);

    this._label = L.tooltip({
      className: 'cd-label',
      direction: 'center',
      permanent: false,
      sticky: false,
    });
  }

  _baseStyle() {
    return {
      fillColor: this._state.fillColor,
      fillOpacity: this._state.fillOpacity,
      color: this._state.strokeColor,
      weight: this._state.strokeWidth,
      opacity: this._state.strokeOpacity,
    };
  }

  _onHover(feature, layer) {
    if (this._hoveredLayer) {
      this._onHoverEnd(this._hoveredLayer);
    }
    this._hoveredLayer = layer;

    layer.setStyle({
      fillOpacity: this._state.hoverFillOpacity,
      weight: this._state.hoverStrokeWidth,
      opacity: this._state.hoverStrokeOpacity,
    });
    layer.bringToFront();

    const el = layer.getElement();
    if (el) {
      el.style.filter = `saturate(${this._state.hoverSaturate})`;
      if (this._state.hoverScaleEnabled) {
        const bounds = layer.getBounds();
        const center = this._map.latLngToLayerPoint(bounds.getCenter());
        el.style.transformOrigin = `${center.x}px ${center.y}px`;
        el.style.transform = `scale(${this._state.hoverScale})`;
        el.style.transition = 'transform 0.15s ease';
      }
    }

    if (this._state.hoverLabelEnabled) {
      const name = getCDName(feature.properties.BoroCD);
      const cd = feature.properties.BoroCD;
      const label = `<strong>CD ${cd % 100}</strong><br>${name}`;
      layer.bindTooltip(label, {
        className: 'cd-label',
        direction: 'center',
        sticky: false,
      }).openTooltip();
    }
  }

  _onHoverEnd(layer) {
    if (this._hoveredLayer === layer) {
      this._hoveredLayer = null;
    }

    layer.setStyle(this._baseStyle());

    const el = layer.getElement();
    if (el) {
      el.style.filter = '';
      el.style.transform = '';
      el.style.transition = '';
      el.style.transformOrigin = '';
    }

    layer.unbindTooltip();
  }

  update(newState) {
    Object.assign(this._state, newState);
    if (this._layer) {
      this._layer.setStyle(() => this._baseStyle());
    }
  }

  getState() {
    return { ...this._state };
  }
}
