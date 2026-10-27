import { useState } from 'react';
import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import { api } from '../api';
import MeterHistory from '../features/meters/MeterHistory';
import FormModal from '../components/FormModal';
import { setFormatLocale } from '../utils/format';

vi.mock('../api', () => ({ api: { get: vi.fn() } }));
afterEach(() => { cleanup(); vi.resetAllMocks(); setFormatLocale('de-DE'); });

const HISTORY = {
  meter: { id: 'm1', unit_id: 'u1', meter_type: 'cold_water', measure_unit: null, location: 'Keller', supplier: 'Stadtwerke Leipzig',
    contract_number: 'SW-1', contract_end_date: '2027-12-31', portal_url: 'https://portal.example/login', is_active: true },
  readings: [
    { id: 'r1', reading_date: '2024-07-01', value: 100.1, consumption: null, days: null, per_day: null, recorded_by: 'Hausmeister', notes: null, warning: null },
    { id: 'r2', reading_date: '2025-01-01', value: 150.3, consumption: 50.2, days: 184, per_day: 0.273, recorded_by: null, notes: 'Auszug', warning: null },
    { id: 'r3', reading_date: '2025-03-01', value: 10, consumption: -140.3, days: 59, per_day: -2.378, recorded_by: null, notes: null,
      warning: 'Stand kleiner als zuvor: Zählertausch, Überlauf oder Ablesefehler?' },
  ],
  years: [{ year: 2024, consumption: 50.2, covered_days: 184, complete: false }, { year: 2025, consumption: 0, covered_days: 0, complete: false }],
  contracts: [{ id: 'sc1', title: 'Wasser Nordhaus', provider: 'KWL', contract_number: 'W-9', customer_number: 'K-1',
    portal_url: 'https://kwl.example', href: '/service-contracts/sc1' }],
};

it('shows the readings with consumption, the years, the supply contracts and their portals', async () => {
  api.get.mockResolvedValue(HISTORY);
  const onEdit = vi.fn(); const onRecord = vi.fn();
  await act(async () => {
    render(<MemoryRouter><MeterHistory meterId="m1" meterLabel="WZ 4711" unitLabel="EG links" propertyName="Haus" propertyId="p1"
      onClose={() => {}} onEdit={onEdit} onRecord={onRecord} /></MemoryRouter>);
  });
  expect(api.get).toHaveBeenCalledWith('/meters/m1/history', expect.anything());
  expect(screen.getByRole('heading', { name: 'WZ 4711' })).toBeInTheDocument();
  expect(screen.getByRole('link', { name: 'EG links' })).toHaveAttribute('href', '/units/u1');
  const portals = screen.getAllByRole('link', { name: /Kundenportal des Anbieters öffnen/ });
  expect(portals.map(link => link.getAttribute('href'))).toEqual(['https://portal.example/login', 'https://kwl.example']);
  portals.forEach(link => { expect(link).toHaveAttribute('target', '_blank'); expect(link).toHaveAttribute('rel', 'noopener noreferrer'); });
  expect(screen.getByRole('link', { name: 'Wasser Nordhaus' })).toHaveAttribute('href', '/service-contracts/sc1');
  const readings = screen.getByRole('table', { name: /Ablesungen/ });
  const rows = within(readings).getAllByRole('row');
  expect(rows[1]).toHaveTextContent('01.03.2025');                     // newest first
  expect(rows[2]).toHaveTextContent('50,2');
  expect(rows[2]).toHaveTextContent('Auszug');
  expect(screen.getByRole('note')).toHaveTextContent('Zählertausch');
  expect(screen.getByRole('heading', { name: 'Verbrauch je Kalenderjahr (m³)' })).toBeInTheDocument();
  expect(screen.getByText(/Schraffiert/)).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Zähler bearbeiten' }));
  fireEvent.click(screen.getByRole('button', { name: '+ Ablesung erfassen' }));
  expect(onEdit).toHaveBeenCalled(); expect(onRecord).toHaveBeenCalled();
});

it('closes on Escape unless a form opened from it is on top', async () => {
  api.get.mockResolvedValue(HISTORY);
  const onClose = vi.fn();
  const { rerender } = render(<MemoryRouter><MeterHistory meterId="m1" meterLabel="WZ 4711" covered onClose={onClose} /></MemoryRouter>);
  await act(async () => {});
  fireEvent.keyDown(document, { key: 'Escape' });
  expect(onClose).not.toHaveBeenCalled();
  rerender(<MemoryRouter><MeterHistory meterId="m1" meterLabel="WZ 4711" onClose={onClose} /></MemoryRouter>);
  fireEvent.keyDown(document, { key: 'Escape' });
  expect(onClose).toHaveBeenCalled();
});

function deferred() {
  let resolve; let reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}

