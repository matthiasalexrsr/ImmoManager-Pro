import { act, fireEvent, render, screen, within } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import userEvent from '@testing-library/user-event';
import FormModal from '../components/FormModal';
import DataTable from '../components/DataTable';
import german from '../../../i18n/de-DE.json';

vi.mock('../i18n', () => ({ useTranslation: () => ({ t: key => key.split('.').reduce((value, part) => value?.[part], german) || key }) }));
afterEach(() => vi.restoreAllMocks());
const fields = [{ key: 'name', label: 'Name', required: true, hint: 'Eindeutige Bezeichnung' }, { key: 'amount', label: 'Betrag', type: 'number', min: 0 }];
const defaults = { title: 'Eintrag bearbeiten', fields, initial: { name: 'Miete', amount: 0 }, onSave: vi.fn(), onClose: vi.fn() };
const form = () => screen.getByRole('dialog').querySelector('form');

it('keeps drafts through translated field labels, equivalent initial objects, changed options, and preview round trips', async () => {
  const save = vi.fn();
  const original = [...fields, { key: 'status', label: 'Status', type: 'select', options: [{ value: 'open', label: 'Offen' }] }];
  const { rerender } = render(<FormModal {...defaults} fields={original} initial={{ name: 'Miete', amount: 0, status: 'open' }} onSave={save} closeOnSave={false} />);
  fireEvent.change(screen.getByLabelText('Name *'), { target: { value: 'Mein Entwurf' } });
  const translated = original.map(field => ({ ...field, label: field.key === 'name' ? 'Name EN' : field.label, options: field.options?.map(option => ({ ...option, label: 'Open EN' })) }));
  rerender(<FormModal {...defaults} fields={translated} initial={{ name: 'Miete', amount: 0, status: 'open' }} onSave={save} closeOnSave={false} />);
  expect(screen.getByLabelText('Name EN *')).toHaveValue('Mein Entwurf');
  expect(screen.getByRole('combobox', { name: 'Status' })).toHaveValue('open');
  rerender(<FormModal {...defaults} fields={[]} initial={{ name: 'Miete', amount: 0, status: 'open' }} onSave={save} closeOnSave={false}><p>Vorschau</p></FormModal>);
  rerender(<FormModal {...defaults} fields={translated} initial={{ name: 'Miete', amount: 0, status: 'open' }} onSave={save} closeOnSave={false} />);
  expect(screen.getByLabelText('Name EN *')).toHaveValue('Mein Entwurf');
  fireEvent.submit(form());
  await act(async () => {});
  expect(save).toHaveBeenCalledWith({ name: 'Mein Entwurf', amount: 0, status: 'open' });
});

it('initial data for a different record replaces the draft while new fields get defaults', () => {
  const { rerender } = render(<FormModal {...defaults} />);
  fireEvent.change(screen.getByLabelText('Name *'), { target: { value: 'Entwurf' } });
  rerender(<FormModal {...defaults} fields={[...fields, { key: 'note', label: 'Notiz', default: 'Hinweis' }]} />);
  expect(screen.getByLabelText('Name *')).toHaveValue('Entwurf');
  expect(screen.getByLabelText('Notiz')).toHaveValue('Hinweis');
  rerender(<FormModal {...defaults} initial={{ name: 'Andere Miete', amount: 20 }} />);
  expect(screen.getByLabelText('Name *')).toHaveValue('Andere Miete');
  expect(screen.getByLabelText('Betrag')).toHaveValue(20);
});

it('field labels and hints have unique instance IDs with no payload key changes', () => {
  render(<><FormModal {...defaults} /><FormModal {...defaults} title="Zweiter Eintrag" /></>);
  const inputs = screen.getAllByLabelText('Name *');
  expect(inputs[0].id).not.toBe(inputs[1].id);
  inputs.forEach(input => {
    expect(input).toHaveAttribute('name', 'name');
    expect(document.getElementById(input.getAttribute('aria-describedby'))).toHaveTextContent('Eindeutige Bezeichnung');
  });
});

