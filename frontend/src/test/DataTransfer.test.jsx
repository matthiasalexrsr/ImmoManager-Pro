import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import ImportWizard from '../features/dataTransfer/ImportWizard';
import CustomerExports from '../features/dataTransfer/CustomerExports';
import { api } from '../api';

vi.mock('../api', () => ({ api: { get: vi.fn(), list: vi.fn(), post: vi.fn(), upload: vi.fn(), getBlob: vi.fn(), captureSession: vi.fn(() => () => {}) } }));
const batch = { id: 'batch-1', state: 'ready', revision: 1, source_system: 'Altsystem', mappings: { columns: {}, references: {} },
  preview: { errors: [], error_count: 0, warnings: [], warning_count: 0, duplicates: [], skipped_existing: {}, document_versions: 0,
    controls: { units: { count: 10000, amounts: {} }, receivables: { count: 1, amounts: { amount_due: '123.45' } } },
    files: [{ filename: 'units.csv', entity: 'units', headers: ['external_ref', 'label'], mapping: { external_ref: 'external_ref', label: 'label' } }], sample: {} } };
const schema = { entities: { units: { label: 'Einheiten', fields: ['external_ref', 'label'], required: ['external_ref', 'label'] } } };
beforeEach(() => {
  vi.resetAllMocks();
  api.list.mockResolvedValue([{ id: 'portfolio', name: 'Zielbestand' }]);
  api.get.mockImplementation(path => Promise.resolve(path.endsWith('/schema') ? schema : path.includes('?') ? { items: [batch], total: 1 } : batch));
});
const open = async () => {
  render(<ImportWizard />);
  await userEvent.click(await screen.findByRole('button', { name: /Altsystem/ }));
  await screen.findByRole('heading', { name: 'Übernahme: Altsystem' });
};
const confirm = async () => {
  await userEvent.type(screen.getByLabelText('Prüfvermerk'), 'Quellmengen und Beträge abgeglichen.');
  await userEvent.click(screen.getByLabelText(/Zuordnungen, Mengen und Beträge/));
};

describe('reviewed data import', () => {
  it('never commits from preview and requires reconciliation before confirmation', async () => {
    await open();
    expect(screen.getByRole('button', { name: 'Übernahme verbindlich bestätigen' })).toBeDisabled();
    expect(screen.getByText('10000')).toBeInTheDocument();
    expect(screen.getByText('amount_due: 123.45')).toBeInTheDocument();
    expect(api.post).not.toHaveBeenCalled();
    await confirm();
    api.post.mockResolvedValue({ ...batch, state: 'committed', revision: 2, result: { reason: 'Geprüft' } });
    await userEvent.click(screen.getByRole('button', { name: 'Übernahme verbindlich bestätigen' }));
    await screen.findByText(/Die bestätigte Übernahme wurde gemeinsam gespeichert/);
    expect(screen.getByRole('heading', { name: 'Übernahme: Altsystem' })).toHaveFocus();
    expect(api.post.mock.calls[0][1].expected_revision).toBe(1);
  });

  it('keeps the same command on a lost response and displays target conflicts', async () => {
    await open(); await confirm();
    api.post.mockRejectedValueOnce(new Error('Antwort unterbrochen')).mockRejectedValueOnce(new Error('Zielbestand geändert, Vorschau erneuern.'));
    const button = screen.getByRole('button', { name: 'Übernahme verbindlich bestätigen' });
    await userEvent.click(button);
    expect(await screen.findByRole('alert')).toHaveTextContent('Antwort unterbrochen');
    const first = api.post.mock.calls[0][1].idempotency_key;
    await userEvent.click(button);
    expect(await screen.findByRole('alert')).toHaveTextContent('Zielbestand geändert');
    expect(api.post.mock.calls[1][1].idempotency_key).toBe(first);
    expect(api.post.mock.calls).toHaveLength(2);
  });

  it('a mapping edit invalidates confirmation and needs a new preview revision', async () => {
    await open(); await confirm();
    await userEvent.click(screen.getByText('Feldzuordnung: units.csv'));
    await userEvent.selectOptions(screen.getByLabelText('label (Pflicht)'), 'external_ref');
    expect(screen.getByRole('button', { name: 'Übernahme verbindlich bestätigen' })).toBeDisabled();
    api.post.mockResolvedValue({ ...batch, revision: 2 });
    await userEvent.click(screen.getByRole('button', { name: 'Vorschau mit aktuellem Zielbestand erneuern' }));
    await screen.findByText(/Prüfstand 2/);
    expect(api.post.mock.calls[0][1].columns['units.csv'].label).toBe('external_ref');
    expect(screen.getByLabelText(/Zuordnungen, Mengen und Beträge/)).not.toBeChecked();
  });

  it('retries source upload without making a new batch identity', async () => {
    api.get.mockImplementation(path => Promise.resolve(path.endsWith('/schema') ? schema : { items: [], total: 0 }));
    api.upload.mockRejectedValueOnce(new Error('Übertragung unterbrochen')).mockResolvedValueOnce(batch);
    render(<ImportWizard />);
    await userEvent.type(screen.getByLabelText('Quellsystem / stabiler Importname'), 'Altsystem');
    await waitFor(() => expect(screen.getByLabelText('Zielbestand für CSV')).toBeEnabled());
    await userEvent.selectOptions(screen.getByLabelText('Zielbestand für CSV'), 'portfolio');
    await userEvent.upload(screen.getByLabelText(/Dateien \(bis sechs/), new File(['external_ref;label\nA;WE1'], 'units.csv', { type: 'text/csv' }));
    const form = screen.getByRole('button', { name: 'Vorschau erstellen' }).closest('form');
    fireEvent.submit(form);
    expect(await screen.findByRole('alert')).toHaveTextContent('Übertragung unterbrochen');
    fireEvent.submit(form);
    await screen.findByRole('heading', { name: 'Übernahme: Altsystem' });
    expect(api.upload.mock.calls[0][2].idempotencyKey).toBe(api.upload.mock.calls[1][2].idempotencyKey);
  });
});

it('customer export exposes failed jobs and keeps creation retries idempotent', async () => {
  api.get.mockResolvedValue({ items: [{ id: 'failed', state: 'failed', created_at: '2026-10-26T10:00:00', error: 'Original fehlt.' }], total: 1 });
  api.post.mockRejectedValue(new Error('Antwort verloren'));
  render(<CustomerExports />);
  expect(await screen.findByText('Original fehlt.')).toBeInTheDocument();
  await userEvent.click(screen.getByRole('button', { name: 'Kundenexport erstellen' }));
  await screen.findByText(/Antwort verloren/);
  await userEvent.click(screen.getByRole('button', { name: 'Kundenexport erstellen' }));
  expect(api.post.mock.calls[0][1].idempotency_key).toBe(api.post.mock.calls[1][1].idempotency_key);
});