it.each(['resolve', 'reject'])('ignores a late %s from the previous meter while the next history is loading', async outcome => {
  const old = deferred(); const current = deferred();
  api.get.mockImplementation(path => path === '/meters/m1/history' ? old.promise : current.promise);
  const view = props => <MemoryRouter><MeterHistory onClose={vi.fn()} {...props} /></MemoryRouter>;
  const { rerender } = render(view({ meterId: 'm1', meterLabel: 'Alter Zähler' }));
  const oldSignal = api.get.mock.calls[0][1].signal;
  rerender(view({ meterId: 'm2', meterLabel: 'Neuer Zähler' }));
  expect(oldSignal.aborted).toBe(true);
  expect(screen.getByRole('heading', { name: 'Neuer Zähler' })).toBeInTheDocument();
  expect(screen.getByRole('status')).toHaveTextContent('Verlauf wird geladen');
  await act(async () => outcome === 'resolve' ? old.resolve(HISTORY) : old.reject(new Error('Alter Request fehlgeschlagen')));
  expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  expect(screen.queryByRole('table', { name: /Ablesungen/ })).not.toBeInTheDocument();
  expect(screen.getByRole('status')).toHaveTextContent('Verlauf wird geladen');
  await act(async () => current.resolve({ ...HISTORY, meter: { ...HISTORY.meter, id: 'm2' },
    readings: [{ ...HISTORY.readings[0], id: 'new', notes: 'Nur neuer Zähler' }] }));
  expect(screen.getByRole('table', { name: 'Ablesungen (1)' })).toHaveTextContent('Nur neuer Zähler');
  expect(screen.queryByText('Auszug')).not.toBeInTheDocument();
});

it('clears the previous successful history immediately when changing meter or refreshing its revision', async () => {
  const pending = deferred();
  api.get.mockResolvedValueOnce(HISTORY).mockImplementation(() => pending.promise);
  const view = revision => <MemoryRouter><MeterHistory meterId="m1" meterLabel="WZ" revision={revision} onClose={vi.fn()} /></MemoryRouter>;
  const { rerender } = render(view(0));
  await screen.findByRole('table', { name: 'Ablesungen (3)' });
  rerender(view(1));
  expect(screen.queryByRole('table', { name: /Ablesungen/ })).not.toBeInTheDocument();
  expect(screen.queryByText('Noch keine Ablesung erfasst.')).not.toBeInTheDocument();
  expect(screen.getByRole('status')).toHaveTextContent('Verlauf wird geladen');
  await act(async () => pending.resolve({ ...HISTORY, readings: [] }));
  expect(screen.getByText('Noch keine Ablesung erfasst.')).toBeInTheDocument();
});

it('reports a failed load and retries the same meter without pretending readings are empty', async () => {
  api.get.mockRejectedValueOnce(new Error('Messdienst nicht erreichbar')).mockResolvedValueOnce(HISTORY);
  render(<MemoryRouter><MeterHistory meterId="m1" meterLabel="WZ" onClose={vi.fn()} /></MemoryRouter>);
  expect(await screen.findByRole('alert')).toHaveTextContent('Messdienst nicht erreichbar');
  expect(screen.queryByText('Noch keine Ablesung erfasst.')).not.toBeInTheDocument();
  expect(screen.queryByRole('table')).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Erneut laden' }));
  await screen.findByRole('table', { name: 'Ablesungen (3)' });
  expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  expect(api.get.mock.calls.map(([path]) => path)).toEqual(['/meters/m1/history', '/meters/m1/history']);
});

it.each([{ meter: HISTORY.meter }, { ...HISTORY, meter: { ...HISTORY.meter, id: 'another' } }])(
  'treats an incomplete or mismatched history as a recoverable load error', async response => {
    api.get.mockResolvedValueOnce(response).mockResolvedValueOnce(HISTORY);
    render(<MemoryRouter><MeterHistory meterId="m1" meterLabel="WZ" onClose={vi.fn()} /></MemoryRouter>);
    expect(await screen.findByRole('alert')).toHaveTextContent('nicht vollständig geladen');
    expect(screen.queryByText('Noch keine Ablesung erfasst.')).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Erneut laden' }));
    await screen.findByRole('table', { name: 'Ablesungen (3)' });
  });

