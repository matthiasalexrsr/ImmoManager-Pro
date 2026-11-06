import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { MemoryRouter, useLocation, useNavigate } from 'react-router-dom';
import Calendar from '../pages/Calendar';
import { api } from '../api';

const state=vi.hoisted(()=>({actor:'reader',units:[{id:'u1',label:'EG',property_id:'p1'}]}));
vi.mock('../api',()=>({api:{get:vi.fn(),list:vi.fn(),post:vi.fn(),put:vi.fn(),del:vi.fn(),captureSession:vi.fn()}}));
vi.mock('../i18n',()=>({useTranslation:()=>({t:()=>'',locale:'de-DE'})}));
vi.mock('../contexts/AuthContext',()=>({useAuth:()=>({user:{id:state.actor}}),useCanWrite:()=>false}));
vi.mock('../contexts/DataStoreContext',()=>({useDataStore:()=>null,useEntities:()=>({items:state.units,loading:false})}));
vi.mock('../components/ConfirmDialog',()=>({useConfirm:()=>async()=>true}));
vi.mock('../components/DataTable',()=>({default:({data,clearFocusedRow,acknowledgeNotifications})=><section aria-label="Terminliste"><output data-testid="table-ack">{String(acknowledgeNotifications)}</output><button onClick={clearFocusedRow}>Listenfokus entfernen</button>{data.map(row=><span key={row.id}>{row.title}</span>)}</section>}));
const one={id:'e1',title:'Ablesung Stuttgart',description:'Zähler und Schlüssel mitbringen',event_type:'meeting',event_date:'2026-11-20',event_time:'09:30',property_id:'p1',unit_id:'u1',maintenance_case_id:'m1',updated_at:'2026-11-06T10:00:00Z'};
const two={...one,id:'e2',title:'Besichtigung Tübingen',description:'Zweiter Termin'};
function Controls(){const navigate=useNavigate(),location=useLocation();return <><output data-testid="url">{location.pathname}{location.search}</output><button onClick={()=>navigate('/calendar?focus_id=e2')}>Anderer Termin</button><button onClick={()=>navigate(-1)}>Zurück</button><button onClick={()=>navigate(1)}>Vorwärts</button></>;}
function show(url='/calendar?focus_id=e1'){return render(<MemoryRouter initialEntries={[url]}><Controls/><Calendar/></MemoryRouter>);}
const deferred=()=>{let resolve;const promise=new Promise(done=>{resolve=done;});return{promise,resolve};};
beforeEach(()=>{vi.resetAllMocks();state.actor='reader';sessionStorage.clear();api.captureSession.mockImplementation(()=>()=>{});api.list.mockResolvedValue([]);api.post.mockResolvedValue({});api.get.mockImplementation(path=>Promise.resolve(path==='/calendar/e1'?one:path==='/calendar/e2'?two:{notice:{revision:'n-v1'},source:{kind:'calendar',entity_id:'e1',revision:one.updated_at,values:one,href:'/calendar?focus_id=e1'}}));});
afterEach(cleanup);
it('opens an authoritative event despite contradictory list filters',async()=>{
  show('/calendar?focus_id=e1&property_id=p2&unit_id=u2&maintenance_case_id=m2&date_from=2030-01-01&date_to=2030-12-31');
  const heading=await screen.findByRole('heading',{name:one.title,level:2});
  expect(within(heading.closest('section')).getByText(one.description)).toBeInTheDocument();
  expect(api.get).toHaveBeenCalledWith('/calendar/e1',expect.anything());
  expect(screen.getByTestId('table-ack')).toHaveTextContent('false');
  expect(api.post).not.toHaveBeenCalled();
});
it('keeps the exact event readable if list and lookup loads failed',async()=>{
  api.list.mockRejectedValue(new Error('Sammelliste offline'));show();
  expect(await screen.findByRole('heading',{name:one.title,level:2})).toBeInTheDocument();
  expect(screen.getByRole('link',{name:'Immobilie öffnen'})).toHaveAttribute('href','/properties/p1');
  expect(screen.queryByRole('button',{name:'Bearbeiten'})).not.toBeInTheDocument();
});
it.each([403,404])('shows a generic unavailable state for HTTP %s and retries the same id',async statusCode=>{
  api.get.mockRejectedValueOnce(Object.assign(new Error('private source label'),{statusCode}));show('/calendar?focus_id=e1&property_id=p2');
  const card=await screen.findByRole('region',{name:'Termindetails'});
  expect(await within(card).findByRole('alert')).toHaveTextContent('Dieser Termin wurde gelöscht oder ist für Sie nicht zugänglich.');
  expect(screen.queryByText(/private source/)).not.toBeInTheDocument();
  fireEvent.click(within(card).getByRole('button',{name:'Termin erneut laden'}));
  expect(await screen.findByRole('heading',{name:one.title,level:2})).toBeInTheDocument();
  expect(screen.getByTestId('url')).toHaveTextContent('property_id=p2');
});
it('discards late previous records and restores the correct detail on Back and Forward',async()=>{
  const pending=deferred();api.get.mockImplementationOnce(()=>pending.promise);show();
  await waitFor(()=>expect(api.get).toHaveBeenCalledWith('/calendar/e1',expect.anything()));
  const signal=api.get.mock.calls[0][1].signal;
  fireEvent.click(screen.getByRole('button',{name:'Anderer Termin'}));
  expect(await screen.findByRole('heading',{name:two.title,level:2})).toBeInTheDocument();
  expect(signal.aborted).toBe(true);await act(async()=>pending.resolve(one));
  expect(screen.queryByRole('heading',{name:one.title,level:2})).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole('button',{name:'Zurück'}));await screen.findByRole('heading',{name:one.title,level:2});
  fireEvent.click(screen.getByRole('button',{name:'Vorwärts'}));await screen.findByRole('heading',{name:two.title,level:2});
});
it.each(['Alle Termine','Listenfokus entfernen','Objektfilter aufheben'])('cleans source receipt context when %s leaves the detail',async action=>{
  show('/calendar?focus_id=e1&source_id=e1&notice_id=n1&property_id=p1&date_from=2026-01-01');
  await screen.findByRole('heading',{name:one.title,level:2});
  fireEvent.click(screen.getByRole('button',{name:action}));
  expect(screen.getByTestId('url')).not.toHaveTextContent(/focus_id|source_id|notice_id/);
  expect(screen.queryByRole('heading',{name:one.title,level:2})).not.toBeInTheDocument();
});
it('acknowledges only the successfully rendered matching event',async()=>{
  const pending=deferred();api.get.mockImplementationOnce(()=>pending.promise);show('/calendar?focus_id=e1&source_id=e1&notice_id=n1');
  expect(api.post).not.toHaveBeenCalled();await act(async()=>pending.resolve(one));
  await waitFor(()=>expect(api.post).toHaveBeenCalledWith('/notifications/n1/receipt',expect.objectContaining({source_id:'e1',source_kind:'calendar'})));
  expect(api.post).toHaveBeenCalledTimes(1);
});
it('rejects a response for another event without displaying or acknowledging it',async()=>{
  api.get.mockResolvedValue(two);show('/calendar?focus_id=e1&source_id=e1&notice_id=n1');
  expect(await screen.findByRole('alert')).toHaveTextContent('nicht vollständig');
  expect(screen.queryByRole('heading',{name:two.title,level:2})).not.toBeInTheDocument();expect(api.post).not.toHaveBeenCalled();
});
it('hides the previous owner detail immediately during account revalidation',async()=>{
  const view=()=> <MemoryRouter initialEntries={['/calendar?focus_id=e1']}><Calendar/></MemoryRouter>;
  const{rerender}=render(view());await screen.findByRole('heading',{name:one.title,level:2});
  const pending=deferred();api.get.mockImplementation(()=>pending.promise);state.actor='other';rerender(view());
  expect(screen.queryByRole('heading',{name:one.title,level:2})).not.toBeInTheDocument();
  expect(screen.getByText('Termin wird geladen …')).toBeInTheDocument();
});
it('contains a synchronous session capture failure, clears the old event and cleans up its listeners',async()=>{
  const add=vi.spyOn(window,'addEventListener'),remove=vi.spyOn(window,'removeEventListener');
  const view=show();
  try {
    await screen.findByRole('heading',{name:one.title,level:2});
    api.captureSession.mockImplementationOnce(()=>{
      window.dispatchEvent(new Event('workspace-logout'));
      throw Object.assign(new Error('Die Sitzung wurde geändert. Bitte erneut anmelden.'),{code:'SESSION_CHANGED'});
    });
    expect(()=>fireEvent.click(screen.getByRole('button',{name:'Anderer Termin'}))).not.toThrow();
    const detail=screen.getByRole('region',{name:'Termindetails'});
    expect(await within(detail).findByRole('alert')).toHaveTextContent('Die Sitzung wurde geändert');
    expect(within(detail).queryByText(one.description)).not.toBeInTheDocument();
    expect(screen.queryByRole('heading',{name:one.title,level:2})).not.toBeInTheDocument();
    expect(api.get.mock.calls.map(([path])=>path)).toEqual(['/calendar/e1']);
    expect(api.post).not.toHaveBeenCalled();
    view.unmount();
    for(const [name,handler] of add.mock.calls.filter(([name])=>['workspace-owner','workspace-logout'].includes(name))) {
      expect(remove).toHaveBeenCalledWith(name,handler);
    }
  } finally {view.unmount();add.mockRestore();remove.mockRestore();}
});
