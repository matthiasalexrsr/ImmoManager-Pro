import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter, useLocation, useNavigate } from 'react-router-dom';
import Meters from '../pages/Meters';
import Listings from '../pages/Listings';
import MeterHistory from '../features/meters/MeterHistory';
import { api } from '../api';
import { prepareUploadAccess } from '../utils/uploadAccess';

const context = vi.hoisted(() => ({ actor: 'reader', lookups: {
  units: [{ id: 'u1', label: 'EG', property_id: 'p1' }], properties: [{ id: 'p1', name: 'Haus' }],
} }));
vi.mock('../api', () => ({ api: { get: vi.fn(), list: vi.fn(), post: vi.fn(), put: vi.fn(), del: vi.fn(), captureSession: vi.fn() } }));
vi.mock('../i18n', () => ({ useTranslation: () => ({ t: () => undefined, locale: 'de-DE' }) }));
vi.mock('../contexts/AuthContext', () => ({ useAuth: () => ({ user: { id: context.actor } }), useCanWrite: () => false }));
vi.mock('../contexts/DataStoreContext', () => ({ useEntities: key => ({ items: context.lookups[key] || [], loading: false }), useDataStore: () => null }));
vi.mock('../components/ConfirmDialog', () => ({ useConfirm: () => async () => true }));
vi.mock('../utils/uploadAccess', () => ({ prepareUploadAccess: vi.fn() }));
vi.mock('../components/DataTable', () => ({ default: ({ data }) => <div data-testid="list">{data.map(row => <span key={row.id}>{row.title || row.serial_number}</span>)}</div> }));
vi.mock('../features/channels/MarketingPanel', () => ({ default: () => null }));
vi.mock('../features/channels/ChannelPanel', () => ({ default: () => null }));

const meter = { id: 'm1', serial_number: 'Zähler 1', unit_id: 'u1', meter_type: 'cold_water', measure_unit: 'm³' };
const r1 = { id: 'r1', reading_date: '2026-10-01', value: 123.4, notes: 'Oktoberablesung', recorded_by: 'Hausverwaltung' };
const r2 = { id: 'r2', reading_date: '2026-11-01', value: 140.8, notes: 'Novemberablesung' };
const history = { meter, readings: [r1, r2], years: [], contracts: [] };
const listing = { id: 'l1', title: 'Stuttgart EG', unit_id: 'u1' };
const photo = { id: 'ph1', listing_id: 'l1', title: 'Wohnzimmer', file_url: '/uploads/listing-photos/one.jpg' };
const photo2 = { id: 'ph2', listing_id: 'l1', title: 'Küche', file_url: '/uploads/listing-photos/two.jpg' };
function noticeSource(kind, record, href) { return { notice: { revision: 'notice-v1' }, source: { kind, entity_id: record.id, revision: 'source-v1', values: record, href } }; }
function Controls({ second }) {
  const location = useLocation(), navigate = useNavigate();
  return <><output data-testid="url">{location.pathname}{location.search}</output>
    <button onClick={() => navigate(second)}>Anderes Ziel</button><button onClick={() => navigate(-1)}>Zurück</button><button onClick={() => navigate(1)}>Vorwärts</button></>;
}
function show(Component, url, second = '/meters') {
  return render(<MemoryRouter initialEntries={[url]}><Controls second={second} /><Component /></MemoryRouter>);
}
function deferred() { let resolve; const promise = new Promise(yes => { resolve = yes; }); return { promise, resolve }; }

beforeEach(() => {
  vi.resetAllMocks(); context.actor = 'reader'; sessionStorage.clear();
  api.captureSession.mockImplementation(() => () => {});
  prepareUploadAccess.mockResolvedValue(undefined);
  api.list.mockImplementation(path => Promise.resolve(path === '/meters' ? [meter] : path === '/listings' ? [listing] : []));
  api.post.mockResolvedValue({});
  api.get.mockImplementation(path => {
    if (path === '/meters/m1/history') return Promise.resolve(history);
    if (path === '/listings/photos/ph1') return Promise.resolve(photo);
    if (path === '/listings/photos/ph2') return Promise.resolve(photo2);
    if (path === '/listings/l1') return Promise.resolve(listing);
    if (path === '/notifications/n1/source') return Promise.resolve(noticeSource('standalone_reading', r1, '/meters?focus_id=m1&source_id=r1'));
    return Promise.reject(new Error(`Unexpected request ${path}`));
  });
});
afterEach(cleanup);

