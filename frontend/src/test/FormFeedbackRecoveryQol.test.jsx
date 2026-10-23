import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import FormModal from '../components/FormModal';
import { workspace } from '../utils/workspaceClient';

vi.mock('../contexts/AuthContext', () => ({ useAuth: () => ({ user: { id: 'form-feedback-user' } }) }));
vi.mock('../utils/workspaceClient', async original => {
  const actual = await original();
  return { ...actual, workspace: {
    list: vi.fn(), get: vi.fn(), put: vi.fn(), rebase: vi.fn(), remove: vi.fn(),
    command: () => crypto.randomUUID(),
  } };
});

const fields = [{ key: 'full_name', label: 'Name' }, { key: 'notes', label: 'Notiz', type: 'textarea' }];
const savedDraft = {
  id: 'interrupted-draft', revision: 3, context: 'tenants', source: null,
  values: { full_name: 'Wiederhergestellt', notes: 'Vor der Unterbrechung erfasst' },
  source_state: { status: 'new' },
};

beforeEach(() => {
  vi.clearAllMocks(); localStorage.clear(); sessionStorage.clear();
  window.history.replaceState({}, '', '/tenants');
  workspace.list.mockResolvedValue({ items: [], next_cursor: null });
  workspace.put.mockImplementation(async (_, id, body) => ({ id, revision: body.base_revision + 1, ...body }));
  workspace.remove.mockResolvedValue({ deleted: true });
});
afterEach(() => { cleanup(); window.history.replaceState({}, '', '/'); });

it('announces a failed save, retains the entries and offers a keyboard path back to editing', async () => {
  const onSave = vi.fn().mockRejectedValueOnce(new Error('Speichern derzeit nicht möglich')).mockResolvedValue(undefined);
  const onClose = vi.fn();
  const { container } = render(<FormModal title="Mieter" fields={fields} autosave={false} onSave={onSave} onClose={onClose} />);
  fireEvent.change(screen.getByLabelText('Name'), { target: { value: 'Anna' } });
  fireEvent.change(screen.getByLabelText('Notiz'), { target: { value: 'Bitte erhalten' } });
  fireEvent.submit(container.querySelector('form'));

  const feedback = await screen.findByRole('alert');
  expect(feedback).toHaveTextContent('Speichern derzeit nicht möglich');
  expect(feedback).toHaveTextContent('Ihre Eingaben bleiben erhalten');
  await waitFor(() => expect(feedback).toHaveFocus());
  expect(screen.getByLabelText('Name')).toHaveValue('Anna');
  expect(screen.getByLabelText('Notiz')).toHaveValue('Bitte erhalten');
  expect(onClose).not.toHaveBeenCalled();

  fireEvent.click(screen.getByRole('button', { name: 'Eingaben prüfen' }));
  expect(screen.getByLabelText('Name')).toHaveFocus();
  fireEvent.submit(container.querySelector('form'));
  await waitFor(() => expect(onClose).toHaveBeenCalledOnce());
  expect(onSave).toHaveBeenCalledTimes(2);
  expect(onSave).toHaveBeenLastCalledWith({ full_name: 'Anna', notes: 'Bitte erhalten' });
});

it('does not clear the autosaved draft when the business save fails', async () => {
  const onSave = vi.fn().mockRejectedValue(new Error('Server vorübergehend offline'));
  const { container } = render(<FormModal title="Mieter" fields={fields} onSave={onSave} onClose={vi.fn()} />);
  await waitFor(() => expect(screen.getByLabelText('Name')).toBeEnabled());
  fireEvent.change(screen.getByLabelText('Name'), { target: { value: 'Offline-Eingabe' } });
  fireEvent.submit(container.querySelector('form'));
  await screen.findByText('Server vorübergehend offline');
  expect(workspace.remove).not.toHaveBeenCalled();
  expect(JSON.parse(localStorage.getItem(localStorage.key(0))).values.full_name).toBe('Offline-Eingabe');
  expect(screen.getByLabelText('Name')).toHaveValue('Offline-Eingabe');
});

