import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import AiReadingPanel from '../features/aiReading/AiReadingPanel';
import { preferredReader } from '../features/aiReading/aiReadingApi';

afterEach(cleanup);
const deferred = () => { let resolve, reject; const promise = new Promise((yes, no) => { resolve = yes; reject = no; }); return { promise, resolve, reject }; };
const surface = { id: 'invoice', label: 'Rechnung', may_use: true, ai_allowed: true, needs_ai: false, fields: [{ name: 'supplier', label: 'Lieferant', kind: 'text' }] };
const options = extra => ({ readers: [{ id: 'local', label: 'Lokale Regeln', available: true, ai: false }, { id: 'claude', label: 'Claude', available: true, ai: true }], default_reader: 'claude', ai_enabled: true, surfaces: [surface], ...extra });
const reading = extra => ({ id: 'reading-old', revision: 1, surface: 'invoice', reader: 'claude', reader_label: 'Claude', status: 'open', chat: true, values: { supplier: { value: 'Alter Lieferant', confidence: 'high' } }, messages: [], duplicates: [], ...extra });
const service = extra => ({ options: vi.fn().mockResolvedValue(options()), start: vi.fn().mockResolvedValue(reading()), say: vi.fn(), decide: vi.fn(), finish: vi.fn(), ...extra });
const view = (api, extra = {}) => <MemoryRouter><AiReadingPanel surface="invoice" source={{ fileUrl: '/uploads/documents/old.pdf' }} params={{ property_id: 'old-property' }} service={api} {...extra} /></MemoryRouter>;

describe('Bindung der Dokumentlesung an Quelle und Sitzung', () => {
  it.each([
    { source: { fileUrl: '/uploads/documents/new.pdf' } },
    { params: { property_id: 'new-property' } },
  ])('verwirft eine verspätete Lesung nach einem Quellen- oder Aktenwechsel (%j)', async change => {
    const pending = deferred(); const api = service({ start: vi.fn().mockReturnValue(pending.promise) }); const onApply = vi.fn();
    const mounted = render(view(api, { onApply }));
    fireEvent.click(await screen.findByRole('button', { name: 'Einlesen' }));
    mounted.rerender(view(api, { onApply, ...change }));
    await act(async () => pending.resolve(reading()));
    expect(screen.queryByText('Alter Lieferant')).toBeNull();
    expect(screen.queryByRole('button', { name: 'In die Maske übernehmen' })).toBeNull();
    expect(onApply).not.toHaveBeenCalled();
    expect(await screen.findByRole('button', { name: 'Einlesen' })).toBeEnabled();
  });

  it('löst nach dem Schließen keine verspätete Entscheidung im Fachformular aus', async () => {
    const pending = deferred(); const duplicate = { kind: 'invoice', id: 'i1', href: '/invoice-review/i1', title: 'Vorhandene Rechnung' };
    const api = service({ start: vi.fn().mockResolvedValue(reading({ duplicates: [duplicate] })), decide: vi.fn().mockReturnValue(pending.promise) });
    const onOpenExisting = vi.fn(); const mounted = render(view(api, { onOpenExisting }));
    fireEvent.click(await screen.findByRole('button', { name: 'Einlesen' }));
    fireEvent.click(await screen.findByRole('button', { name: 'Öffnen' })); mounted.unmount();
    await act(async () => pending.resolve(reading({ revision: 2, decision: { action: 'use_existing' } })));
    expect(onOpenExisting).not.toHaveBeenCalled();
  });

  it.each(['workspace-logout', 'workspace-owner'])('blendet Werte bei %s sofort aus und verwirft verspätete Antworten', async event => {
    const pending = deferred(); const api = service({ say: vi.fn().mockReturnValue(pending.promise) }); render(view(api, { onApply: vi.fn() }));
    fireEvent.click(await screen.findByRole('button', { name: 'Einlesen' }));
    fireEvent.change(await screen.findByLabelText('Nachricht an Claude'), { target: { value: 'Bitte korrigieren' } });
    fireEvent.click(screen.getByRole('button', { name: 'Senden' }));
    act(() => window.dispatchEvent(new Event(event)));
    expect(screen.queryByText('Alter Lieferant')).toBeNull();
    await act(async () => pending.resolve(reading({ values: { supplier: { value: 'Verspäteter Lieferant' } } })));
    expect(screen.queryByText('Verspäteter Lieferant')).toBeNull();
    expect(screen.queryByRole('button', { name: 'In die Maske übernehmen' })).toBeNull();
    expect(screen.getByRole('alert')).toHaveTextContent(/Sitzung.*geändert/);
  });
});