describe('meter child-source navigation', () => {
  it('contains a synchronous capture failure on history refresh and removes its old reading and listeners', async () => {
    const add=vi.spyOn(window,'addEventListener'),remove=vi.spyOn(window,'removeEventListener');
    const content=revision=><MemoryRouter><MeterHistory meterId="m1" meterLabel="Zähler 1" focusedReadingId="r1" revision={revision} canWrite={false} onClose={()=>{}} /></MemoryRouter>;
    const view=render(content(0));
    try {
      await screen.findByRole('region',{name:'Verlinkte Ablesung'});
      api.captureSession.mockImplementationOnce(()=>{
        window.dispatchEvent(new Event('workspace-logout'));
        throw Object.assign(new Error('Die Sitzung wurde geändert. Bitte erneut anmelden.'),{code:'SESSION_CHANGED'});
      });
      expect(()=>view.rerender(content(1))).not.toThrow();
      expect(await screen.findByRole('alert')).toHaveTextContent('Die Sitzung wurde geändert');
      expect(screen.queryByRole('region',{name:'Verlinkte Ablesung'})).not.toBeInTheDocument();
      expect(screen.queryByText(r1.notes)).not.toBeInTheDocument();
      expect(api.get.mock.calls.map(([path])=>path)).toEqual(['/meters/m1/history']);
      expect(api.post).not.toHaveBeenCalled();
      view.unmount();
      for(const [name,handler] of add.mock.calls.filter(([name])=>['workspace-owner','workspace-logout'].includes(name))) {
        expect(remove).toHaveBeenCalledWith(name,handler);
      }
    } finally {view.unmount();add.mockRestore();remove.mockRestore();}
  });
  it('opens the exact reading from a favorite without a notice and never sends a receipt', async () => {
    show(Meters, '/meters?focus_id=m1&source_id=r1');
    const details = await screen.findByRole('region', { name: 'Verlinkte Ablesung' });
    expect(details).toHaveTextContent('Oktoberablesung');
    expect(details).toHaveTextContent('123,4 m³');
    expect(details).toHaveFocus();
    expect(screen.getByRole('row', { current: true })).toHaveTextContent('Oktoberablesung');
    expect(api.post).not.toHaveBeenCalled();
    expect(screen.queryByRole('button', {name:'Zähler bearbeiten'})).not.toBeInTheDocument();
  });
  it('keeps the authoritative history usable if the list failed or did not contain the parent', async () => {
    api.list.mockRejectedValue(new Error('Liste offline'));
    show(Meters, '/meters?focus_id=m1&source_id=r1');
    expect(await screen.findByRole('region', { name: 'Verlinkte Ablesung' })).toHaveTextContent('Oktoberablesung');
    expect(screen.getByText('Liste offline')).toBeInTheDocument();
    expect(api.post).not.toHaveBeenCalled();
  });
  it.each(['missing', 'foreign-meter-reading'])('rejects %s child IDs without fetching a foreign source', async id => {
    show(Meters, `/meters?focus_id=m1&source_id=${id}&notice_id=n1`);
    expect(await screen.findByRole('alert')).toHaveTextContent('für diesen Zähler nicht verfügbar');
    expect(screen.queryByRole('region', { name: 'Verlinkte Ablesung' })).not.toBeInTheDocument();
    expect(api.get.mock.calls.map(([path]) => path)).toEqual(['/meters/m1/history']);
    expect(api.post).not.toHaveBeenCalled();
  });
  it('sends a notice receipt only for the reading in the verified parent history', async () => {
    show(Meters, '/meters?focus_id=m1&source_id=r1&notice_id=n1');
    await screen.findByRole('region', { name: 'Verlinkte Ablesung' });
    await waitFor(() => expect(api.post).toHaveBeenCalledWith('/notifications/n1/receipt', expect.objectContaining({ source_id: 'r1', source_kind: 'standalone_reading', action: 'landed' })));
    expect(api.post).toHaveBeenCalledTimes(1);
  });
  it('restores the selected child on Back/Forward and closes URL-owned history without reopening it', async () => {
    show(Meters, '/meters?focus_id=m1&source_id=r1&status=active', '/meters?focus_id=m1&source_id=r2&status=active');
    await screen.findByRole('region', { name: 'Verlinkte Ablesung' });
    fireEvent.click(screen.getByRole('button', {name:'Anderes Ziel'}));
    expect(screen.getByRole('region', { name: 'Verlinkte Ablesung' })).toHaveTextContent('Novemberablesung');
    fireEvent.click(screen.getByRole('button', {name:'Zurück'}));
    expect(screen.getByRole('region', { name: 'Verlinkte Ablesung' })).toHaveTextContent('Oktoberablesung');
    fireEvent.click(screen.getByRole('button', {name:'Vorwärts'}));
    fireEvent.click(screen.getByRole('button', {name:'Schließen',exact:true}));
    expect(screen.getByTestId('url')).toHaveTextContent('/meters?status=active');
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(api.post).not.toHaveBeenCalled();
  });
  it('does not acknowledge a missing or mismatched parent history', async () => {
    api.get.mockResolvedValue({ ...history, meter: { ...meter, id: 'foreign' } });
    show(Meters, '/meters?focus_id=m1&source_id=r1&notice_id=n1');
    expect(await screen.findByRole('alert')).toHaveTextContent('nicht vollständig geladen');
    expect(screen.queryByRole('region', { name: 'Verlinkte Ablesung' })).not.toBeInTheDocument();
    expect(api.post).not.toHaveBeenCalled();
  });
  it.each([403,404])('does not disclose parent existence for HTTP %s', async statusCode => {
    api.get.mockRejectedValue(Object.assign(new Error('sensitive parent label'),{statusCode}));
    show(Meters, '/meters?focus_id=m1&source_id=r1&notice_id=n1');
    expect(await screen.findByRole('alert')).toHaveTextContent('Zählerverlauf ist nicht verfügbar');
    expect(screen.queryByText(/sensitive parent/)).not.toBeInTheDocument();
    expect(api.post).not.toHaveBeenCalled();
  });
  it.each([[null], [r1,r1], [{...r1,meter_id:'foreign'}]])('rejects malformed or ambiguous child rows %j', async readings => {
    api.get.mockResolvedValue({...history,readings});
    show(Meters, '/meters?focus_id=m1&source_id=r1&notice_id=n1');
    expect(await screen.findByRole('alert')).toHaveTextContent('nicht vollständig geladen');
    expect(screen.queryByRole('region',{name:'Verlinkte Ablesung'})).not.toBeInTheDocument();
    expect(api.post).not.toHaveBeenCalled();
  });
});

