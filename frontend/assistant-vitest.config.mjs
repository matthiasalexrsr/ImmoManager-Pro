import { mergeConfig } from 'vite';
import { realpathSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import base from './vite.config.js';

// Isolated test runner for a shared dependency junction in a Git worktree. Production
// and the existing repository configuration remain unchanged.
export default mergeConfig(base, { server: { fs: { allow: [
  fileURLToPath(new URL('.', import.meta.url)),
  realpathSync(fileURLToPath(new URL('./node_modules', import.meta.url))),
] } } });
