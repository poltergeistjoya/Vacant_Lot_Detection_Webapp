export const TOOLTIPS = {
  naip: '2022 NAIP aerial imagery (60cm resolution). Toggle to see the satellite photo underneath predictions.',
  overlay: 'Vacant lot overlay combining model predictions and PLUTO records by default. Use the source selector below to show model only, PLUTO only, or both. Dark areas are non-vacant; clear areas are vacant. Roads and athletic surfaces (baseball diamonds, courts, etc.) are excluded.',
  error: 'Compares predictions against ground truth. Green = correctly detected (TP), Red = false alarm (FP), Blue = missed (FN).',
  roads: 'NYC planimetric road network. Shaded to match the non-vacant overlay so streets read as built environment.',
  parks: 'Official NYC parks and open spaces (DPR). Useful to distinguish maintained green space from vacant lots.',
  cd: 'NYC Community District boundaries. Click a district to zoom in and see its name in the footer.',
  parcels: 'MapPLUTO parcel boundaries and ownership data (NYC Dept of City Planning). Visible at zoom 12+. Colors show vacancy agreement: Red = model + PLUTO agree; Orange = model only; Blue = PLUTO only. Does not affect the raster overlay. Click any lot for details.',
  athletic: 'Athletic surfaces from OpenStreetMap (baseball diamonds, basketball courts, tennis courts, etc.). Visible at zoom 13+. Red = model falsely predicts vacant; Green = correctly classified. Updates with the threshold slider. Click any surface for details. OSM data date shown in footer when active.',
};
