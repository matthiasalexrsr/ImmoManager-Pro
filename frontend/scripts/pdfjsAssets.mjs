import { createReadStream, readFileSync, readdirSync } from 'node:fs';
import { createRequire } from 'node:module';
import { dirname, join, extname } from 'node:path';

// PDF.js workers request some decoders by their original filename, so those
// resources need a stable, versioned directory rather than individually hashed URLs.
export default function pdfjsAssets() {
  const require = createRequire(import.meta.url);
  const root = dirname(require.resolve('pdfjs-dist/package.json'));
  const { version } = JSON.parse(readFileSync(join(root, 'package.json'), 'utf8'));
  const prefix = `pdfjs/${version}/`;
  const files = new Map([['LICENSE', join(root, 'LICENSE')]]);
  for (const directory of ['cmaps', 'standard_fonts', 'wasm', 'iccs']) {
    for (const entry of readdirSync(join(root, directory), { withFileTypes: true })) {
      if (entry.isFile()) files.set(`${directory}/${entry.name}`, join(root, directory, entry.name));
    }
  }
  const mime = { '.js': 'text/javascript', '.wasm': 'application/wasm', '.ttf': 'font/ttf', '.pfb': 'application/octet-stream', '.icc': 'application/vnd.iccprofile', '.bcmap': 'application/octet-stream' };
  return {
    name: 'local-pdfjs-assets',
    config(config) {
      return { define: { 'import.meta.env.PDFJS_ASSET_PATH': JSON.stringify(`${config.base || '/'}${prefix}`) } };
    },
    configureServer(server) {
      const routes = new Map([...files].map(([name, path]) => [`${server.config.base}${prefix}${name}`, path]));
      server.middlewares.use((request, response, next) => {
        if (!['GET', 'HEAD'].includes(request.method)) return next();
        let path;
        try { path = decodeURIComponent(new URL(request.url, 'http://localhost').pathname); } catch { return next(); }
        // Exact allowlist lookup: request paths are never joined to a filesystem path.
        const file = routes.get(path);
        if (!file) return next();
        response.setHeader('Content-Type', mime[extname(file)] || 'text/plain; charset=utf-8');
        response.setHeader('X-Content-Type-Options', 'nosniff');
        if (request.method === 'HEAD') return response.end();
        createReadStream(file).on('error', () => { response.statusCode = 500; response.end(); }).pipe(response);
      });
    },
    generateBundle() {
      for (const [name, path] of files) this.emitFile({ type: 'asset', fileName: `${prefix}${name}`, source: readFileSync(path) });
    },
  };
}
