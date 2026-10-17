import '@testing-library/jest-dom';
import { afterEach, vi } from 'vitest';

// jsdom has no scrolling implementation. Actual scrolling is exercised by
// browser QA; unit tests retain a spy instead of emitting unrelated warnings.
Object.defineProperty(window, 'scrollTo', { configurable: true, writable: true, value: vi.fn() });

// Lists keep their search and page per browser tab (sessionStorage); every test starts with a fresh tab.
afterEach(() => { window.sessionStorage.clear(); });
