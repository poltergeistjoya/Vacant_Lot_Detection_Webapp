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

export default {
  root: 'src',
  publicDir: '../data',
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
        playground: path.resolve(__dirname, 'src/playground.html'),
      },
    },
  },
  plugins: [maplibreWorkerPlugin(), {
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
