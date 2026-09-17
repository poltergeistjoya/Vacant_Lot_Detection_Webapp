export const TOOLTIPS = {
  naip: '2022 NAIP aerial imagery (60cm resolution). Toggle to see the satellite photo underneath predictions.',
  overlay: 'Pixels predicted as vacant by an open-source image segmentation model trained on NAIP aerial imagery at 0.6 m resolution. Dark areas are non-vacant; clear areas are predicted vacant lots at the current confidence threshold.',
  error: 'Compares predictions against ground truth. Green = correctly detected (TP), Red = false alarm (FP), Blue = missed (FN).',
  roads: 'NYC planimetric road network. Shaded to match the non-vacant overlay so streets read as built environment.',
  parks: 'Official NYC parks and open spaces (DPR). Useful to distinguish maintained green space from vacant lots.',
  cd: 'NYC Community District boundaries. Click a district to zoom in and see its name in the footer.',
  parcels: 'MapPLUTO parcel data (NYC Dept of City Planning). Visible at zoom 14+. A parcel is classified as model-vacant when at least 20% of its land area is predicted vacant at the current confidence threshold. Colors update as you move the slider. Red = model + PLUTO agree; Orange = model only; Blue = PLUTO only. Click any lot for details.',
};
