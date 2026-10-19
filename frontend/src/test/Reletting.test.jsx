import { afterEach, describe, expect, it, vi } from 'vitest';
import { act, cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';
import { api } from '../api';
import Reletting from '../pages/Reletting';
import RelettingProject from '../pages/RelettingProject';
import { takeNewEntry } from '../utils/newEntry';
import { readAssistantDraft } from '../features/assistant/assistantDrafts';

vi.mock('../api', () => ({ api: { get: vi.fn(), post: vi.fn(), put: vi.fn(), del: vi.fn(), upload: vi.fn(), getBlob: vi.fn() } }));
const toast = { error: vi.fn(), success: vi.fn() };
vi.mock('../components/Toast', () => ({ useToast: () => toast }));
const confirm = vi.fn(() => Promise.resolve(true));
vi.mock('../components/ConfirmDialog', () => ({ useConfirm: () => confirm }));
vi.mock('../contexts/AuthContext', () => ({ useCanWrite: () => true, useAuth: () => ({ user: { id: 'u1' } }) }));
vi.mock('../components/PdfPreview', () => ({ default: ({ title }) => <div>PDF {title}</div> }));
// the form itself is tested on its own; here only what the page gives it and does with the result
vi.mock('../components/FormModal', () => ({ default: ({ title, onSave, onClose, initial }) => <div role="dialog" aria-label={title}>
  <button onClick={async () => { await onSave({ ...(initial || {}), full_name: 'Clara Neu', status: 'new' }); onClose(); }}>Speichern</button></div> }));

afterEach(() => { cleanup(); vi.clearAllMocks(); localStorage.clear(); });

function Where() { const location = useLocation(); return <output aria-label="Adresse">{location.pathname}</output>; }

const OVERVIEW = {
  totals: { open: 1, vacant_without_project: 1, applicants: 2, purge_due: 1 },
  projects: [{ id: 'p1', status: 'open', unit_id: 'u1', unit_label: 'WE 3', property_id: 'h1', property_name: 'Bautzner Straße',
    available_from: '2026-12-01', warm_rent: 1000, applicants: 2, purge_due: 1, next_viewing: null, accepted: null, href: '/reletting/p1',
    next_step: { key: 'contract', label: 'Mietvertrag', detail: 'Vertrag MV-7 angelegt: Projekt damit abschließen' } }],
  vacancies: [{ unit_id: 'u2', unit_label: 'WE 5', unit_type: 'Wohnung', property_id: 'h1', property_name: 'Bautzner Straße',
    area_sqm: 48, rooms: 2, cold_rent: 420, vacant_since: '2026-09-30', free_from: null, href: '/units/u2' }],
};

const criteria = states => ['income', 'persons', 'move_in', 'pets', 'documents', 'viewing'].map((key, index) => ({
  key, label: { income: 'Einkommen mindestens 3,0-fache Warmmiete', persons: 'Haushaltsgröße passt', move_in: 'Einzug zum Bezugstermin (± 1 Monat)',
    pets: 'Haustiere passen zur Vorgabe', documents: 'Unterlagen vollständig', viewing: 'Besichtigung wahrgenommen' }[key],
  state: states[index], detail: `Detail ${key}` }));
const applicant = (id, name, status, states, extra = {}) => ({
  id, full_name: name, status, household_size: 2, net_income: 3200, rent_share: 31.2, move_in_date: '2026-12-01', employment: 'permanent',
  rating: null, viewing_rating: null, criteria: criteria(states), met: states.filter(s => s === 'met').length,
  not_met: states.filter(s => s === 'not_met').length, attachments: [], viewings: [], deletable: ['rejected', 'withdrawn'].includes(status),
  days_since_decision: status === 'rejected' ? 120 : null, purge_due: status === 'rejected', doc_income: true, ...extra,
});
const PROJECT = {
  project: { id: 'p1', status: 'open', unit_id: 'u1', headline: 'Helle 2-Zimmer-Wohnung', target_rent: 800, service_charge: 150,
    heating_charge: 50, deposit_amount: 2400, income_factor: 3, available_from: '2026-12-01', deleted_applicants: 0, tenant_id: null,
    updated_at: '2026-10-19T10:00:00' },
  warm_rent: 1000,
  unit: { id: 'u1', label: 'WE 3', href: '/units/u1', area_sqm: 60.5, rooms: 2, floor: '2. OG' },
  property: { id: 'h1', name: 'Bautzner Straße', address: 'Bautzner Straße 61, 01099 Dresden', href: '/properties/h1' },
  steps: [{ key: 'offer', label: 'Angebot festlegen', done: true, detail: 'Miete' }, { key: 'expose', label: 'Exposé und Portaltext', done: false, detail: 'Es fehlt: Art des Energieausweises' }],
  missing_for_ad: ['Art des Energieausweises'],
  next_step: { key: 'expose', label: 'Exposé und Portaltext', detail: 'Es fehlt: Art des Energieausweises' },
  applicants: [
    applicant('a', 'Anna Bergmann', 'viewing_scheduled', ['met', 'met', 'met', 'met', 'met', 'open']),
    applicant('b', 'Bernd Krause', 'new', ['not_met', 'not_met', 'met', 'open', 'open', 'open']),
    applicant('c', 'Carla Alt', 'rejected', ['open', 'open', 'open', 'open', 'open', 'open'],
      { attachments: [{ id: 'f1', title: 'Selbstauskunft', kind: 'document', size: 2048, created_at: '2026-06-01', file_url: '/uploads/applicants/c/x.pdf' }] }),
  ],
  viewings: [], listing: null, tenant: null, contracts: [], purge_due: 1, retention_days: 90,
};

function renderProject(entry = '/reletting/p1') {
  api.get.mockImplementation(path => Promise.resolve(path.endsWith('/portal-text')
    ? { blocks: [{ key: 'facts', label: 'Eckdaten und Kosten', text: 'Warmmiete: 1.000,00 €' }], missing: ['Art des Energieausweises'] }
    : path.endsWith('/ai-question') ? { question: 'Bitte vergleiche … Bewerbung A:', applicants: 2 } : PROJECT));
  return render(<MemoryRouter initialEntries={[entry]}>
    <Routes><Route path="/reletting/:id" element={<><RelettingProject /><Where /></>} />
      <Route path="*" element={<Where />} /></Routes></MemoryRouter>);
}

describe('Reletting hub', () => {
  it('lists the projects and starts one for a vacant unit', async () => {
    api.get.mockResolvedValue(OVERVIEW);
    api.post.mockResolvedValue({ project: { id: 'p9' }, adopted: 2 });
    render(<MemoryRouter initialEntries={['/reletting']}><Routes>
      <Route path="/reletting" element={<Reletting />} /><Route path="*" element={<Where />} /></Routes></MemoryRouter>);
    expect(await screen.findByRole('link', { name: 'WE 3' })).toHaveAttribute('href', '/reletting/p1');
    expect(screen.getByText('Laufende Projekte').closest('.stat-card')).toHaveTextContent('1');
    expect(screen.getByText('seit 30.09.2026')).toBeInTheDocument();
    // what is left to do, linked to the tab where it is done
    expect(screen.getByRole('link', { name: 'Mietvertrag' })).toHaveAttribute('href', '/reletting/p1?tab=closing');
    expect(screen.getByText('Vertrag MV-7 angelegt: Projekt damit abschließen')).toBeInTheDocument();
    await act(async () => { fireEvent.click(screen.getByRole('button', { name: 'Neuvermietung starten' })); });
    expect(api.post).toHaveBeenCalledWith('/reletting', { unit_id: 'u2' });
    expect(toast.success).toHaveBeenCalledWith('2 bereits erfasste Anfragen gehören jetzt zum Projekt.');
    expect(screen.getByRole('status', { name: 'Adresse' })).toHaveTextContent('/reletting/p9');
  });
});

describe('Reletting project', () => {
  it('shows the steps, compares the open applicants and hands a pseudonymised question to the assistant', async () => {
    renderProject();
    expect(await screen.findByRole('heading', { name: 'Helle 2-Zimmer-Wohnung' })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'WE 3' })).toHaveAttribute('href', '/units/u1');
    expect(screen.getByText('Ablauf · 1 von 2 erledigt')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('tab', { name: 'Vergleich' }));
    const table = screen.getByRole('table', { name: 'Vergleich der Bewerbungen' });
    const header = within(table).getAllByRole('columnheader').map(cell => cell.textContent);
    expect(header.join(' ')).toContain('Anna Bergmann');
    expect(header.join(' ')).not.toContain('Carla Alt');                // declined applicants are not compared
    expect(within(table).getByRole('row', { name: /Kriterien erfüllt/ })).toHaveTextContent('5 von 6');
    await act(async () => { fireEvent.click(screen.getByRole('button', { name: 'KI-Vergleich vorbereiten' })); });
    expect(api.get).toHaveBeenCalledWith('/reletting/p1/ai-question');
    expect(readAssistantDraft('u1', 'new')).toMatchObject({ body: 'Bitte vergleiche … Bewerbung A:', data_scope: 'none' });
    expect(screen.getByRole('status', { name: 'Adresse' })).toHaveTextContent('/assistant');
  });

  it('names the next step and opens the tab a link asks for', async () => {
    renderProject();
    await screen.findByRole('heading', { name: 'Helle 2-Zimmer-Wohnung' });
    expect(screen.getByText(/Als Nächstes:/)).toHaveTextContent('Es fehlt: Art des Energieausweises');
    fireEvent.click(within(screen.getByText(/Als Nächstes:/)).getByRole('button', { name: 'Exposé und Portaltext' }));
    expect(screen.getByRole('tab', { name: 'Exposé & Portale' })).toHaveAttribute('aria-selected', 'true');
    cleanup();
    renderProject('/reletting/p1?tab=closing');
    await screen.findByRole('heading', { name: 'Helle 2-Zimmer-Wohnung' });
    expect(screen.getByRole('tab', { name: 'Abschluss & Datenschutz' })).toHaveAttribute('aria-selected', 'true');
  });

  it('takes the chosen applicant over and opens the prefilled contract form', async () => {
    renderProject();
    await screen.findByRole('heading', { name: 'Helle 2-Zimmer-Wohnung' });
    const accepted = { ...PROJECT, project: { ...PROJECT.project, tenant_id: 't7' }, tenant: { id: 't7', full_name: 'Anna Bergmann', href: '/tenants/t7/account' },
      applicants: PROJECT.applicants.map(row => (row.id === 'a' ? { ...row, status: 'accepted' } : row)), rent_applied: true,
      contract_prefill: { unit_id: 'u1' } };
    api.post.mockResolvedValue(accepted);
    fireEvent.click(screen.getByRole('tab', { name: 'Vergleich' }));
    await act(async () => { fireEvent.click(screen.getAllByRole('button', { name: 'Als Mieter übernehmen' })[0]); });
    expect(api.post).toHaveBeenCalledWith('/reletting/p1/accept', { lead_id: 'a', apply_rent: true });
    expect(screen.getByRole('tab', { name: 'Abschluss & Datenschutz' })).toHaveAttribute('aria-selected', 'true');
    expect(screen.getByRole('link', { name: 'Anna Bergmann' })).toHaveAttribute('href', '/tenants/t7/account');
    fireEvent.click(screen.getByRole('button', { name: 'Mietvertrag anlegen' }));
    expect(screen.getByRole('status', { name: 'Adresse' })).toHaveTextContent('/contracts');
    expect(takeNewEntry('/contracts')).toEqual({ prefill: { property_id: 'h1', unit_id: 'u1', tenant_id: 't7', status: 'active',
      start_date: '2026-12-01', deposit_amount: 2400, persons: 2 } });
  });

  it('deletes declined applicants only after confirmation', async () => {
    renderProject();
    await screen.findByRole('heading', { name: 'Helle 2-Zimmer-Wohnung' });
    fireEvent.click(screen.getByRole('tab', { name: 'Abschluss & Datenschutz' }));
    const privacy = screen.getByRole('region', { name: 'Datenschutz: Bewerberdaten löschen' });
    expect(within(privacy).getByText('Löschung empfohlen')).toBeInTheDocument();
    expect(within(privacy).queryByText(/Anna Bergmann/)).toBeNull();          // still in the running
    const remove = within(privacy).getByRole('button', { name: 'Ausgewählte endgültig löschen' });
    expect(remove).toBeDisabled();
    fireEvent.click(within(privacy).getByRole('checkbox'));
    api.post.mockResolvedValue({ ...PROJECT, applicants: PROJECT.applicants.slice(0, 2), deleted: 1, deleted_files: 1,
      project: { ...PROJECT.project, deleted_applicants: 1 } });
    await act(async () => { fireEvent.click(remove); });
    expect(confirm).toHaveBeenCalledWith(expect.stringContaining('Carla Alt'), { action: 'delete' });
    expect(api.post).toHaveBeenCalledWith('/reletting/p1/purge', { lead_ids: ['c'], confirmed: true });
    expect(toast.success).toHaveBeenCalledWith('1 Bewerbung(en) gelöscht, 1 Datei(en) entfernt.');
    expect(screen.getByText('Bisher gelöscht: 1 Bewerbung(en).')).toBeInTheDocument();
  });

  it('records an applicant and shows the portal texts with what an advertisement still lacks', async () => {
    renderProject();
    await screen.findByRole('heading', { name: 'Helle 2-Zimmer-Wohnung' });
    fireEvent.click(screen.getByRole('tab', { name: /Interessenten/ }));
    api.post.mockResolvedValue(PROJECT);
    fireEvent.click(screen.getByRole('button', { name: /Bewerbung erfassen/ }));
    await act(async () => { fireEvent.click(within(screen.getByRole('dialog', { name: 'Bewerbung erfassen' })).getByRole('button', { name: 'Speichern' })); });
    expect(api.post).toHaveBeenCalledWith('/reletting/p1/applicants', expect.objectContaining({ full_name: 'Clara Neu', doc_income: false, rating: null }));
    fireEvent.click(screen.getByRole('tab', { name: 'Exposé & Portale' }));
    expect(await screen.findByText('Warmmiete: 1.000,00 €')).toBeInTheDocument();
    expect(screen.getByRole('note')).toHaveTextContent('Art des Energieausweises');
    api.getBlob.mockResolvedValue(new Blob(['%PDF-1.4'], { type: 'application/pdf' }));
    URL.createObjectURL = vi.fn(() => 'blob:expose');
    URL.revokeObjectURL = vi.fn();
    await act(async () => { fireEvent.click(screen.getByRole('button', { name: 'Exposé als PDF ansehen' })); });
    expect(api.getBlob).toHaveBeenCalledWith('/reletting/p1/expose');
    expect(screen.getByText('PDF Exposé')).toBeInTheDocument();
  });
});