describe('Zulässiger Leser und bestätigte Übermittlung', () => {
  it.each([
    options({ ai_enabled: false }),
    options({ surfaces: [{ ...surface, ai_allowed: false }] }),
  ])('wählt bei ausgeschalteter KI trotz verbundenem externem Default lokale Regeln', async found => {
    const api = service({ options: vi.fn().mockResolvedValue(found) }); render(view(api));
    expect(await screen.findByRole('radio', { name: /Claude/ })).toBeDisabled();
    expect(screen.getByRole('radio', { name: 'Lokale Regeln' })).toBeChecked();
    fireEvent.click(screen.getByRole('button', { name: 'Einlesen' }));
    await waitFor(() => expect(api.start).toHaveBeenCalledWith(expect.objectContaining({ reader: 'local' })));
    expect(preferredReader(found)).toBe('local');
  });

  it('startet eine bildpflichtige Stelle bei ausgeschalteter KI nicht mit einem unzulässigen Leser', async () => {
    const api = service({ options: vi.fn().mockResolvedValue(options({ ai_enabled: false, surfaces: [{ ...surface, needs_ai: true, ai_allowed: false }] })) }); render(view(api));
    expect(await screen.findByRole('radio', { name: /Claude/ })).toBeDisabled();
    expect(screen.getByRole('radio', { name: 'Lokale Regeln' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Einlesen' })).toBeDisabled();
    expect(api.start).not.toHaveBeenCalled();
  });

  it('startet auch lokale Regeln nicht automatisch ohne die erforderliche Rollenfreigabe', async () => {
    const api = service({ options: vi.fn().mockResolvedValue(options({ default_reader: 'local', surfaces: [{ ...surface, may_use: false }] })) });
    render(view(api, { autoStart: true }));
    expect(await screen.findByRole('button', { name: 'Einlesen' })).toBeDisabled();
    expect(api.start).not.toHaveBeenCalled();
  });

  it('gleicht einen verlorenen Start mit derselben Kennung ab und sperrt zwischenzeitliche Änderungen', async () => {
    const api = service({ start: vi.fn().mockRejectedValueOnce(new Error('Bestätigung verloren')).mockResolvedValueOnce(reading()) }); render(view(api));
    fireEvent.click(await screen.findByRole('button', { name: 'Einlesen' }));
    await screen.findByText(/Bestätigung verloren/);
    const first = api.start.mock.calls[0][0];
    expect(first.idempotency_key).toEqual(expect.any(String));
    expect(screen.getByRole('radio', { name: 'Lokale Regeln' })).toBeDisabled();
    fireEvent.click(screen.getByRole('button', { name: 'Einlesen abgleichen' }));
    await screen.findByText('Alter Lieferant');
    expect(api.start.mock.calls[1][0]).toEqual(first);
  });

  it('bietet nach fehlgeschlagenem Laden einen gezielten erneuten Versuch an', async () => {
    const api = service({ options: vi.fn().mockRejectedValueOnce(new Error('Einstellungen nicht erreichbar')).mockResolvedValueOnce(options()) }); render(view(api));
    await screen.findByText('Einstellungen nicht erreichbar');
    fireEvent.click(screen.getByRole('button', { name: 'Einleseeinstellungen erneut laden' }));
    expect(await screen.findByRole('button', { name: 'Einlesen' })).toBeEnabled();
    expect(api.options).toHaveBeenCalledTimes(2);
  });

  it('gleicht eine verlorene Entscheidung mit derselben ursprünglichen Revision und Kennung ab', async () => {
    const duplicate = { kind: 'invoice', id: 'i1', href: '/invoice-review/i1', title: 'Vorhandene Rechnung' };
    const api = service({ start: vi.fn().mockResolvedValue(reading({ duplicates: [duplicate] })),
      decide: vi.fn().mockRejectedValueOnce(new Error('Entscheidungsbestätigung verloren')).mockResolvedValueOnce(reading({ revision: 2 })) });
    const onOpenExisting = vi.fn(); render(view(api, { onOpenExisting }));
    fireEvent.click(await screen.findByRole('button', { name: 'Einlesen' }));
    fireEvent.click(await screen.findByRole('button', { name: 'Öffnen' }));
    await screen.findByText('Entscheidungsbestätigung verloren');
    expect(onOpenExisting).not.toHaveBeenCalled();
    expect(screen.getByRole('button', { name: 'Trotzdem neu anlegen' })).toBeDisabled();
    fireEvent.click(screen.getByRole('button', { name: 'Übermittlung abgleichen' }));
    await waitFor(() => expect(onOpenExisting).toHaveBeenCalledTimes(1));
    expect(api.decide.mock.calls[1]).toEqual(api.decide.mock.calls[0]);
    expect(api.decide.mock.calls[0][3]).toEqual(expect.any(String));
  });

  it('gleicht einen verlorenen Abschluss ab, bevor das Fachformular fortgesetzt wird', async () => {
    const api = service({ finish: vi.fn().mockRejectedValueOnce(new Error('Abschlussbestätigung verloren')).mockResolvedValueOnce(reading({ status: 'cancelled' })) });
    const onSkip = vi.fn(); render(view(api, { onSkip }));
    fireEvent.click(await screen.findByRole('button', { name: 'Einlesen' }));
    fireEvent.click(await screen.findByRole('button', { name: 'Ohne die Werte weiter' }));
    await screen.findByText('Abschlussbestätigung verloren'); expect(onSkip).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: 'Übermittlung abgleichen' }));
    await waitFor(() => expect(onSkip).toHaveBeenCalledTimes(1));
    expect(api.finish.mock.calls[1]).toEqual(api.finish.mock.calls[0]);
    expect(api.finish.mock.calls[0][3]).toEqual(expect.any(String));
  });
});
