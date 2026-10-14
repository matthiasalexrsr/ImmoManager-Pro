import '@testing-library/jest-dom';
import { afterEach } from 'vitest';

// Lists keep their search and page per browser tab (sessionStorage); every test starts with a fresh tab.
afterEach(() => { window.sessionStorage.clear(); });
