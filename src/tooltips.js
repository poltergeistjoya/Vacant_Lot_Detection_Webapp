export const TOOLTIPS = {
  naip: '2022 NAIP aerial imagery (60cm resolution). Toggle to see the satellite photo underneath predictions.',
  overlay: 'Dark overlay shows areas the model predicts as non-vacant at the current confidence threshold. Clear areas are predicted vacant lots.',
  error: 'Compares predictions against ground truth. Green = correctly detected (TP), Red = false alarm (FP), Blue = missed (FN).',
  roads: 'NYC planimetric road network. Shaded to match the non-vacant overlay so streets read as built environment.',
  parks: 'Official NYC parks and open spaces (DPR). Useful to distinguish maintained green space from vacant lots.',
  cd: 'NYC Community District boundaries. Click a district to zoom in and see its name in the footer.',
  parcels: 'MapPLUTO parcel data (NYC Dept of City Planning). Visible at zoom 15+. Red = model + PLUTO agree it\'s vacant; Orange = model predicts but PLUTO doesn\'t record; Blue = PLUTO records but model missed. Click any lot for ownership details.',
};
