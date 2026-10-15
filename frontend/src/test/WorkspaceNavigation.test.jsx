import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter, Routes, Route, useNavigate } from 'react-router-dom';
import DataTable from '../components/DataTable';
vi.mock('../contexts/AuthContext', () => ({ useAuth: () => null, useCanWrite: () => true }));
vi.mock('../i18n', () => ({ useTranslation: () => ({ t: key => key }) }));
const columns = [{ key: 'title', label: 'Aufgabe', filterType: 'text' }];
const data = [{ id: 'a', title: 'Rückruf Anna' }, { id: 'b', title: 'Ablesung Ben' }];
function List() {
  const navigate = useNavigate();
  return <DataTable title="Arbeit" columns={columns} data={data} onEdit={() => navigate('/detail')} />;
}
function Detail() { const navigate = useNavigate(); return <button onClick={() => navigate(-1)}>Zurück zur Auswahl</button>; }
beforeEach(() => { sessionStorage.clear(); localStorage.clear(); });
afterEach(cleanup);
it('restores search and row highlight on Back to a concrete filtered address', async () => {
  render(<MemoryRouter initialEntries={['/tasks?property_id=haus-a']}><Routes><Route path="/tasks" element={<List />} /><Route path="/detail" element={<Detail />} /></Routes></MemoryRouter>);
  const search = document.querySelector('.search-input');
  fireEvent.change(search, { target: { value: 'Anna' } });
  fireEvent.click(screen.getByRole('button', { name: /Bearbeiten|ui.buttons.edit/ }));
  fireEvent.click(await screen.findByText('Zurück zur Auswahl'));
  await screen.findByText('Rückruf Anna');
  expect(document.querySelector('.search-input')).toHaveValue('Anna');
  expect(screen.queryByText('Ablesung Ben')).not.toBeInTheDocument();
  expect(screen.getByText('Rückruf Anna').closest('tr')).toHaveClass('workspace-row-mark');
});
