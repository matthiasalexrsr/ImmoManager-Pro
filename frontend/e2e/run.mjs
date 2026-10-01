import { spawn } from 'node:child_process';
import { randomBytes } from 'node:crypto';
import { once } from 'node:events';
import { existsSync } from 'node:fs';
import { copyFile, mkdir, mkdtemp, rm, writeFile } from 'node:fs/promises';
import { createServer } from 'node:net';
import { tmpdir } from 'node:os';
import { dirname, join, resolve } from 'node:path';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';

const require = createRequire(import.meta.url);
const frontendDir = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const projectDir = resolve(frontendDir, '..');
const tempPrefix = join(tmpdir(), 'immomanager-browser-');
const dataDir = await mkdtemp(tempPrefix);
const backendLog = join(dataDir, 'backend.log');
const defaultPython = join(projectDir, '.venv', process.platform === 'win32' ? 'Scripts/python.exe' : 'bin/python');
const python = process.env.IMMO_E2E_PYTHON || (existsSync(defaultPython) ? defaultPython : 'python');
const freshInstallation = process.argv.includes('--fresh-install');
const playwrightArgs = process.argv.slice(2).filter(arg => arg !== '--fresh-install');
let backend;
let backendStopped;
let backendError;
let stopPromise;
let log = '';
let interrupted = false;

function start(command, args, options = {}) {
  return spawn(command, args, { cwd: projectDir, windowsHide: true, ...options });
}

async function run(command, args, options) {
  const child = start(command, args, { stdio: 'inherit', ...options });
  const [code] = await once(child, 'exit');
  if (code !== 0) throw new Error(`${command} exited with ${code}`);
}

async function freePort() {
  const server = createServer();
  server.listen(0, '127.0.0.1');
  await once(server, 'listening');
  const port = server.address().port;
  await new Promise((resolveClose, reject) => server.close(error => error ? reject(error) : resolveClose()));
  return port;
}

async function waitForBackend(url) {
  const deadline = Date.now() + 90_000;
  while (Date.now() < deadline) {
    if (backendError) throw backendError;
    if (interrupted || backend.exitCode !== null || backend.signalCode !== null) throw new Error('Test backend stopped before becoming ready.');
    try {
      const response = await fetch(`${url}/health`, { signal: AbortSignal.timeout(2000) });
      if (response.ok) {
        const health = await response.json();
        if (health.status !== 'ok' || health.store_backend !== 'SQLAlchemyStore' || !health.database_connected) {
          throw new Error(`Browser tests require a healthy SQL database: ${JSON.stringify(health)}`);
        }
        return;
      }
    } catch (error) {
      if (error.message.startsWith('Browser tests require')) throw error;
    }
    await new Promise(resolveWait => setTimeout(resolveWait, 250));
  }
  throw new Error('Test backend did not become ready within 90 seconds.');
}

async function stopBackend() {
  if (stopPromise) return stopPromise;
  if (!backend || backendError || backend.exitCode !== null || backend.signalCode !== null) return;
  stopPromise = (async () => {
    if (process.platform === 'win32') {
      // A Windows venv launcher can have a Python child; terminate our owned tree.
      await run('taskkill.exe', ['/PID', String(backend.pid), '/T', '/F'], { stdio: 'ignore' });
    } else {
      backend.kill('SIGTERM');
    }
    await backendStopped;
  })();
  return stopPromise;
}

for (const signal of ['SIGINT', 'SIGTERM']) {
  process.on(signal, () => {
    interrupted = true;
    stopBackend().catch(error => console.error(error.message));
  });
}

try {
  if (!process.env.npm_execpath) throw new Error('Start this runner through npm run test:e2e.');
  await run(process.execPath, [process.env.npm_execpath, 'run', 'build'], { cwd: frontendDir });
  const port = await freePort();
  const url = `http://127.0.0.1:${port}`;
  backend = start(python, ['-m', 'backend', ...(freshInstallation ? [] : ['--seed']), '--no-browser', '--host', '127.0.0.1', '--port', String(port), '--data-dir', dataDir], {
    stdio: ['ignore', 'pipe', 'pipe'],
    env: {
      ...process.env,
      PYTHONUTF8: '1',
      PYTHONUNBUFFERED: '1',
      ENVIRONMENT: 'development',
      DATABASE_URL: `sqlite:///${join(dataDir, 'immo_manager.db').replaceAll('\\', '/')}`,
      DATA_DIR: dataDir,
      UPLOADS_DIR: join(dataDir, 'uploads'),
      BACKUP_DIR: join(dataDir, 'backups'),
      LOG_FILE: join(dataDir, 'application.log'),
      INTEGRATION_STATE_FILE: join(dataDir, 'integrations.json'),
      JWT_SECRET_KEY: randomBytes(48).toString('hex'),
      SQLITE_PERSISTENT_STORE: 'true',
      ALLOW_INMEMORY_FALLBACK: 'false',
      AUTO_SEED_DEMO_DATA: 'false',
      AUTO_MIGRATE: 'false',
      AI_ENABLED: 'false',
      PLUGIN_DIRS: '[]',
      CORS_ORIGINS: url,
    },
  });
  backendStopped = new Promise(resolveStopped => {
    backend.once('exit', resolveStopped);
    backend.once('error', resolveStopped);
  });
  backend.stdout.on('data', chunk => { log += chunk.toString(); });
  backend.stderr.on('data', chunk => { log += chunk.toString(); });
  backend.on('error', error => { backendError = error; log += `\n${error.stack}\n`; });
  await waitForBackend(url);
  await run(process.execPath, [require.resolve('@playwright/test/cli'), 'test', '--config', 'e2e/playwright.config.mjs', ...playwrightArgs], {
    cwd: frontendDir,
    env: { ...process.env, IMMO_E2E_URL: url, IMMO_E2E_MODE: freshInstallation ? 'setup' : 'demo' },
  });
} catch (error) {
  console.error(error.message);
  console.error(log.slice(-12_000));
  process.exitCode = 1;
} finally {
  await stopBackend();
  await writeFile(backendLog, log);
  const resultsDir = join(frontendDir, 'test-results', ...(freshInstallation ? ['auth'] : []));
  await mkdir(resultsDir, { recursive: true });
  await copyFile(backendLog, join(resultsDir, 'backend.log'));
  // Only remove the fresh directory created by this process, never a configured data path.
  if (dirname(resolve(dataDir)) === resolve(tmpdir()) && resolve(dataDir).startsWith(resolve(tempPrefix))) {
    await rm(dataDir, { recursive: true, force: true, maxRetries: 5, retryDelay: 200 });
  }
}