it('asks before deleting an interrupted draft and allows cancel without a delete', async () => {
  workspace.list.mockResolvedValue({ items: [savedDraft], next_cursor: null });
  const onSave = vi.fn();
  render(<FormModal title="Mieter" fields={fields} draftContext="tenants" onSave={onSave} onClose={vi.fn()} />);
  await screen.findByText('Ungespeicherter Entwurf vorhanden');
  expect(screen.getByLabelText('Name')).toBeDisabled();

  const discard = screen.getByRole('button', { name: 'Entwurf verwerfen' });
  expect(discard).toHaveAttribute('aria-expanded', 'false');
  fireEvent.click(discard);
  expect(discard).toHaveAttribute('aria-expanded', 'true');
  expect(screen.getByRole('group', { name: 'Entwurf verwerfen bestätigen' })).toHaveTextContent('Die ungespeicherten Eingaben gehen verloren');
  expect(workspace.remove).not.toHaveBeenCalled();

  fireEvent.click(screen.getByRole('button', { name: 'Entwurf behalten' }));
  expect(discard).toHaveFocus();
  expect(screen.queryByRole('group', { name: 'Entwurf verwerfen bestätigen' })).not.toBeInTheDocument();
  expect(workspace.remove).not.toHaveBeenCalled();
  expect(screen.getByText('Ungespeicherter Entwurf vorhanden')).toBeInTheDocument();

  fireEvent.click(discard);
  await act(async () => { fireEvent.click(screen.getByRole('button', { name: 'Endgültig verwerfen' })); });
  await waitFor(() => expect(workspace.remove).toHaveBeenCalledTimes(1));
  expect(workspace.remove).toHaveBeenCalledWith('drafts', 'interrupted-draft', expect.objectContaining({ base_revision: 3 }));
  expect(screen.queryByText('Ungespeicherter Entwurf vorhanden')).not.toBeInTheDocument();
  await waitFor(() => expect(screen.getByLabelText('Name')).toHaveFocus());
  expect(onSave).not.toHaveBeenCalled();
});

it('returns focus to recovered inputs without sending the domain action', async () => {
  workspace.list.mockResolvedValue({ items: [savedDraft], next_cursor: null });
  const onSave = vi.fn().mockResolvedValue(undefined);
  const onClose = vi.fn();
  const { container } = render(<FormModal title="Mieter" fields={fields} draftContext="tenants" onSave={onSave} onClose={onClose} />);
  fireEvent.click(await screen.findByRole('button', { name: 'Entwurf wiederaufnehmen' }));
  await waitFor(() => expect(screen.getByLabelText('Name')).toHaveValue('Wiederhergestellt'));
  expect(screen.getByLabelText('Notiz')).toHaveValue('Vor der Unterbrechung erfasst');
  await waitFor(() => expect(screen.getByLabelText('Name')).toHaveFocus());
  expect(onSave).not.toHaveBeenCalled();
  expect(onClose).not.toHaveBeenCalled();
  fireEvent.submit(container.querySelector('form'));
  await waitFor(() => expect(onSave).toHaveBeenCalledWith({
    full_name: 'Wiederhergestellt', notes: 'Vor der Unterbrechung erfasst',
  }));
});

it('ignores a late failed save from a form that was replaced by another record', async () => {
  let rejectPrevious;
  const onSave = vi.fn(() => new Promise((_, reject) => { rejectPrevious = reject; }));
  const initial = { id: 'a', full_name: 'Erster', notes: '' };
  const { container, rerender } = render(<FormModal title="Mieter" fields={fields} autosave={false} initial={initial} onSave={onSave} onClose={vi.fn()} />);
  fireEvent.submit(container.querySelector('form'));
  rerender(<FormModal title="Mieter" fields={fields} autosave={false} initial={{ id: 'b', full_name: 'Zweiter' }} onSave={onSave} onClose={vi.fn()} />);
  await act(async () => { rejectPrevious(new Error('Alter Fehler')); });
  expect(screen.getByLabelText('Name')).toHaveValue('Zweiter');
  expect(screen.queryByText('Alter Fehler')).not.toBeInTheDocument();
});


