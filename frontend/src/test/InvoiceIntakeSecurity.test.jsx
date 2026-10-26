import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import EInvoiceIntakes from '../features/invoiceReview/EInvoiceIntakes';
import PaymentSecurity, { BankModeSettings } from '../features/invoiceReview/PaymentSecurity';
import { api } from '../api';

vi.mock('../api', () => ({ api: { get: vi.fn(), list: vi.fn(), post: vi.fn(), put: vi.fn(), upload: vi.fn(), getFile: vi.fn() } }));
vi.mock('../i18n', () => ({ useTranslation: () => ({ t: key => key, locale: 'de-DE' }) }));
const access = vi.hoisted(() => ({ write: true, user: { id: 'owner', role: 'eigentuemer' } }));
vi.mock('../contexts/AuthContext', () => ({ useCanWrite: () => access.write, useAuth: () => ({ user: access.user }) }));
const props = [{ id: 'p', name: 'Prüfhaus' }];
const intake = { id: 'e', property_id: 'p', filename: 'beleg.xml', reading: {}, state: 'technical_error',
  revision: 2, blockers: ['Lokaler Validator nicht verfügbar.'], validations: [], validation_number: 1 };
const bank = { revision: 'a'.repeat(64), authorized: false, eligible: true, amount: 119, blockers: [],
  policy: { effective_mode: 'four_eyes' }, authorization_history: [], recipient: {
    id: 'r', number: 1, name: 'Lieferant', iban: 'DE89370400440532013000', created_by: 'owner' } };
const show = node => render(<MemoryRouter initialEntries={['/invoice-review/i#bankfreigabe']}>{node}</MemoryRouter>);
beforeEach(() => {
  vi.resetAllMocks(); access.write = true; access.user = { id: 'owner', role: 'eigentuemer' };
  api.list.mockResolvedValue([]);
});

describe('structured invoice intake', () => {
  it('retains the upload command after a lost response', async () => {
    api.get.mockImplementation(path => Promise.resolve(path.includes('?') ? { items: [], total: 0 } : intake));
    api.upload.mockRejectedValueOnce(new Error('Antwort unterbrochen')).mockResolvedValueOnce(intake);
    show(<EInvoiceIntakes properties={props} choicesReady />);
    await userEvent.selectOptions(screen.getByLabelText('Immobilie'), 'p');
    await userEvent.upload(screen.getByLabelText(/Originalbeleg/), new File(['<Invoice/>'], 'beleg.xml', { type: 'application/xml' }));
    expect(screen.getByLabelText('Immobilie')).toHaveValue('p');
    expect(screen.getByLabelText('Immobilie')).toBeValid();
    expect(screen.getByLabelText(/Originalbeleg/).files[0].name).toBe('beleg.xml');
    // jsdom's required-file validity ignores userEvent's synthetic FileList.
    // Native file selection/constraint validation is covered by the browser flow.
    fireEvent.submit(screen.getByRole('button', { name: 'Beleg einlesen' }).closest('form'));
    expect(await screen.findByRole('alert')).toHaveTextContent('Antwort unterbrochen');
    const first = api.upload.mock.calls[0][2].idempotencyKey;
    fireEvent.submit(screen.getByRole('button', { name: 'Beleg einlesen' }).closest('form'));
    await screen.findByRole('dialog');
    expect(api.upload.mock.calls[1][2].idempotencyKey).toBe(first);
    expect(api.upload.mock.calls[1][1].get('property_id')).toBe('p');
  });

  it('exposes a technical failure without allowing receipt acceptance', async () => {
    api.get.mockImplementation(path => Promise.resolve(path.includes('?') ? { items: [intake], total: 1 } : intake));
    show(<EInvoiceIntakes properties={props} choicesReady initialIntake="e" />);
    expect(await screen.findByRole('button', { name: 'Zuordnung bestätigen und übernehmen' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Erneut prüfen' })).toBeEnabled();
    expect(screen.getByRole('button', { name: 'Original herunterladen' })).toBeEnabled();
    expect(api.post).not.toHaveBeenCalled();
  });

  it('provides readonly access without upload, validation or acceptance controls', async () => {
    access.write = false;
    api.get.mockImplementation(path => Promise.resolve(path.includes('?') ? { items: [intake], total: 1 } : intake));
    show(<EInvoiceIntakes properties={props} choicesReady initialIntake="e" />);
    await screen.findByRole('button', { name: 'Original herunterladen' });
    expect(screen.queryByRole('button', { name: 'Beleg einlesen' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Erneut prüfen' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Zuordnung bestätigen und übernehmen' })).not.toBeInTheDocument();
  });
});

describe('bank authorization', () => {
  it('blocks self approval in standard mode and displays the exact version and amount', async () => {
    api.get.mockResolvedValue(bank);
    show(<PaymentSecurity invoiceId="i" />);
    expect(await screen.findByRole('button', { name: 'Diesen Betrag und Empfänger freigeben' })).toBeDisabled();
    expect(screen.getByText('Empfänger, Version 1')).toBeInTheDocument();
    expect(screen.getByText(/Eine andere berechtigte Person/)).toBeInTheDocument();
    expect(screen.queryByLabelText('Neuer Zwei-Faktor-Code')).not.toBeInTheDocument();
  });

  it('clears failed TOTP input and retains the command identity for a retry', async () => {
    api.get.mockResolvedValue({ ...bank, policy: { effective_mode: 'single_user' } });
    api.post.mockRejectedValue(new Error('Code nicht gültig'));
    show(<PaymentSecurity invoiceId="i" />);
    const button = await screen.findByRole('button', { name: 'Diesen Betrag und Empfänger freigeben' });
    fireEvent.change(screen.getByLabelText('Dokumentierte Gegenprüfung'), { target: { value: 'Kontaktnummer aus bestehendem Vertrag angerufen.' } });
    fireEvent.change(screen.getByLabelText('Freigabebegründung'), { target: { value: 'Betrag mit Originalbeleg verglichen.' } });
    fireEvent.change(screen.getByLabelText('Neuer Zwei-Faktor-Code'), { target: { value: '123456' } });
    fireEvent.click(button);
    await screen.findByRole('alert');
    expect(screen.getByLabelText('Neuer Zwei-Faktor-Code')).toHaveValue('');
    fireEvent.change(screen.getByLabelText('Neuer Zwei-Faktor-Code'), { target: { value: '234567' } });
    fireEvent.click(button);
    await waitFor(() => expect(api.post).toHaveBeenCalledTimes(2));
    expect(api.post.mock.calls[1][1].idempotency_key).toBe(api.post.mock.calls[0][1].idempotency_key);
    expect(api.post.mock.calls[1][1].expected_revision).toBe(bank.revision);
  });

  it('reserves single-user configuration for the owner', () => {
    access.user.role = 'buchhaltung';
    show(<BankModeSettings />);
    expect(screen.queryByRole('button', { name: 'Einzelbenutzermodus verwalten' })).not.toBeInTheDocument();
    expect(api.get).not.toHaveBeenCalled();
  });
});
