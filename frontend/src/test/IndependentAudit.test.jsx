import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import InvoiceReview from '../pages/InvoiceReview';
import AiReadingPanel from '../features/aiReading/AiReadingPanel';
import { api } from '../api';

vi.mock('../api', () => ({ api: { get: vi.fn(), list: vi.fn(), post: vi.fn(), put: vi.fn(), patch: vi.fn(), del: vi.fn(), upload: vi.fn() } }));
vi.mock('../i18n', () => ({ useTranslation: () => ({ t: key => key, locale: 'de-DE' }) }));
vi.mock('../contexts/AuthContext', () => ({ useCanWrite: () => true, useAuth: () => null }));

let reading;
let options;
beforeEach(() => {
  vi.clearAllMocks();
  reading = { id: 'audit-read', revision: 1, surface: 'invoice', reader: 'local', reader_label: 'Lokale Regeln', status: 'open',
    chat: false, changed: [], duplicates: [], decision: null, questions: [], notes: [], dropped: [], messages: [], confirm_mode: 'confirm',
    file: { name: 'beleg.pdf' }, values: Object.fromEntries(Object.entries({supplier: 'Audit Stadtwerke', invoice_number: 'AUD-2026',
      invoice_date: '2026-03-04', net_amount: '1000.00', vat_rate: '19', gross_amount: '1190.00', due_date: '2026-03-31',
      performance_start: '2025-01-01', performance_end: '2025-12-31', iban: 'DE89370400440532013000', document_kind: 'credit_note'})
      .map(([name, value]) => [name, { value, confidence: 'high', evidence: value, source: 'local' }])) };
  options = {readers: [{id:'local',label:'Lokale Regeln',available:true,ai:false},{id:'claude',label:'Claude',available:true,ai:true}],
    default_reader: 'local', ai_enabled: true, chat: true, surfaces: [{id:'invoice',label:'Rechnungseingang',may_use:true,ai_allowed:true,needs_ai:false,fields:[]}]};
  api.list.mockImplementation(path => Promise.resolve(path === '/invoices'
    ? [{id:'original',supplier:'Audit Stadtwerke',invoice_number:'ORIG-2026',invoice_date:'2026-02-01',gross_amount:1190}]
    : [{id:'p1',name:'Audit Haus'}]));
  api.get.mockImplementation(path => {
    if (path.startsWith('/invoice-review/inbox')) return Promise.resolve({items:[],total:0,skip:0,limit:50,has_more:false});
    if (path.startsWith('/invoice-review/duplicates')) return Promise.resolve({duplicates:[]});
    if (path.startsWith('/ai/readings/options')) return Promise.resolve(options);
    if (path.startsWith('/auth/users/me/settings/draft-defaults')) return Promise.resolve({values:{}});
    return Promise.reject(new Error(`unexpected ${path}`));
  });
  api.upload.mockResolvedValue({file_url:'/uploads/documents/beleg.pdf'});
  api.post.mockImplementation(path => Promise.resolve(path === '/ai/readings' ? reading : path === '/documents' ? {id:'audit-doc'} :
    path === '/invoice-review/receipts' ? {invoice:{id:'audit-invoice'}} : {}));
});
afterEach(cleanup);

async function readAndSave() {
  render(<MemoryRouter><InvoiceReview /></MemoryRouter>);
  fireEvent.click(await screen.findByRole('button', {name:'Rechnung erfassen'}));
  const dialog = await screen.findByRole('dialog', {name:'Rechnung erfassen'});
  fireEvent.change(within(dialog).getByLabelText('Beleg'), {target:{files:[new File(['%PDF-1.4'],'beleg.pdf',{type:'application/pdf'})]}});
  fireEvent.click(within(dialog).getByRole('button', {name:/Beleg einlesen/}));
  fireEvent.click(await within(dialog).findByRole('button', {name:'In die Rechnung übernehmen'}));
  fireEvent.click(within(dialog).getByRole('button', {name:'Alle bestätigen'}));
  if (reading.values.document_kind.value === 'credit_note') {
    await within(dialog).findByRole('option', {name:/ORIG-2026/});
    fireEvent.change(within(dialog).getByLabelText('Mindert Rechnung'), {target:{value:'original'}});
  }
  fireEvent.click(within(dialog).getByRole('button', {name:'Speichern'}));
  await waitFor(() => expect(api.post).toHaveBeenCalledWith('/invoice-review/receipts', expect.anything()));
  return api.post.mock.calls.find(([path]) => path === '/invoice-review/receipts')[1];
}

