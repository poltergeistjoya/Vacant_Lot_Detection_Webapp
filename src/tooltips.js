export const TOOLTIPS = {
  naip: '2022 NAIP aerial imagery (60cm resolution). Toggle to see the satellite photo underneath predictions.',
  overlay_both: 'Vacant flagged lots flagged by both NYC PLUTO records and open source model predictions.',
  overlay_model: 'Vacant lots flagged by open source image segmentation model trained on NAIP data.',
  overlay_pluto: 'Vacant lots recorded in NYC\'s PLUTO tax-lot database.',
  error: 'Compares predictions against ground truth. Green = correctly detected (TP), Red = false alarm (FP), Blue = missed (FN).',
  roads: 'NYC planimetric road network. Shaded to match the non-vacant overlay so streets read as built environment.',
  parks: 'Official NYC parks and open spaces (DPR). Useful to distinguish maintained green space from vacant lots.',
  cd: 'NYC Community District boundaries. Click a district to zoom in and see its name in the footer.',
  parcels: 'MapPLUTO parcel boundaries and ownership data (NYC Dept of City Planning).',
  athletic: 'Athletic surfaces from OpenStreetMap (baseball diamonds, basketball courts, tennis courts, etc.). Visible at zoom 13+. Red = model falsely predicts vacant; Green = correctly classified. Updates with the threshold slider. Click any surface for details. OSM data date shown in footer when active.',
};