it('uses a fresh focus list after fields change and excludes disabled fieldsets, hidden ancestors and negative tabindex', async () => {
  const user = userEvent.setup();
  const children = <><fieldset disabled><input aria-label="Gesperrt" /></fieldset><div hidden><button type="button">Versteckt</button></div><div style={{ display: 'none' }}><button type="button">Unsichtbar</button></div><button type="button" tabIndex={-1}>Nicht per Tab</button></>;
  const { rerender } = render(<FormModal {...defaults} saveDisabled fields={[]} >{children}</FormModal>);
  const close = screen.getByRole('button', { name: 'Schließen' });
  const cancel = screen.getByRole('button', { name: 'Abbrechen' });
  cancel.focus();
  await user.tab();
  expect(close).toHaveFocus();
  await user.tab({ shift: true });
  expect(cancel).toHaveFocus();
  rerender(<FormModal {...defaults} saveDisabled>{children}</FormModal>);
  close.focus();
  await user.tab();
  expect(screen.getByLabelText('Name *')).toHaveFocus();
  await user.tab();
  expect(screen.getByLabelText('Betrag')).toHaveFocus();
});

it('restores focus to a connected opener and tolerates a removed opener', () => {
  const opener = document.createElement('button');
  document.body.append(opener);
  opener.focus();
  const first = render(<FormModal {...defaults} />);
  expect(screen.getByLabelText('Name *')).toHaveFocus();
  first.unmount();
  expect(opener).toHaveFocus();
  const second = render(<FormModal {...defaults} />);
  opener.remove();
  expect(() => second.unmount()).not.toThrow();
});

it('busy save prevents duplicate requests and every dismissal path until completion', async () => {
  let complete;
  const save = vi.fn(() => new Promise(resolve => { complete = resolve; }));
  const close = vi.fn();
  render(<FormModal {...defaults} onSave={save} onClose={close} />);
  fireEvent.submit(form());
  fireEvent.submit(form());
  expect(save).toHaveBeenCalledTimes(1);
  expect(screen.getByRole('dialog')).toHaveAttribute('aria-busy', 'true');
  expect(screen.getByLabelText('Name *')).toBeDisabled();
  expect(screen.getByRole('button', { name: 'Schließen' })).toBeDisabled();
  expect(screen.getByRole('button', { name: 'Abbrechen' })).toBeDisabled();
  fireEvent.click(screen.getByRole('button', { name: 'Schließen' }));
  fireEvent.click(screen.getByRole('button', { name: 'Abbrechen' }));
  fireEvent.click(screen.getByRole('presentation'));
  fireEvent.keyDown(document, { key: 'Escape' });
  expect(close).not.toHaveBeenCalled();
  await act(async () => complete());
  expect(close).toHaveBeenCalledTimes(1);
  expect(screen.getByRole('dialog')).toHaveAttribute('aria-busy', 'false');
});

it('saveDisabled blocks even an explicit form submit', () => {
  const save = vi.fn();
  render(<FormModal {...defaults} saveDisabled onSave={save} />);
  fireEvent.submit(form());
  expect(save).not.toHaveBeenCalled();
});

it('shows precise server errors, links field errors, preserves inputs and permits a retry', async () => {
  const error = Object.assign(new Error('Buchung bereits vergeben'), { details: [{ loc: ['body', 'amount'], msg: 'Nur 50 EUR verfügbar' }] });
  const save = vi.fn().mockRejectedValueOnce(error).mockResolvedValueOnce(undefined);
  render(<FormModal {...defaults} onSave={save} closeOnSave={false} />);
  fireEvent.change(screen.getByLabelText('Name *'), { target: { value: 'Mein Entwurf' } });
  fireEvent.submit(form());
  const alert = await screen.findByRole('alert');
  expect(alert).toHaveTextContent('Buchung bereits vergeben');
  expect(alert).toHaveFocus();
  const amount = screen.getByLabelText('Betrag');
  expect(amount).toHaveAttribute('aria-invalid', 'true');
  expect(document.getElementById(amount.getAttribute('aria-describedby'))).toHaveTextContent('Nur 50 EUR verfügbar');
  expect(screen.getByLabelText('Name *')).toHaveValue('Mein Entwurf');
  fireEvent.submit(form());
  await act(async () => {});
  expect(save).toHaveBeenCalledTimes(2);
  expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Speichern' })).toHaveFocus();
});

