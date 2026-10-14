import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import DataTable from '../components/DataTable';
import FormModal from '../components/FormModal';
import SetupChecklist from '../components/SetupChecklist';
import { nextNumber } from '../utils/nextNumber';
import { onlyChoices, prerequisiteFor } from '../utils/prerequisites';

const auth = vi.hoisted(() => ({ canWrite: true }));
vi.mock('../contexts/AuthContext', () => ({
  useCanWrite: () => auth.canWrite,
  useAuth: () => ({ user: { id: 'owner-1' } }),
}));

beforeEach(() => { localStorage.clear(); sessionStorage.clear(); auth.canWrite = true; });
afterEach(cleanup);

describe('next contract number', () => {
  it('continues the pattern in use and never proposes a taken one', () => {
    expect(nextNumber([], 'MV-1')).toBe('MV-1');
    expect(nextNumber(['MV-2024-007', 'MV-2024-003'], 'MV-1')).toBe('MV-2024-008');
    expect(nextNumber(['MV-9', 'MV-10'], 'MV-1')).toBe('MV-11');
    expect(nextNumber(['A-01', 'A-02', 'A-03'], 'MV-1')).toBe('A-04');
    expect(nextNumber(['7', '8', 'MV-8'], 'MV-1')).toBe('9');
    expect(nextNumber(['Altvertrag Müller'], 'MV-1')).toBe('MV-1');
    expect(nextNumber(['MV-1'], 'MV-1')).toBe('MV-2');
  });
});

describe('required choices', () => {
  const portfolio = { key: 'portfolio_id', label: 'Portfolio', type: 'select', required: true };

  it('makes a choice with one option and leaves several or a made one alone', () => {
    const fields = [
      { ...portfolio, options: [{ value: 'p1', label: 'Mein Bestand' }] },
      { key: 'kind', type: 'select', required: true, options: [{ value: 'a', label: 'A' }, { value: 'b', label: 'B' }] },
      { key: 'note', type: 'select', options: [{ value: 'x', label: 'X' }] },
      { key: 'unit_id', type: 'select', required: true, options: values => (values.portfolio_id ? [{ value: 'u1', label: 'WE 1' }] : []) },
    ];
    expect(onlyChoices(fields, { portfolio_id: '', kind: '', note: '', unit_id: '' })).toEqual({ portfolio_id: 'p1' });
    expect(onlyChoices(fields, { portfolio_id: 'p1', kind: '', note: '', unit_id: '' })).toEqual({ unit_id: 'u1' });
    expect(onlyChoices(fields, { portfolio_id: 'p1', kind: '', note: '', unit_id: 'u9' })).toEqual({});
  });

  it('names a missing prerequisite only where nothing else explains the empty list', () => {
    expect(prerequisiteFor({ ...portfolio, options: [] }, [])).toMatchObject({ to: '/portfolios?neu=1' });
    expect(prerequisiteFor({ ...portfolio, options: [] }, [{ value: 'p1' }])).toBeNull();
    expect(prerequisiteFor({ ...portfolio, required: false, options: [] }, [])).toBeNull();
    // units of the chosen property: empty before a property is chosen, for another reason
    expect(prerequisiteFor({ key: 'unit_id', type: 'select', required: true, options: () => [] }, [])).toBeNull();
    expect(prerequisiteFor({ key: 'unit_id', type: 'select', required: true, options: () => [], emptyHint: { text: 'x', to: '/y', label: 'z' } }, [])).toMatchObject({ to: '/y' });
  });

  it('the form preselects the only portfolio without counting it as an edit', () => {
    const onClose = vi.fn();
    render(<MemoryRouter><FormModal title="Immobilie erstellen" onSave={vi.fn()} onClose={onClose}
      fields={[{ ...portfolio, options: [{ value: 'p1', label: 'Mein Bestand' }] }, { key: 'name', label: 'Name' }]} /></MemoryRouter>);
    expect(screen.getByLabelText('Portfolio *')).toHaveValue('p1');
    fireEvent.click(screen.getByRole('button', { name: /schlie|close/i }));
    expect(onClose).toHaveBeenCalled();
  });

  it('the form links to creating a missing portfolio', () => {
    render(<MemoryRouter><FormModal title="Immobilie erstellen" onSave={vi.fn()} onClose={vi.fn()}
      fields={[{ ...portfolio, options: [] }]} /></MemoryRouter>);
    const note = screen.getByRole('note');
    expect(note).toHaveTextContent('Noch kein Portfolio angelegt.');
    expect(within(note).getByRole('link', { name: 'Portfolio anlegen' })).toHaveAttribute('href', '/portfolios?neu=1');
  });
});