it('must not silently submit a recognised credit note as an invoice', async () => {
  const saved = await readAndSave();
  expect(saved.kind).toBe('credit_note');
  expect(saved.credit_for_invoice_id).toBe('original');
});

it('must carry the explicitly recognised due date into the saved invoice', async () => {
  reading.values.document_kind.value = 'invoice';
  const saved = await readAndSave();
  expect(saved.invoice.due_date).toBe('2026-03-31');
  expect(saved.invoice.performance_start).toBe('2025-01-01');
  expect(saved.invoice.performance_end).toBe('2025-12-31');
  expect(saved.invoice.notes).toContain('DE89370400440532013000');
});

it('must recover a lost chat response with the same command instead of a fresh conflicting command', async () => {
  options.default_reader = 'claude';
  reading.reader = 'claude'; reading.reader_label = 'Claude'; reading.chat = true;
  let committed = null;
  api.post.mockImplementation((path, body) => {
    if (path === '/ai/readings') return Promise.resolve(reading);
    if (path.endsWith('/messages')) {
      if (!committed) { committed = body; return Promise.reject(new Error('Reply lost after server commit')); }
      if (body.idempotency_key !== committed.idempotency_key) return Promise.reject(new Error('409 revision conflict'));
      return Promise.resolve({...reading,revision:2,messages:[{id:'m2',role:'assistant',text:'Gespeicherte Antwort'}]});
    }
    return Promise.resolve({});
  });
  render(<MemoryRouter><AiReadingPanel surface="invoice" source={{fileUrl:'/uploads/documents/beleg.pdf'}} /></MemoryRouter>);
  fireEvent.click(await screen.findByRole('button', {name:'Einlesen'}));
  const text = await screen.findByLabelText('Nachricht an Claude');
  fireEvent.change(text, {target:{value:'Bitte das Datum korrigieren'}});
  fireEvent.click(screen.getByRole('button',{name:'Senden'}));
  await screen.findByText('Reply lost after server commit');
  fireEvent.click(screen.getByRole('button',{name:'Senden'}));
  await waitFor(() => expect(api.post.mock.calls.filter(([path]) => path.endsWith('/messages'))).toHaveLength(2));
  const calls = api.post.mock.calls.filter(([path]) => path.endsWith('/messages'));
  expect(calls[1][1].idempotency_key).toBe(calls[0][1].idempotency_key);
});

it('loads the current revision after a real API conflict and retries the reviewed message', async () => {
  options.default_reader = 'claude';
  reading.reader = 'claude'; reading.reader_label = 'Claude'; reading.chat = true;
  const originalGet = api.get.getMockImplementation();
  api.get.mockImplementation(path => path === '/ai/readings/audit-read'
    ? Promise.resolve({...reading, revision: 2}) : originalGet(path));
  let messages = 0;
  api.post.mockImplementation(path => {
    if (path === '/ai/readings') return Promise.resolve(reading);
    if (path.endsWith('/messages') && ++messages === 1) {
      return Promise.reject(Object.assign(new Error('Revision conflict'), {statusCode:409}));
    }
    return Promise.resolve({...reading, revision:3});
  });
  render(<MemoryRouter><AiReadingPanel surface="invoice" source={{fileUrl:'/uploads/documents/beleg.pdf'}} /></MemoryRouter>);
  fireEvent.click(await screen.findByRole('button', {name:'Einlesen'}));
  const text = await screen.findByLabelText('Nachricht an Claude');
  fireEvent.change(text, {target:{value:'Bitte prüfen'}});
  fireEvent.click(screen.getByRole('button',{name:'Senden'}));
  await screen.findByText(/Der aktuelle Stand ist geladen/);
  expect(text.value).toBe('Bitte prüfen');
  fireEvent.click(screen.getByRole('button',{name:'Senden'}));
  await waitFor(() => expect(messages).toBe(2));
  const calls = api.post.mock.calls.filter(([path]) => path.endsWith('/messages'));
  expect(calls[1][1].expected_revision).toBe(2);
  expect(calls[1][1].idempotency_key).not.toBe(calls[0][1].idempotency_key);
});
