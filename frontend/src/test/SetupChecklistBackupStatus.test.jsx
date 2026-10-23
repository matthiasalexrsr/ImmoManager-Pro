import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import SetupChecklist from '../components/SetupChecklist';

const permission = vi.hoisted(() => ({ allowed: true }));

vi.mock('../contexts/AuthContext', () => ({
  useAuth: () => ({ user: { id: 'synthetic-owner' } }),
  useCanWrite: () => permission.allowed,
}));

beforeEach(() => {
  permission.allowed = true;
  localStorage.clear();
});
afterEach(() => cleanup());

const show = (props = {}) => render(
  <MemoryRouter initialEntries={['/']}>
    <SetupChecklist stats={{ portfolios: 1, properties: 0, units: 0, accounts: 0, contracts: 0 }}
      ready {...props} />
  </MemoryRouter>,
);

it('never claims daily backups without observing the actual installation status', () => {
  show();
  expect(screen.getByRole('heading', { name: 'Erste Schritte' })).toBeVisible();
  expect(screen.queryByText(/Datensicherung läuft automatisch jeden Tag/)).not.toBeInTheDocument();
  expect(screen.getByText(/Ob und wann automatische Sicherungen laufen/)).toBeVisible();
  expect(screen.getByText(/letzte erfolgreiche Sicherung und Wiederherstellungsprobe/)).toBeVisible();
  expect(screen.getByRole('link', { name: 'Einstellungen → System' }))
    .toHaveAttribute('href', '/settings?section=system');
});

it('does not expose setup actions to nonwriters or before portfolio statistics are ready', () => {
  permission.allowed = false;
  show();
  expect(screen.queryByRole('heading', { name: 'Erste Schritte' })).not.toBeInTheDocument();
  cleanup();
  permission.allowed = true;
  show({ ready: false });
  expect(screen.queryByRole('link', { name: 'Einstellungen → System' })).not.toBeInTheDocument();
});
