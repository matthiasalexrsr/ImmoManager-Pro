import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import DossierTabs from '../components/DossierTabs';
afterEach(cleanup);
it('continues from actual focus while the previous URL selection has not rendered yet', () => {
  const changed = vi.fn();
  render(<DossierTabs tabs={[{ key: 'overview', label: 'Übersicht' }, { key: 'units', label: 'Einheiten' }, { key: 'contracts', label: 'Verträge' }]}
    value="overview" onChange={changed}>Akteninhalt</DossierTabs>);
  const units = screen.getByRole('tab', { name: 'Einheiten' });
  units.focus(); fireEvent.keyDown(units, { key: 'ArrowRight' });
  expect(changed).toHaveBeenLastCalledWith('contracts');
  const contracts = screen.getByRole('tab', { name: 'Verträge' });
  expect(contracts).toHaveFocus();
  fireEvent.keyDown(contracts, { key: 'ArrowLeft' });
  expect(changed).toHaveBeenLastCalledWith('units'); expect(units).toHaveFocus();
});