it('validates native field bounds before invoking a save', async () => {
  const save = vi.fn();
  render(<FormModal {...defaults} fields={[{ key: 'amount', label: 'Betrag', type: 'number', min: 1, max: 10, required: true }]} initial={{ amount: 20 }} onSave={save} />);
  fireEvent.submit(form());
  expect(save).not.toHaveBeenCalled();
  expect(await screen.findByRole('alert')).toHaveTextContent('Bitte prüfen Sie die Pflichtfelder und Eingaben.');
});

it('column popup consumes the first Escape, and the second Escape closes the enclosing dialog', () => {
  const close = vi.fn();
  render(<FormModal {...defaults} fields={[]} onClose={close}><DataTable title="Vorschau" columns={[{ key: 'name', label: 'Name' }]} data={[{ name: 'Miete' }]} /></FormModal>);
  fireEvent.click(screen.getByRole('button', { name: 'Spalten anpassen' }));
  fireEvent.keyDown(screen.getByRole('checkbox', { name: 'Name' }), { key: 'Escape' });
  expect(close).not.toHaveBeenCalled();
  expect(screen.getByRole('button', { name: 'Spalten anpassen' })).toHaveFocus();
  fireEvent.keyDown(screen.getByRole('button', { name: 'Spalten anpassen' }), { key: 'Escape' });
  expect(close).toHaveBeenCalledTimes(1);
});

it('preserves number/null and dependent field semantics when serializing the draft', async () => {
  const save = vi.fn();
  render(<FormModal {...defaults} fields={[{ key: 'booking', label: 'Bankbuchung', type: 'select', options: [{ value: 'b1', label: 'Buchung' }], onChange: value => value === 'b1' ? { amount: 50 } : {} }, { key: 'amount', label: 'Betrag', type: 'number' }, { key: 'empty', label: 'Optional', type: 'number' }, { key: 'contract', type: 'hidden', default: 0 }]} initial={null} onSave={save} />);
  fireEvent.change(screen.getByLabelText('Bankbuchung'), { target: { value: 'b1' } });
  expect(screen.getByLabelText('Betrag')).toHaveValue(50);
  fireEvent.submit(form());
  await act(async () => {});
  expect(save).toHaveBeenCalledWith({ booking: 'b1', amount: 50, empty: null, contract: 0 });
  expect(within(screen.getByRole('dialog')).queryByLabelText('contract')).not.toBeInTheDocument();
});

it('keeps custom renderer values, selection details and dependent updates in the ordinary payload', async () => {
  const save = vi.fn();
  const customFields = [
    { key: 'unit_id', label: 'Einheit', type: 'select', onChange: (value, values, row) => ({ property_id: row.property_id, note: values.note }),
      render: ({ value, values, onChange, inputProps }) => <><input {...inputProps} value={value} readOnly aria-label="Ausgewählte Einheit" /><button type="button" onClick={() => onChange('u2', { property_id: 'p2' })}>Spätere Einheit aus {values.property_id}</button></> },
    { key: 'property_id', type: 'hidden' }, { key: 'note', label: 'Notiz' },
  ];
  render(<FormModal {...defaults} fields={customFields} initial={{ unit_id: 'u1', property_id: 'p1', note: 'Erhalten' }} onSave={save} />);
  fireEvent.click(screen.getByRole('button', { name: 'Spätere Einheit aus p1' }));
  expect(screen.getByRole('button', { name: 'Spätere Einheit aus p2' })).toBeVisible();
  expect(screen.getByLabelText('Ausgewählte Einheit')).toHaveValue('u2');
  fireEvent.submit(form());
  await act(async () => {});
  expect(save).toHaveBeenCalledWith({ unit_id: 'u2', property_id: 'p2', note: 'Erhalten' });
});
