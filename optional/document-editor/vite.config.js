import { defineConfig } from 'vite';

export default defineConfig({
  base: '/document-editor/',
  // Library mode retains dependency NODE_ENV checks unless explicitly defined;
  // a browser has no Node process global (Vue otherwise fails before onReady).
  define: { 'process.env.NODE_ENV': JSON.stringify('production') },
  build: {
    outDir: '../../frontend/public/document-editor',
    emptyOutDir: true,
    lib: { entry: 'src/editor.js', formats: ['es'], fileName: () => 'editor.js', cssFileName: 'editor' },
    rollupOptions: { output: { assetFileNames: '[name][extname]' } },
  },
});