describe('listing child-source navigation', () => {
  it('contains synchronous session capture failure without fetching a new photo or retaining the previous one', async () => {
    const add=vi.spyOn(window,'addEventListener'),remove=vi.spyOn(window,'removeEventListener');
    const view=show(Listings,'/listings?focus_id=l1&source_id=ph1','/listings?focus_id=l1&source_id=ph2');
    try {
      await screen.findByRole('img',{name:'Wohnzimmer'});
      api.captureSession.mockImplementationOnce(()=>{
        window.dispatchEvent(new Event('workspace-logout'));
        throw Object.assign(new Error('Die Sitzung wurde geändert. Bitte erneut anmelden.'),{code:'SESSION_CHANGED'});
      });
      expect(()=>fireEvent.click(screen.getByRole('button',{name:'Anderes Ziel'}))).not.toThrow();
      expect(await screen.findByRole('alert')).toHaveTextContent('Die Sitzung wurde geändert');
      expect(screen.queryByRole('img')).not.toBeInTheDocument();
      expect(screen.queryByRole('region',{name:'Verlinktes Inseratfoto'})).not.toBeInTheDocument();
      expect(api.get.mock.calls.map(([path])=>path)).toEqual(['/listings/photos/ph1','/listings/l1']);
      expect(prepareUploadAccess).toHaveBeenCalledTimes(1);
      expect(api.post).not.toHaveBeenCalled();
      view.unmount();
      for(const [name,handler] of add.mock.calls.filter(([name])=>['workspace-owner','workspace-logout'].includes(name))) {
        expect(remove).toHaveBeenCalledWith(name,handler);
      }
    } finally {view.unmount();add.mockRestore();remove.mockRestore();}
  });
  it('opens a photo from history without notice_id using authoritative parent/child reads', async () => {
    api.list.mockResolvedValue([]);
    show(Listings, '/listings?focus_id=l1&source_id=ph1');
    const section = await screen.findByRole('region', {name:'Verlinktes Inseratfoto'});
    expect(section).toHaveTextContent('Stuttgart EG');
    const image = within(section).getByRole('img', { name: 'Wohnzimmer' });
    fireEvent.load(image);
    expect(api.get).toHaveBeenCalledWith('/listings/l1', expect.anything());
    expect(prepareUploadAccess).toHaveBeenCalledWith(expect.stringContaining('/uploads/listing-photos/one.jpg'), expect.anything());
    expect(api.post).not.toHaveBeenCalled();
  });
  it('uses the photo view even if the listing collection failed, and waits for image bytes before acknowledging', async () => {
    api.list.mockRejectedValue(new Error('Inseratliste offline'));
    api.get.mockImplementation(path => Promise.resolve(path === '/listings/photos/ph1' ? photo : path === '/listings/l1' ? listing : noticeSource('listing_photo', photo, '/listings?focus_id=l1&source_id=ph1')));
    show(Listings, '/listings?focus_id=l1&source_id=ph1&notice_id=n1');
    const image = await screen.findByRole('img', {name:'Wohnzimmer'});
    expect(api.post).not.toHaveBeenCalled();
    fireEvent.load(image);
    await waitFor(() => expect(api.post).toHaveBeenCalledWith('/notifications/n1/receipt', expect.objectContaining({ source_id: 'ph1', source_kind: 'listing_photo' })));
    expect(api.post).toHaveBeenCalledTimes(1);
  });
  it.each([{...photo,id:'wrong'}, {...photo,listing_id:'foreign'}])('rejects a wrong child identity or parent %j', async response => {
    api.get.mockResolvedValue(response);
    show(Listings, '/listings?focus_id=l1&source_id=ph1&notice_id=n1');
    expect(await screen.findByRole('alert')).toHaveTextContent('für dieses Inserat nicht verfügbar');
    expect(screen.queryByRole('img')).not.toBeInTheDocument();
    expect(api.get.mock.calls.map(([path])=>path)).toEqual(['/listings/photos/ph1']);
    expect(prepareUploadAccess).not.toHaveBeenCalled();
    expect(api.post).not.toHaveBeenCalled();
  });
  it.each([403,404])('shows a generic missing/unavailable photo for HTTP %s', async statusCode => {
    api.get.mockRejectedValue(Object.assign(new Error('sensitive entity information'),{statusCode}));
    show(Listings, '/listings?focus_id=l1&source_id=ph1');
    expect(await screen.findByRole('alert')).toHaveTextContent('für dieses Inserat nicht verfügbar');
    expect(screen.queryByText(/sensitive entity/)).not.toBeInTheDocument();
    expect(api.post).not.toHaveBeenCalled();
  });
  it('rejects a mismatched parent response before exposing an image', async () => {
    api.get.mockImplementation(path => Promise.resolve(path.includes('/photos/') ? photo : {...listing,id:'foreign'}));
    show(Listings, '/listings?focus_id=l1&source_id=ph1');
    expect(await screen.findByRole('alert')).toHaveTextContent('für dieses Inserat nicht verfügbar');
    expect(screen.queryByRole('img')).not.toBeInTheDocument();
  });
  it('handles image errors without a receipt and retries the current photo', async () => {
    show(Listings, '/listings?focus_id=l1&source_id=ph1&notice_id=n1');
    fireEvent.error(await screen.findByRole('img', {name:'Wohnzimmer'}));
    expect(screen.getByRole('alert')).toHaveTextContent('konnte nicht angezeigt werden');
    expect(api.post).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', {name:'Foto erneut laden'}));
    expect(await screen.findByRole('img', {name:'Wohnzimmer'})).toBeInTheDocument();
    expect(api.get.mock.calls.filter(([path])=>path==='/listings/photos/ph1')).toHaveLength(2);
  });
  it('aborts a stale child fetch and restores exact photo selection on Back/Forward', async () => {
    const old = deferred();
    api.get.mockImplementation(path => path === '/listings/photos/ph1' ? old.promise : Promise.resolve(path.includes('/photos/') ? photo2 : listing));
    show(Listings, '/listings?focus_id=l1&source_id=ph1', '/listings?focus_id=l1&source_id=ph2');
    await waitFor(()=>expect(api.get).toHaveBeenCalledWith('/listings/photos/ph1',expect.anything()));
    const signal = api.get.mock.calls.find(([path])=>path==='/listings/photos/ph1')[1].signal;
    fireEvent.click(screen.getByRole('button',{name:'Anderes Ziel'}));
    expect(await screen.findByRole('img',{name:'Küche'})).toBeInTheDocument();
    expect(signal.aborted).toBe(true);
    await act(async()=>old.resolve(photo));
    expect(screen.queryByRole('img',{name:'Wohnzimmer'})).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button',{name:'Zurück'}));
    expect(await screen.findByRole('img',{name:'Wohnzimmer'})).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button',{name:'Vorwärts'}));
    expect(await screen.findByRole('img',{name:'Küche'})).toBeInTheDocument();
    expect(api.post).not.toHaveBeenCalled();
  });
  it('cleans source/notice/focus on close while preserving list filters', async () => {
    show(Listings, '/listings?focus_id=l1&source_id=ph1&notice_id=n1&status=active');
    await screen.findByRole('img',{name:'Wohnzimmer'});
    fireEvent.click(screen.getByRole('button',{name:'Foto schließen'}));
    expect(screen.getByTestId('url')).toHaveTextContent('/listings?status=active');
    expect(screen.queryByRole('img')).not.toBeInTheDocument();
    expect(api.post).not.toHaveBeenCalled();
  });
  it('hides a previous actor photo immediately while the current actor is revalidated', async () => {
    const url='/listings?focus_id=l1&source_id=ph1';
    const view=()=> <MemoryRouter initialEntries={[url]}><Listings /></MemoryRouter>;
    const {rerender}=render(view());
    await screen.findByRole('img',{name:'Wohnzimmer'});
    const pending=deferred(); api.get.mockImplementation(()=>pending.promise); context.actor='other-reader';
    rerender(view());
    expect(screen.queryByRole('img',{name:'Wohnzimmer'})).not.toBeInTheDocument();
    expect(screen.getByText('Verlinktes Inseratfoto wird geladen …')).toBeInTheDocument();
    expect(api.post).not.toHaveBeenCalled();
  });
  it('requires a parent context and never guesses an unrelated listing', async () => {
    show(Listings,'/listings?source_id=ph1');
    expect(await screen.findByRole('alert')).toHaveTextContent('benötigt das zugehörige Inserat');
    expect(api.get).not.toHaveBeenCalled();
    expect(screen.queryByRole('img')).not.toBeInTheDocument();
  });
});
