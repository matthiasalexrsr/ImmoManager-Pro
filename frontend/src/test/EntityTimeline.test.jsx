import { act, cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import { api } from '../api';
import EntityTimeline from '../features/workCenter/EntityTimeline';

vi.mock('../api', () => ({ api: { get: vi.fn() } }));
vi.mock('../i18n', () => ({ useTranslation: () => ({ t: key => ({
  'status.badge.open': 'Offen', 'status.badge.completed': 'Erledigt',
}[key] || key) }) }));
const change = (field, oldValue, newValue, extra = {}) => ({ id: field, kind: 'change', title: `Änderung: ${field}`,
  field_name: field, old_value: oldValue, new_value: newValue, occurred_at: '2026-10-15T09:00:00Z', ...extra });
const show = async items => {
  api.get.mockResolvedValueOnce({ items, next_cursor: null });
  await act(async () => { render(<MemoryRouter><EntityTimeline entityType="tenant" entityId="t1" /></MemoryRouter>); });
};
const values = title => [...screen.getByText(title).closest('li').querySelectorAll('dd')].map(node => node.textContent);
beforeEach(() => vi.resetAllMocks());
afterEach(cleanup);

it('shows readable names, exact before/after values and the original reason without additional lookups', async () => {
  await show([
    change('full_name', 'Anna Alt', 'Anna Neu', { body: 'Name berichtigt', actor: { name: 'Verwaltung' }, entity: { href: '/tenants/t1' } }),
    change('status', 'open', 'completed'),
    change('due_date', '2026-10-01', '2026-10-20'),
    change('property_id', 'property-old', 'property-new'),
    change('payment_method', 'cash', 'bank_transfer'),
  ]);
  expect(values('Änderung: Name')).toEqual(['Anna Alt', 'Anna Neu']);
  const name = screen.getByText('Änderung: Name').closest('li');
  expect(within(name).getByText('Vorher')).toBeInTheDocument();
  expect(within(name).getByText('Nachher')).toBeInTheDocument();
  expect(within(name).getByText('Name berichtigt')).toBeInTheDocument();
  expect(within(name).getByText('Verwaltung')).toBeInTheDocument();
  expect(within(name).getByRole('link', { name: 'Vorgang öffnen' })).toHaveAttribute('href', '/tenants/t1');
  expect(values('Änderung: Status')).toEqual(['Offen', 'Erledigt']);
  expect(values('Änderung: Fälligkeit')).toEqual(['01.10.2026', '20.10.2026']);
  expect(values('Änderung: Immobilienkennung')).toEqual(['property-old', 'property-new']);
  expect(values('Änderung: Zahlungsart')).toEqual(['Bar', 'Überweisung']);
  expect(api.get).toHaveBeenCalledTimes(1);
});

it('preserves zero, false, free text, long multiline and unknown field values', async () => {
  const longText = `Erste Zeile\n${'Ausführliche Notiz '.repeat(150)}\nLetzte Zeile`;
  await show([
    change('amount', 0, '0'), change('archived', false, 'True'), change('active', 'False', '1'),
    change('description', null, longText), change('notes', '', '  '), change('title', 'invoice', 'false'),
    change('custom_field', false, { label: 'Unbekannt', amount: 0 }), change('sepa_mandate', 'False', 'True'),
  ]);
  expect(values('Änderung: Betrag')).toEqual(['0', '0']);
  expect(values('Änderung: Archiviert')).toEqual(['Nein', 'Ja']);
  expect(values('Änderung: Aktiv')).toEqual(['Nein', '1']);
  expect(values('Änderung: Beschreibung')).toEqual(['Nicht angegeben', longText]);
  expect(screen.getByText('Änderung: Beschreibung').closest('li').querySelector('dd:last-child')).toHaveClass('work-preserve-lines');
  expect(values('Änderung: Notizen')).toEqual(['Nicht angegeben', 'Nicht angegeben']);
  expect(values('Änderung: Titel')).toEqual(['invoice', 'false']);
  expect(values('Änderung: custom_field')).toEqual(['Nein', '{"label":"Unbekannt","amount":0}']);
  expect(values('Änderung: SEPA-Mandat')).toEqual(['False', 'True']);
});

it('humanizes older titles without inventing missing values and keeps unknown fields visible', async () => {
  await show([
    { id: 'legacy', kind: 'change', title: 'Änderung: title', body: 'Alter Server', occurred_at: '2026-10-15T09:00:00Z' },
    { id: 'unknown', kind: 'change', title: 'Änderung: custom_field' },
    change('defect:d1:description', 'Alt', 'Neu'),
  ]);
  expect(screen.getByText('Änderung: Titel')).toBeInTheDocument();
  expect(screen.getByText('Alter Server')).toBeInTheDocument();
  expect(screen.getByText('Änderung: Titel').closest('li').querySelector('dl')).toBeNull();
  expect(screen.getByText('Änderung: custom_field')).toBeInTheDocument();
  expect(values('Änderung: Mangel (Kennung d1) – Beschreibung')).toEqual(['Alt', 'Neu']);
});

it('retains earlier changed values while loading the next cursor page', async () => {
  api.get.mockResolvedValueOnce({ items: [change('title', 'Alt', 'Neu')], next_cursor: 'next cursor' })
    .mockResolvedValueOnce({ items: [change('status', 'open', 'completed')], next_cursor: null });
  await act(async () => { render(<MemoryRouter><EntityTimeline entityType="tenant" entityId="t1" /></MemoryRouter>); });
  await act(async () => { fireEvent.click(screen.getByRole('button', { name: 'Weitere laden' })); });
  expect(values('Änderung: Titel')).toEqual(['Alt', 'Neu']);
  expect(values('Änderung: Status')).toEqual(['Offen', 'Erledigt']);
  expect(api.get).toHaveBeenCalledTimes(2);
  expect(api.get.mock.calls[1][0]).toContain('&cursor=next%20cursor');
  expect(screen.queryByRole('button', { name: 'Weitere laden' })).not.toBeInTheDocument();
});