it('makes a covered history inert and disables its actions while the actual edit form owns Escape', async () => {
  api.get.mockResolvedValue(HISTORY);
  const onClose = vi.fn(); const onEdit = vi.fn(); const onRecord = vi.fn();
  function Layered() {
    const [editing, setEditing] = useState(false);
    return <MemoryRouter>
      <MeterHistory meterId="m1" meterLabel="WZ" onClose={onClose} covered={editing}
        onEdit={() => { onEdit(); setEditing(true); }} onRecord={onRecord} />
      {editing && <FormModal title="Zähler bearbeiten" autosave={false} fields={[{ key: 'serial', label: 'Seriennummer' }]}
        onSave={vi.fn()} onClose={() => setEditing(false)} />}
    </MemoryRouter>;
  }
  render(<Layered />);
  const edit = await screen.findByRole('button', { name: 'Zähler bearbeiten' });
  const record = screen.getByRole('button', { name: '+ Ablesung erfassen' });
  const close = screen.getByRole('button', { name: 'Schließen' });
  const history = screen.getByRole('dialog', { name: 'WZ' });
  const overlay = history.parentElement;
  fireEvent.click(edit);
  expect(history).toHaveAttribute('inert');
  expect(history).toHaveAttribute('aria-hidden', 'true');
  expect(history).not.toHaveAttribute('aria-modal', 'true');
  expect(edit).toBeDisabled(); expect(record).toBeDisabled(); expect(close).toBeDisabled();
  fireEvent.click(edit); fireEvent.click(record); fireEvent.click(close);
  fireEvent.mouseDown(overlay); fireEvent.click(overlay);
  expect(onEdit).toHaveBeenCalledTimes(1); expect(onRecord).not.toHaveBeenCalled(); expect(onClose).not.toHaveBeenCalled();
  changeSerial('Noch nicht speichern');
  fireEvent.keyDown(document, { key: 'Escape' });
  expect(screen.getByRole('alertdialog')).toHaveTextContent('Ungespeicherte Änderungen verwerfen?');
  expect(onClose).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole('button', { name: 'Verwerfen', exact: true }));
  await waitFor(() => expect(screen.queryByRole('dialog', { name: 'Zähler bearbeiten' })).not.toBeInTheDocument());
  expect(history).not.toHaveAttribute('inert');
  expect(close).toHaveFocus();
  fireEvent.keyDown(document, { key: 'Escape' });
  expect(onClose).toHaveBeenCalledTimes(1);
});

function changeSerial(value) { fireEvent.change(screen.getByLabelText('Seriennummer'), { target: { value } }); }

it('does not retry a covered history behind another form', async () => {
  api.get.mockRejectedValue(new Error('Offline'));
  const { container } = render(<MemoryRouter><MeterHistory meterId="m1" meterLabel="WZ" covered onClose={vi.fn()} /></MemoryRouter>);
  await waitFor(() => expect(container.querySelector('[role="alert"]')).toHaveTextContent('Offline'));
  const retry = within(container).getByText('Erneut laden');
  expect(retry).toBeDisabled();
  fireEvent.click(retry);
  expect(api.get).toHaveBeenCalledTimes(1);
});

it('requires a backdrop click to start on the backdrop, preserving text selections', async () => {
  api.get.mockResolvedValue(HISTORY);
  const onClose = vi.fn();
  render(<MemoryRouter><MeterHistory meterId="m1" meterLabel="WZ" onClose={onClose} /></MemoryRouter>);
  const history = screen.getByRole('dialog');
  const overlay = history.parentElement;
  fireEvent.mouseDown(history); fireEvent.click(overlay);
  expect(onClose).not.toHaveBeenCalled();
  fireEvent.mouseDown(overlay); fireEvent.click(overlay);
  expect(onClose).toHaveBeenCalledTimes(1);
});

it('keeps keyboard focus inside the open history and restores the opener after unmount', async () => {
  api.get.mockResolvedValue(HISTORY);
  const opener = document.createElement('button'); document.body.append(opener); opener.focus();
  const { unmount } = render(<MemoryRouter><MeterHistory meterId="m1" meterLabel="WZ" propertyId="p1" propertyName="Haus" onClose={vi.fn()} /></MemoryRouter>);
  await screen.findByRole('table', { name: 'Ablesungen (3)' });
  const history = screen.getByRole('dialog');
  const targets = history.querySelectorAll('button:not(:disabled), a[href], [tabindex="0"]');
  targets[targets.length - 1].focus();
  fireEvent.keyDown(document, { key: 'Tab' });
  expect(targets[0]).toHaveFocus();
  fireEvent.keyDown(document, { key: 'Tab', shiftKey: true });
  expect(targets[targets.length - 1]).toHaveFocus();
  unmount();
  expect(opener).toHaveFocus(); opener.remove();
});

it('retains the full integer value in an English formatted yearly chart label', async () => {
  setFormatLocale('en-US');
  api.get.mockResolvedValue({ ...HISTORY, years: [{ year: 2025, consumption: 1000, covered_days: 365, complete: true }] });
  const { container } = render(<MemoryRouter><MeterHistory meterId="m1" meterLabel="WZ" onClose={vi.fn()} /></MemoryRouter>);
  await screen.findByRole('table', { name: 'Ablesungen (3)' });
  expect(container.querySelector('.meter-history-cap')).toHaveTextContent(/^1,000$/);
  const years = screen.getByRole('table', { name: 'Verbrauch je Kalenderjahr (m³)' });
  expect(within(years).getByText('1,000')).toBeInTheDocument();
});
