import { afterEach, expect, it } from 'vitest';
import { cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import { MemoryRouter, useLocation } from 'react-router-dom';
import RelatedPageLinks from '../components/RelatedPageLinks';

afterEach(cleanup);
function LocationReport() {
  const route = useLocation();
  return <output data-testid="route">{route.pathname + route.search}</output>;
}

it('renders accessible native links between related records and supports browser navigation', () => {
  render(<MemoryRouter initialEntries={['/units/u1']}>
    <RelatedPageLinks items={[
      { to: '/properties/p1?tab=contracts', label: 'Objektverträge' },
      { to: '/tenants/t1/account', label: 'Mieterkonto' },
    ]} />
    <LocationReport />
  </MemoryRouter>);
  const nav = screen.getByRole('navigation', { name: 'Verknüpfte Seiten' });
  expect(within(nav).getAllByRole('link')).toHaveLength(2);
  const contract = within(nav).getByRole('link', { name: 'Objektverträge' });
  expect(contract).toHaveAttribute('href', '/properties/p1?tab=contracts');
  expect(contract).not.toHaveAttribute('role', 'button');
  expect(nav.querySelector('.related-page-links__items')).toBeInTheDocument();
  fireEvent.click(contract);
  expect(screen.getByTestId('route')).toHaveTextContent('/properties/p1?tab=contracts');
});

it('does not generate links for missing or external targets', () => {
  render(<MemoryRouter><RelatedPageLinks items={[
    { to: 'https://invalid.example/', label: 'Externe Seite' },
    { to: '//invalid.example/', label: 'Protokoll-relative Seite' },
    { to: null, label: 'Fehlt' },
    { to: '/contracts', label: 'Verträge' },
  ]} /></MemoryRouter>);
  const nav = screen.getByRole('navigation', { name: 'Verknüpfte Seiten' });
  expect(within(nav).getAllByRole('link')).toHaveLength(1);
  expect(within(nav).getByRole('link', { name: 'Verträge' })).toHaveAttribute('href', '/contracts');
});

it('renders no empty navigation area when there is no suitable target', () => {
  const { container } = render(<MemoryRouter><RelatedPageLinks items={[]} /></MemoryRouter>);
  expect(container).toBeEmptyDOMElement();
});
