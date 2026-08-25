// Canvas prep for the vacancy mask's *boundary* effects (outline, glow,
// shadow). The interior treatment is handled separately by clipping a
// filtered copy of the Esri tile layer to the mask via CSS mask-image.

function loadImage(url) {
  return new Promise((resolve, reject) => {
    const img = new Image();
    img.onload = () => resolve(img);
    img.onerror = reject;
    img.src = url;
  });
}

function tint(srcCanvas, color, alpha, width, height) {
  const out = document.createElement('canvas');
  out.width = width;
  out.height = height;
  const ctx = out.getContext('2d');
  ctx.fillStyle = color;
  ctx.globalAlpha = alpha;
  ctx.fillRect(0, 0, width, height);
  ctx.globalAlpha = 1;
  ctx.globalCompositeOperation = 'destination-in';
  ctx.drawImage(srcCanvas, 0, 0);
  return out;
}

const NEIGHBOR_OFFSETS = [
  [0, 0], [-1, -1], [0, -1], [1, -1],
  [-1, 0], [1, 0], [-1, 1], [0, 1], [1, 1],
];

function dilateOnce(srcCanvas, width, height) {
  const out = document.createElement('canvas');
  out.width = width;
  out.height = height;
  const ctx = out.getContext('2d');
  for (const [dx, dy] of NEIGHBOR_OFFSETS) ctx.drawImage(srcCanvas, dx, dy);
  return out;
}

export class VacancyBoundary {
  constructor() {
    this.width = 0;
    this.height = 0;
    this.maskCanvas = null;
    this.outlineCanvas = document.createElement('canvas');
    this.glowCanvas = document.createElement('canvas');
    this.shadowCanvas = document.createElement('canvas');
    this._ringWidth = null;
    this._ringCanvas = null;
  }

  async load(url) {
    const img = await loadImage(url);
    this.width = img.naturalWidth;
    this.height = img.naturalHeight;
    for (const c of [this.outlineCanvas, this.glowCanvas, this.shadowCanvas]) {
      c.width = this.width;
      c.height = this.height;
    }
    const c = document.createElement('canvas');
    c.width = this.width;
    c.height = this.height;
    c.getContext('2d').drawImage(img, 0, 0);
    this.maskCanvas = c;
  }

  _getRing(width) {
    const w = Math.max(1, Math.round(width));
    if (this._ringWidth === w && this._ringCanvas) return this._ringCanvas;
    let dilated = this.maskCanvas;
    for (let i = 0; i < w; i++) dilated = dilateOnce(dilated, this.width, this.height);
    const ring = document.createElement('canvas');
    ring.width = this.width;
    ring.height = this.height;
    const ctx = ring.getContext('2d');
    ctx.drawImage(dilated, 0, 0);
    ctx.globalCompositeOperation = 'destination-out';
    ctx.drawImage(this.maskCanvas, 0, 0);
    this._ringWidth = w;
    this._ringCanvas = ring;
    return ring;
  }

  renderOutline({ outlineColor, outlineWidth }) {
    if (!this.maskCanvas) return;
    const ring = this._getRing(outlineWidth);
    const tinted = tint(ring, outlineColor, 1, this.width, this.height);
    const ctx = this.outlineCanvas.getContext('2d');
    ctx.clearRect(0, 0, this.width, this.height);
    ctx.drawImage(tinted, 0, 0);
  }

  renderGlow({ glowColor, glowStrength }) {
    if (!this.maskCanvas) return;
    const tinted = tint(this.maskCanvas, glowColor, glowStrength, this.width, this.height);
    const ctx = this.glowCanvas.getContext('2d');
    ctx.clearRect(0, 0, this.width, this.height);
    ctx.drawImage(tinted, 0, 0);
  }

  renderShadow({ shadowStrength }) {
    if (!this.maskCanvas) return;
    const tinted = tint(this.maskCanvas, '#000000', shadowStrength, this.width, this.height);
    const ctx = this.shadowCanvas.getContext('2d');
    ctx.clearRect(0, 0, this.width, this.height);
    ctx.drawImage(tinted, 0, 0);
  }
}