describe('empty lists', () => {
  const columns = [{ key: 'name', label: 'Name', filterType: 'text' }];

  it('offer the first entry when nothing is there', () => {
    const onAdd = vi.fn();
    render(<DataTable title="Immobilien" columns={columns} data={[]} onAdd={onAdd} />);
    fireEvent.click(screen.getByRole('button', { name: 'Neuen Eintrag anlegen' }));
    expect(onAdd).toHaveBeenCalledTimes(1);
    expect(screen.getByText('Keine Einträge vorhanden.')).toBeInTheDocument();
  });

  it('offer no entry to roles that may not add', () => {
    auth.canWrite = false;
    render(<DataTable title="Immobilien" columns={columns} data={[]} onAdd={vi.fn()} />);
    expect(screen.queryByRole('button', { name: 'Neuen Eintrag anlegen' })).not.toBeInTheDocument();
  });

  it('offer to reset a search that finds nothing', () => {
    render(<DataTable title="Immobilien" columns={columns} data={[{ id: '1', name: 'Lindenstraße 12' }]} />);
    fireEvent.change(screen.getByRole('textbox', { name: 'Immobilien durchsuchen' }), { target: { value: 'gibtsnicht' } });
    fireEvent.click(screen.getByRole('button', { name: 'Suche und Filter zurücksetzen' }));
    expect(screen.getByText('Lindenstraße 12')).toBeInTheDocument();
    expect(screen.getByRole('textbox', { name: 'Immobilien durchsuchen' })).toHaveValue('');
  });

  it('keep a page header button the only visible New button, but answer ?neu=1', () => {
    render(<DataTable title="Mieter" columns={columns} data={[{ id: '1', name: 'Max' }]} onAdd={vi.fn()} addLabel="Partei anlegen" hideAddButton />);
    expect(screen.queryByRole('button', { name: /Partei anlegen|^Neu$/ })).not.toBeInTheDocument();
  });
});

describe('Erste Schritte', () => {
  const none = { portfolios: 0, properties: 0, units: 0, accounts: 0, contracts: 0 };
  const show = stats => render(<MemoryRouter><SetupChecklist stats={stats} ready /></MemoryRouter>);

  it('leads to the first missing step', () => {
    show({ ...none, portfolios: 1 });
    const card = screen.getByRole('region', { name: 'Erste Schritte' });
    expect(card).toHaveTextContent('1 von 5 erledigt');
    const next = card.querySelector('li.is-next');
    expect(next).toHaveTextContent('Immobilie anlegen');
    expect(within(next).getByRole('link')).toHaveAttribute('href', '/properties?neu=1');
  });

  it('disappears when everything is entered, for roles that may not enter, or once put away', () => {
    show({ portfolios: 1, properties: 1, units: 2, accounts: 1, contracts: 1 });
    expect(screen.queryByRole('region', { name: 'Erste Schritte' })).not.toBeInTheDocument();
    cleanup();

    auth.canWrite = false;
    show(none);
    expect(screen.queryByRole('region', { name: 'Erste Schritte' })).not.toBeInTheDocument();
    cleanup();

    auth.canWrite = true;
    show(none);
    fireEvent.click(screen.getByRole('button', { name: 'Ausblenden' }));
    expect(screen.queryByRole('region', { name: 'Erste Schritte' })).not.toBeInTheDocument();
    cleanup();
    show(none);
    expect(screen.queryByRole('region', { name: 'Erste Schritte' })).not.toBeInTheDocument();
  });

  it('waits for the figures instead of showing every step as open', () => {
    render(<MemoryRouter><SetupChecklist stats={{}} ready={false} /></MemoryRouter>);
    expect(screen.queryByRole('region', { name: 'Erste Schritte' })).not.toBeInTheDocument();
  });
});

describe('New forms opened from elsewhere', () => {
  it('pass the values a request carries to the list, also when the list appears later', async () => {
    const { holdNewEntry, requestNewEntry } = await import('../utils/newEntry');
    const onAdd = vi.fn();
    holdNewEntry('/units', { property_id: 'p1' });
    render(<DataTable title="Einheiten" columns={[{ key: 'label', label: 'Einheit' }]} data={[]} onAdd={onAdd} />);
    expect(onAdd).toHaveBeenLastCalledWith({ property_id: 'p1' });
    expect(requestNewEntry({ property_id: 'p2' })).toBe(true);
    expect(onAdd).toHaveBeenLastCalledWith({ property_id: 'p2' });
  });

  it('never hand a click event to the list as values', () => {
    const onAdd = vi.fn();
    render(<DataTable title="Einheiten" columns={[{ key: 'label', label: 'Einheit' }]} data={[{ id: '1', label: 'WE 1' }]} onAdd={onAdd} />);
    fireEvent.click(document.querySelector('[data-table-add]'));
    expect(onAdd).toHaveBeenCalledWith();
  });
});