it('marks the exact 422 fields and guides review to the first invalid field without losing input', async () => {
  const invalid = Object.assign(new Error('Bitte die Eingaben korrigieren'), {
    statusCode: 422, details: [
      { loc: ['body', 'notes'], msg: 'Notiz genauer beschreiben' },
      { loc: ['body', 'email'], msg: 'E-Mail-Adresse ungültig' },
      { loc: ['body', 'unrelated'], msg: 'Unbekannt' },
    ],
  });
  const onSave = vi.fn().mockRejectedValueOnce(invalid).mockResolvedValue(undefined);
  const onClose = vi.fn();
  const editedFields = [
    { key: 'full_name', label: 'Name' }, { key: 'email', label: 'E-Mail', hint: 'Gültige Adresse verwenden' },
    { key: 'notes', label: 'Notiz', type: 'textarea', hint: 'Zusätzliche Angaben' },
  ];
  const { container } = render(<FormModal title="Mieter" fields={editedFields} autosave={false}
    onSave={onSave} onClose={onClose} />);
  fireEvent.change(screen.getByLabelText('Name'), { target: { value: 'Anna' } });
  fireEvent.change(screen.getByLabelText('E-Mail'), { target: { value: 'bad' } });
  fireEvent.change(screen.getByLabelText('Notiz'), { target: { value: 'Unfertige Notiz' } });
  fireEvent.submit(container.querySelector('form'));
  const summary = await screen.findByRole('alert');
  await waitFor(() => expect(summary).toHaveFocus());

  const email = screen.getByLabelText('E-Mail');
  const notes = screen.getByLabelText('Notiz');
  expect(email).toHaveAttribute('aria-invalid', 'true');
  expect(email).toHaveAttribute('aria-describedby', 'form-error-email form-hint-email');
  expect(document.getElementById('form-hint-email')).toHaveTextContent('Gültige Adresse verwenden');
  expect(document.getElementById('form-error-email')).toHaveTextContent('E-Mail-Adresse ungültig');
  expect(notes).toHaveAttribute('aria-invalid', 'true');
  expect(document.getElementById('form-error-notes')).toHaveTextContent('Notiz genauer beschreiben');
  expect(notes).toHaveAttribute('aria-describedby', 'form-error-notes form-hint-notes');
  expect(screen.getByLabelText('Name')).not.toHaveAttribute('aria-invalid');
  expect(screen.getByLabelText('Name')).toHaveValue('Anna');
  expect(notes).toHaveValue('Unfertige Notiz');

  fireEvent.click(screen.getByRole('button', { name: 'Eingaben prüfen' }));
  expect(email).toHaveFocus(); // form order, not server error order
  fireEvent.change(email, { target: { value: 'anna@example.test' } });
  expect(email).not.toHaveAttribute('aria-invalid');
  expect(email).toHaveAttribute('aria-describedby', 'form-hint-email');
  expect(document.getElementById('form-error-email')).toBeNull();
  expect(notes).toHaveAttribute('aria-invalid', 'true'); // unrelated field stays visible
  fireEvent.submit(container.querySelector('form'));
  await waitFor(() => expect(onClose).toHaveBeenCalledOnce());
  expect(onSave).toHaveBeenCalledTimes(2);
  expect(onSave).toHaveBeenLastCalledWith({ full_name: 'Anna', email: 'anna@example.test', notes: 'Unfertige Notiz' });
});

it('links structured field messages for select, date and number inputs but ignores unrelated details', async () => {
  const error = Object.assign(new Error('Ungültige Eingabe'), {
    statusCode: 422, details: [
      { field: 'state', message: 'Auswahl prüfen' },
      { field: 'start_date', message: 'Datum liegt zu früh' },
      { field: 'amount', message: 'Betrag zu klein' },
      { field: 'state.deep', message: 'Verschachtelt' },
    ],
  });
  const fieldsWithTypes = [
    { key: 'state', label: 'Status', type: 'select', options: [{ value: 'open', label: 'Offen' }], hint: 'Status auswählen' },
    { key: 'start_date', label: 'Datum', type: 'date', hint: 'Prüfen Sie den Zeitraum' },
    { key: 'amount', label: 'Betrag', type: 'number', hint: 'Betrag in EUR' },
  ];
  const { container } = render(<FormModal title="Vorgang" fields={fieldsWithTypes} autosave={false}
    onSave={vi.fn().mockRejectedValue(error)} onClose={vi.fn()} />);
  fireEvent.submit(container.querySelector('form'));
  await screen.findByRole('alert');
  for (const label of ['Status', 'Datum', 'Betrag']) expect(screen.getByLabelText(label)).toHaveAttribute('aria-invalid', 'true');
  expect(screen.getByLabelText('Status')).toHaveAttribute('aria-describedby', 'form-error-state form-hint-state');
  expect(screen.getByLabelText('Datum')).toHaveAttribute('aria-describedby', 'form-error-start_date form-hint-start_date');
  expect(screen.getByLabelText('Betrag')).toHaveAttribute('aria-describedby', 'form-error-amount form-hint-amount');
  fireEvent.click(screen.getByRole('button', { name: 'Eingaben prüfen' }));
  expect(screen.getByLabelText('Status')).toHaveFocus();
  fireEvent.click(screen.getByRole('button', { name: 'Heute eintragen' }));
  expect(screen.getByLabelText('Datum')).not.toHaveAttribute('aria-invalid');
  expect(screen.getByLabelText('Datum')).toHaveAttribute('aria-describedby', 'form-hint-start_date');
  expect(screen.getByLabelText('Betrag')).toHaveAttribute('aria-invalid', 'true');
});

