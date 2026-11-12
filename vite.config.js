import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));

function maplibreWorkerPlugin() {
  const mlDist = path.resolve(__dirname, 'node_modules/maplibre-gl/dist');
  return {
    name: 'copy-maplibre-worker',
    generateBundle() {
      for (const file of ['maplibre-gl-worker.mjs', 'maplibre-gl-shared.mjs']) {
        this.emitFile({
          type: 'asset',
          fileName: `assets/${file}`,
          source: fs.readFileSync(path.join(mlDist, file)),
        });
      }
    },
  };
}

// Files from data/ the frontend fetches, served at the site root. Only these are served
// and built, not all of data/ (masks, loose tiles and archives stay local).
const DATA_DIR = path.resolve(__dirname, 'data');
const WEB_DATA = [
  'thresholds.json', 'product_treatment.json',
  'community_districts.geojson', 'parcels.geojson', 'athletic_surfaces_enriched.geojson',
];
// Playground only (dev server; the playground isn't built)
const DEV_DATA = ['masks/boundary.png', 'masks/bounds.json'];
const CONTENT_TYPES = { '.json': 'application/json', '.geojson': 'application/geo+json', '.png': 'image/png' };

function dataFilesPlugin() {
  return {
    name: 'data-files',
    configureServer(server) {
      const served = new Set([...WEB_DATA, ...DEV_DATA]);
      server.middlewares.use((req, res, next) => {
        const name = decodeURIComponent(req.url.split('?')[0]).replace(/^\//, '');
        const file = path.join(DATA_DIR, name);
        if (!served.has(name) || !fs.existsSync(file)) return next();
        res.setHeader('Content-Type', CONTENT_TYPES[path.extname(name)]);
        fs.createReadStream(file).pipe(res);
      });
    },
    generateBundle() {
      for (const name of WEB_DATA) {
        const file = path.join(DATA_DIR, name);
        if (!fs.existsSync(file)) {
          this.warn(`data/${name} not found, not included in the build`);
          continue;
        }
        this.emitFile({ type: 'asset', fileName: name, source: fs.readFileSync(file) });
      }
    },
  };
}

export default {
  root: 'src',
  publicDir: false,
  server: {
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
    },
  },
  optimizeDeps: {
    exclude: ['maplibre-gl'],
  },
  build: {
    outDir: '../dist',
    emptyOutDir: true,
    rollupOptions: {
      input: {
        main: path.resolve(__dirname, 'src/index.html'),
      },
    },
  },
  plugins: [maplibreWorkerPlugin(), dataFilesPlugin(), {
    name: 'serve-tiles',
    configureServer(server) {
      server.middlewares.use('/tiles', (req, res, next) => {
        const filePath = path.resolve(__dirname, 'tiles', req.url.slice(1));
        if (fs.existsSync(filePath)) {
          res.setHeader('Content-Type', 'image/png');
          res.setHeader('Cache-Control', 'public, max-age=3600');
          fs.createReadStream(filePath).pipe(res);
        } else {
          res.statusCode = 404;
          res.end();
        }
      });

      server.middlewares.use((req, res, next) => {
        if (req.url === '/playground' || req.url === '/playground/') {
          req.url = '/playground.html';
        }
        next();
      });
    },
  }],
};
