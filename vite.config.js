import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));

export default {
  root: 'src',
  publicDir: '../data',
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
  plugins: [{
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

      // SPA-style fallback: /playground → /playground.html
      server.middlewares.use((req, res, next) => {
        if (req.url === '/playground' || req.url === '/playground/') {
          req.url = '/playground.html';
        }
        next();
      });
    },
  }],
};