it('Escape only cancels recovered draft deletion and returns focus without deleting or saving', async () => {
  workspace.list.mockResolvedValue({ items: [savedDraft], next_cursor: null });
  const onClose = vi.fn(); const onSave = vi.fn();
  render(<FormModal title="Mieter" fields={fields} draftContext="tenants" onSave={onSave} onClose={onClose} />);
  await screen.findByText('Ungespeicherter Entwurf vorhanden');
  const discard = screen.getByRole('button', { name: 'Entwurf verwerfen' });
  discard.focus();
  fireEvent.click(discard);
  expect(screen.getByRole('button', { name: 'Entwurf behalten' })).toHaveFocus();
  expect(discard).toHaveAttribute('aria-controls', 'form-draft-discard-confirm');
  fireEvent.keyDown(document, { key: 'Enter', ctrlKey: true });
  expect(onSave).not.toHaveBeenCalled();
  fireEvent.keyDown(document, { key: 'Escape' });
  expect(screen.queryByRole('group', { name: 'Entwurf verwerfen bestätigen' })).not.toBeInTheDocument();
  expect(discard).toHaveFocus();
  expect(discard).toHaveAttribute('aria-expanded', 'false');
  expect(discard).not.toHaveAttribute('aria-controls');
  expect(onClose).not.toHaveBeenCalled();
  expect(onSave).not.toHaveBeenCalled();
  expect(workspace.remove).not.toHaveBeenCalled();
  expect(screen.getByText('Ungespeicherter Entwurf vorhanden')).toBeInTheDocument();
  fireEvent.keyDown(document, { key: 'Escape' });
  expect(onClose).toHaveBeenCalledOnce(); // Only the second Escape can close the untouched form.
  expect(workspace.remove).not.toHaveBeenCalled();
});

it('does not close or repeat actions if Escape is pressed during confirmed draft deletion', async () => {
  workspace.list.mockResolvedValue({ items: [savedDraft], next_cursor: null });
  let finishDelete;
  workspace.remove.mockImplementationOnce(() => new Promise(resolve => { finishDelete = resolve; }));
  const onClose = vi.fn(); const onSave = vi.fn();
  render(<FormModal title="Mieter" fields={fields} draftContext="tenants" onSave={onSave} onClose={onClose} />);
  fireEvent.click(await screen.findByRole('button', { name: 'Entwurf verwerfen' }));
  fireEvent.click(screen.getByRole('button', { name: 'Endgültig verwerfen' }));
  await waitFor(() => expect(workspace.remove).toHaveBeenCalledTimes(1));
  fireEvent.keyDown(document, { key: 'Escape' });
  expect(onClose).not.toHaveBeenCalled();
  expect(onSave).not.toHaveBeenCalled();
  expect(workspace.remove).toHaveBeenCalledTimes(1);
  await act(async () => { finishDelete({ deleted: true }); });
  await waitFor(() => expect(screen.queryByText('Ungespeicherter Entwurf vorhanden')).not.toBeInTheDocument());
  expect(onSave).not.toHaveBeenCalled();
  expect(workspace.remove).toHaveBeenCalledTimes(1);
});
