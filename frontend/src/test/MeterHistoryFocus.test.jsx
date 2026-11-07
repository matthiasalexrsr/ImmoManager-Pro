import { Profiler, useState } from 'react';
import { act, cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import MeterHistory from '../features/meters/MeterHistory';
import FormModal from '../components/FormModal';
import { api } from '../api';

vi.mock('../api', () => ({ api: { get: vi.fn(), post: vi.fn(), captureSession: vi.fn() } }));
vi.mock('../contexts/AuthContext', () => ({ useAuth: () => ({ user: { id: 'focus-reader' } }) }));
vi.mock('../i18n', () => ({ useTranslation: () => ({ t: () => undefined, locale: 'de-DE' }) }));

const history = {
  meter: { id: 'm1', meter_type: 'cold_water', measure_unit: 'm³' },
  readings: [
    { id: 'r1', reading_date: '2026-10-01', value: 123.4, notes: 'Oktoberablesung' },
    { id: 'r2', reading_date: '2026-11-01', value: 140.8, notes: 'Novemberablesung' },
  ], years: [], contracts: [],
};

function deferred() {
  let resolve;
  const promise = new Promise(yes => { resolve = yes; });
  return { promise, resolve };
}

// Profiler runs in the commit/layout phase. Waiting for a DOM query alone can
// resolve before passive effects; record the first accessible commit itself.
function traceCommits() {
  const commits = [];
  const onRender = () => {
    const dialog = document.querySelector('[aria-labelledby="meter-history-title"]');
    const selected = dialog?.querySelector('[aria-label="Verlinkte Ablesung"]');
    commits.push({ covered: dialog?.getAttribute('aria-hidden') === 'true',
      selected: selected?.textContent ?? null,
      active: document.activeElement,
      readingHasFocus: Boolean(selected && selected === document.activeElement) });
  };
  return { commits, onRender };
}

beforeEach(() => {
  vi.resetAllMocks();
  api.captureSession.mockImplementation(() => () => {});
  api.get.mockResolvedValue(history);
});
afterEach(cleanup);

describe('meter history focus at the accessible commit', () => {
  it.each([null, 'r1'])('focuses Close while the authorized history is loading (child %s)', focusedReadingId => {
    api.get.mockReturnValue(deferred().promise);
    const trace = traceCommits();
    render(<Profiler id="history" onRender={trace.onRender}><MemoryRouter>
      <MeterHistory meterId="m1" meterLabel="Zähler 1" focusedReadingId={focusedReadingId} onClose={vi.fn()} />
    </MemoryRouter></Profiler>);
    const close = screen.getByRole('button', { name: 'Schließen' });
    expect(trace.commits[0].active).toBe(close);
    expect(close).toHaveFocus();
    expect(screen.getByRole('status')).toHaveTextContent('Verlauf wird geladen');
  });

  it('focuses the exact authorized reading in its first commit, before passive effects', async () => {
    const pending = deferred(); api.get.mockReturnValue(pending.promise);
    const trace = traceCommits();
    render(<Profiler id="history" onRender={trace.onRender}><MemoryRouter>
      <MeterHistory meterId="m1" meterLabel="Zähler 1" focusedReadingId="r1" onClose={vi.fn()} canWrite={false} />
    </MemoryRouter></Profiler>);
    await act(async () => pending.resolve(history));
    const details = screen.getByRole('region', { name: 'Verlinkte Ablesung' });
    expect(details).toHaveTextContent('Oktoberablesung');
    expect(details).toHaveFocus();
    expect(trace.commits.find(commit => commit.selected).readingHasFocus).toBe(true);
    expect(api.post).not.toHaveBeenCalled();
  });

  it('keeps a covered history from stealing focus, including after its data arrives', async () => {
    const pending = deferred(); api.get.mockReturnValue(pending.promise);
    const opener = document.createElement('button'); document.body.append(opener); opener.focus();
    const trace = traceCommits();
    const view = covered => <Profiler id="history" onRender={trace.onRender}><MemoryRouter>
      <MeterHistory meterId="m1" meterLabel="Zähler 1" focusedReadingId="r1" covered={covered} onClose={vi.fn()} />
    </MemoryRouter></Profiler>;
    try {
      const { rerender } = render(view(true));
      await act(async () => pending.resolve(history));
      expect(opener).toHaveFocus();
      expect(trace.commits.filter(commit => commit.covered).every(commit => commit.active === opener)).toBe(true);
      rerender(view(false));
      expect(screen.getByRole('region', { name: 'Verlinkte Ablesung' })).toHaveFocus();
      expect(trace.commits.find(commit => !commit.covered && commit.selected).readingHasFocus).toBe(true);
    } finally { opener.remove(); }
  });

  it.each([null, 'r1'])('restores the matching history target after the real edit modal closes (child %s)', async focusedReadingId => {
    const trace = traceCommits();
    function Layered() {
      const [editing, setEditing] = useState(false);
      return <MemoryRouter>
        <MeterHistory meterId="m1" meterLabel="Zähler 1" focusedReadingId={focusedReadingId} covered={editing}
          onClose={vi.fn()} onEdit={() => setEditing(true)} />
        {editing && <FormModal title="Zähler bearbeiten" autosave={false}
          fields={[{ key: 'serial', label: 'Seriennummer' }]} onSave={vi.fn()} onClose={() => setEditing(false)} />}
      </MemoryRouter>;
    }
    await act(async () => render(<Profiler id="layered" onRender={trace.onRender}><Layered /></Profiler>));
    fireEvent.click(screen.getByRole('button', { name: 'Zähler bearbeiten' }));
    expect(screen.getByLabelText('Seriennummer')).toHaveFocus();
    const beforeClose = trace.commits.length;
    fireEvent.keyDown(document, { key: 'Escape' });
    expect(screen.queryByRole('dialog', { name: 'Zähler bearbeiten' })).not.toBeInTheDocument();
    const target = focusedReadingId ? screen.getByRole('region', { name: 'Verlinkte Ablesung' }) : screen.getByRole('button', { name: 'Schließen' });
    expect(target).toHaveFocus();
    expect(trace.commits.slice(beforeClose).find(commit => !commit.covered).active).toBe(target);
  });

  it('moves focus with the selected child and clears the destination when it is missing', async () => {
    const trace = traceCommits();
    const view = id => <Profiler id="history" onRender={trace.onRender}><MemoryRouter>
      <MeterHistory meterId="m1" meterLabel="Zähler 1" focusedReadingId={id} onClose={vi.fn()} />
    </MemoryRouter></Profiler>;
    let rendered;
    await act(async () => { rendered = render(view('r1')); });
    const first = screen.getByRole('region', { name: 'Verlinkte Ablesung' });
    rendered.rerender(view('r2'));
    expect(screen.getByRole('region', { name: 'Verlinkte Ablesung' })).toHaveTextContent('Novemberablesung');
    expect(screen.getByRole('region', { name: 'Verlinkte Ablesung' })).toHaveFocus();
    rendered.rerender(view('missing'));
    expect(screen.queryByRole('region', { name: 'Verlinkte Ablesung' })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Schließen' })).toHaveFocus();
    expect(first).not.toBeInTheDocument();
    expect(trace.commits.at(-1).active).toBe(screen.getByRole('button', { name: 'Schließen' }));
    expect(api.get).toHaveBeenCalledTimes(1);
  });

  it('does not retain an invalidated authorized reading or its focus', async () => {
    await act(async () => render(<MemoryRouter><MeterHistory meterId="m1" meterLabel="Zähler 1" focusedReadingId="r1" onClose={vi.fn()} /></MemoryRouter>));
    const details = screen.getByRole('region', { name: 'Verlinkte Ablesung' });
    expect(details).toHaveFocus();
    act(() => window.dispatchEvent(new Event('workspace-logout')));
    expect(screen.getByRole('alert')).toHaveTextContent('Die Sitzung wurde geändert');
    expect(details).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Schließen' })).toHaveFocus();
    expect(api.get).toHaveBeenCalledTimes(1);
  });

  it('preserves Tab containment, Escape and return focus to the connected opener', async () => {
    const opener = document.createElement('button'); document.body.append(opener); opener.focus();
    function OpenHistory() {
      const [open, setOpen] = useState(true);
      return <MemoryRouter>{open && <MeterHistory meterId="m1" meterLabel="Zähler 1" focusedReadingId="r1"
        propertyId="p1" propertyName="Haus" onClose={() => setOpen(false)} />}</MemoryRouter>;
    }
    try {
      await act(async () => render(<OpenHistory />));
      const dialog = screen.getByRole('dialog');
      const targets = [...dialog.querySelectorAll('button:not(:disabled), a[href], [tabindex="0"]')];
      targets.at(-1).focus(); fireEvent.keyDown(document, { key: 'Tab' });
      expect(targets[0]).toHaveFocus();
      fireEvent.keyDown(document, { key: 'Tab', shiftKey: true });
      expect(targets.at(-1)).toHaveFocus();
      expect(within(dialog).getByRole('region', { name: 'Verlinkte Ablesung' })).toBeInTheDocument();
      fireEvent.keyDown(document, { key: 'Escape' });
      expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
      expect(opener).toHaveFocus();
    } finally { opener.remove(); }
  });
});
