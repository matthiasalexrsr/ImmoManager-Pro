import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { act, cleanup, render } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import useNavigationState from '../hooks/useNavigationState';
import { privateStorageKey, setWorkspaceOwner } from '../utils/workspaceIdentity';

vi.mock('../contexts/AuthContext', () => ({ useAuth: () => ({ user: { id: 'scroll-user' } }) }));
let node, resizeCallback, frames;
function Probe() { useNavigationState(); return null; }
beforeEach(() => {
  sessionStorage.clear(); setWorkspaceOwner('scroll-user'); frames = new Map(); let next = 0;
  node = document.createElement('main'); node.className = 'main-content-body'; document.body.append(node);
  Object.defineProperties(node, { scrollHeight: { value: 100, configurable: true }, clientHeight: { value: 100, configurable: true } });
  vi.stubGlobal('requestAnimationFrame', fn => { frames.set(++next, fn); return next; });
  vi.stubGlobal('cancelAnimationFrame', id => frames.delete(id));
  vi.stubGlobal('ResizeObserver', class { constructor(fn) { resizeCallback = fn; } observe() {} disconnect() {} });
  sessionStorage.setItem(privateStorageKey('scroll:/tasks'), JSON.stringify([{ top: 400, left: 0 }]));
});
afterEach(() => { cleanup(); node.remove(); vi.unstubAllGlobals(); setWorkspaceOwner(null); });
function tick() { act(() => { const batch = [...frames.values()]; frames.clear(); batch.forEach(callback => callback()); }); }
it('waits for delayed list layout without a fixed frame cutoff or busy loop', () => {
  render(<MemoryRouter initialEntries={['/tasks']}><Probe /></MemoryRouter>);
  tick();
  expect(node.scrollTop).toBe(0); expect(frames.size).toBe(0);
  // A slow request may finish well after the former 120-frame limit.
  for (let frame = 0; frame < 150; frame++) tick();
  Object.defineProperty(node, 'scrollHeight', { value: 1000, configurable: true });
  act(() => resizeCallback()); tick();
  expect(node.scrollTop).toBe(400);
});
it('respects manual scrolling while a delayed list is loading', () => {
  render(<MemoryRouter initialEntries={['/tasks']}><Probe /></MemoryRouter>);
  tick();
  act(() => window.dispatchEvent(new Event('wheel')));
  Object.defineProperty(node, 'scrollHeight', { value: 1000, configurable: true });
  act(() => resizeCallback()); tick();
  expect(node.scrollTop).toBe(0);
});
