import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, expect, it, vi } from 'vitest';
import FormModal from '../components/FormModal';
import { annotateRevisions, EDIT_REVISION } from '../editRevision';
import german from '../../../i18n/de-DE.json';

const get = vi.hoisted(() => vi.fn());
vi.mock('../api', () => ({ api: { get } }));
vi.mock('../i18n', () => ({ useTranslation: () => ({ t: (key, params) => {
  let value = key.split('.').reduce((current, part) => current?.[part], german) || key;
  Object.entries(params || {}).forEach(([name, replacement]) => { value = value.replace(`{{${name}}}`, replacement); });
  return value;
} }) }));

const fields = [{ key: 'name', label: 'Name', required: true }, { key: 'description', label: 'Beschreibung' }];
const original = () => annotateRevisions({ id: 'id-1', name: 'Original', description: 'Alt', updated_at: '2026-10-01T08:00:00.123456' }, '/properties');
const current = () => annotateRevisions({ ...original(), name: 'Server A', updated_at: '2026-10-01T08:01:00.654321' }, '/properties');
const conflict = () => Object.assign(new Error('Zwischenzeitlich geändert'), { isEditConflict: true, resourcePath: '/properties/id-1' });
const submit = () => fireEvent.submit(screen.getByRole('dialog').querySelector('form'));
beforeEach(() => { get.mockReset(); });

it('keeps the draft and original revision through background GETs and changing initial props', async () => {
  const save = vi.fn().mockRejectedValue(conflict());
  const initial = original();
  const { rerender } = render(<FormModal title="Bearbeiten" fields={fields} initial={initial} onSave={save} onClose={vi.fn()} />);
  fireEvent.change(screen.getByLabelText('Name *'), { target: { value: 'Entwurf B' } });
  rerender(<FormModal title="Bearbeiten" fields={fields} initial={current()} onSave={save} onClose={vi.fn()} />);
  expect(screen.getByLabelText('Name *')).toHaveValue('Entwurf B');
  submit();
  await screen.findByRole('region', { name: 'Änderungen abgleichen' });
  expect(save.mock.calls[0][0][EDIT_REVISION].updatedAt).toContain('.123456');
  expect(get).not.toHaveBeenCalled();
  expect(screen.getByLabelText('Name *')).toHaveValue('Entwurf B');
});

it('requires an explicit choice for colliding fields and never auto-saves the reconciliation', async () => {
  const save = vi.fn().mockRejectedValueOnce(conflict()).mockResolvedValueOnce({});
  const close = vi.fn();
  get.mockResolvedValue(current());
  render(<FormModal title="Bearbeiten" fields={fields} initial={original()} onSave={save} onClose={close} />);
  fireEvent.change(screen.getByLabelText('Name *'), { target: { value: 'Entwurf B' } });
  submit();
  await screen.findByText('Ihre Eingaben bleiben erhalten.', { exact: false });
  fireEvent.click(screen.getByRole('button', { name: 'Aktuellen Stand prüfen' }));
  const reconcile = await screen.findByRole('button', { name: 'Abgleich übernehmen' });
  expect(reconcile).toBeDisabled();
  expect(screen.getByText('Server A')).toBeVisible();
  fireEvent.change(screen.getByRole('combobox', { name: 'Wert für Name auswählen' }), { target: { value: 'draft' } });
  fireEvent.click(reconcile);
  expect(save).toHaveBeenCalledTimes(1);
  expect(close).not.toHaveBeenCalled();
  expect(screen.getByLabelText('Name *')).toHaveValue('Entwurf B');
  submit();
  await waitFor(() => expect(save).toHaveBeenCalledTimes(2));
  expect(save.mock.calls[1][0][EDIT_REVISION].updatedAt).toContain('.654321');
  expect(save.mock.calls[1][0].name).toBe('Entwurf B');
  await waitFor(() => expect(close).toHaveBeenCalledTimes(1));
});

it('merges independently changed fields only after explicit reconciliation', async () => {
  const save = vi.fn().mockRejectedValue(conflict());
  get.mockResolvedValue(current());
  render(<FormModal title="Bearbeiten" fields={fields} initial={original()} onSave={save} onClose={vi.fn()} />);
  fireEvent.change(screen.getByLabelText('Beschreibung'), { target: { value: 'Meine neue Notiz' } });
  submit();
  await screen.findByRole('button', { name: 'Aktuellen Stand prüfen' });
  fireEvent.click(screen.getByRole('button', { name: 'Aktuellen Stand prüfen' }));
  const reconcile = await screen.findByRole('button', { name: 'Abgleich übernehmen' });
  expect(screen.queryByRole('combobox')).not.toBeInTheDocument();
  expect(screen.getByLabelText('Name *')).toHaveValue('Original');
  fireEvent.click(reconcile);
  expect(screen.getByLabelText('Name *')).toHaveValue('Server A');
  expect(screen.getByLabelText('Beschreibung')).toHaveValue('Meine neue Notiz');
  expect(save).toHaveBeenCalledTimes(1);
});

it('failed refresh and deleted records preserve editable draft and offer a safe retry', async () => {
  const save = vi.fn().mockRejectedValue(conflict());
  get.mockRejectedValueOnce(new Error('Laden fehlgeschlagen')).mockRejectedValueOnce(Object.assign(new Error('Missing'), { statusCode: 404 })).mockResolvedValueOnce(current());
  render(<FormModal title="Bearbeiten" fields={fields} initial={original()} onSave={save} onClose={vi.fn()} />);
  fireEvent.change(screen.getByLabelText('Beschreibung'), { target: { value: 'Bleibt erhalten' } });
  submit();
  const inspect = await screen.findByRole('button', { name: 'Aktuellen Stand prüfen' });
  fireEvent.click(inspect);
  await screen.findByText('Laden fehlgeschlagen');
  expect(screen.getByLabelText('Beschreibung')).toHaveValue('Bleibt erhalten');
  fireEvent.click(inspect);
  await screen.findByText('Der Datensatz wurde entfernt.', { exact: false });
  expect(screen.queryByRole('button', { name: 'Abgleich übernehmen' })).not.toBeInTheDocument();
  fireEvent.click(inspect);
  await screen.findByRole('button', { name: 'Abgleich übernehmen' });
  expect(save).toHaveBeenCalledTimes(1);
});

it('aborts the inspection when the editor closes and ignores a late response', async () => {
  let resolve;
  get.mockImplementation(() => new Promise(done => { resolve = done; }));
  const { unmount } = render(<FormModal title="Bearbeiten" fields={fields} initial={original()} onSave={vi.fn().mockRejectedValue(conflict())} onClose={vi.fn()} />);
  submit();
  fireEvent.click(await screen.findByRole('button', { name: 'Aktuellen Stand prüfen' }));
  const signal = get.mock.calls[0][1].signal;
  unmount();
  expect(signal.aborted).toBe(true);
  await act(async () => resolve(current()));
});

it('ordinary validation/duplicate errors do not expose an edit-conflict workflow', async () => {
  render(<FormModal title="Bearbeiten" fields={fields} initial={original()} onSave={vi.fn().mockRejectedValue(new Error('Doppelt'))} onClose={vi.fn()} />);
  submit();
  await screen.findByText('Doppelt');
  expect(screen.queryByRole('region', { name: 'Änderungen abgleichen' })).not.toBeInTheDocument();
});
