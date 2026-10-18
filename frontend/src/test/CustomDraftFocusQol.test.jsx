import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import CustomDraftNotice from '../components/CustomDraftNotice';

afterEach(cleanup);

function draft(sessionKey = 'a') {
  return {
    enabled: true, ready: true, sessionKey, status: 'recovery',
    recovery: { values: { body: 'Privater Entwurf' }, source_state: { status: 'current' } },
    recover: vi.fn().mockResolvedValue(undefined),
    clear: vi.fn().mockResolvedValue(undefined),
    retry: vi.fn(),
  };
}
function Editor({ state, onRestore = vi.fn(), children }) {
  return <div>
    <CustomDraftNotice draft={state} onRestore={onRestore} />
    {children || <fieldset><label htmlFor="editable-note">Notiz</label><textarea id="editable-note" /></fieldset>}
  </div>;
}

it('returns to the editable field only after a successful recovery has been applied', async () => {
  const current = draft();
  const onRestore = vi.fn();
  const { rerender } = render(<Editor state={current} onRestore={onRestore} />);
  const resume = screen.getByRole('button', { name: 'Entwurf übernehmen' });
  resume.focus();
  fireEvent.click(resume);
  await waitFor(() => expect(current.recover).toHaveBeenCalledWith(current.recovery.values));
  expect(onRestore).toHaveBeenCalledWith(current.recovery.values);
  // Until the hook publishes a ready state, its recovery actions still exist.
  expect(screen.getByRole('region', { name: 'Entwurfssicherung' })).toContainElement(resume);
  rerender(<Editor state={{ ...current, recovery: null, status: 'ready' }} onRestore={onRestore} />);
  expect(screen.getByRole('textbox', { name: 'Notiz' })).toHaveFocus();
  expect(current.clear).not.toHaveBeenCalled();
});

it('moves from a completed discard to an editable field without executing domain save', async () => {
  const current = draft();
  const { rerender } = render(<Editor state={current} />);
  fireEvent.click(screen.getByRole('button', { name: 'Entwurf verwerfen' }));
  fireEvent.click(screen.getByRole('button', { name: 'Endgültig verwerfen' }));
  await waitFor(() => expect(current.clear).toHaveBeenCalledOnce());
  expect(screen.getByRole('region', { name: 'Entwurfssicherung' })).toHaveFocus();
  rerender(<Editor state={{ ...current, recovery: null, status: 'ready' }} />);
  expect(screen.getByRole('textbox', { name: 'Notiz' })).toHaveFocus();
  expect(current.recover).not.toHaveBeenCalled();
});

it('skips disabled, hidden, readonly and inert controls in sibling forms', async () => {
  const current = draft();
  const { rerender } = render(<Editor state={current}>
    <fieldset disabled><input aria-label="Gesperrt" /></fieldset>
    <div><input type="hidden" aria-label="Versteckt" /><input readOnly aria-label="Nur Lesen" /></div>
    <div inert={true}><textarea aria-label="Nicht zugänglich" /></div>
    <div hidden><input aria-label="Optisch ausgeblendet" /></div>
    <div aria-disabled="true"><input aria-label="Verboten" /></div>
    <div><input aria-label="Bearbeitbar" /></div>
  </Editor>);
  fireEvent.click(screen.getByRole('button', { name: 'Entwurf übernehmen' }));
  await waitFor(() => expect(current.recover).toHaveBeenCalledOnce());
  rerender(<Editor state={{ ...current, recovery: null, status: 'ready' }}>
    <fieldset disabled><input aria-label="Gesperrt" /></fieldset>
    <div><input type="hidden" aria-label="Versteckt" /><input readOnly aria-label="Nur Lesen" /></div>
    <div inert={true}><textarea aria-label="Nicht zugänglich" /></div>
    <div hidden><input aria-label="Optisch ausgeblendet" /></div>
    <div aria-disabled="true"><input aria-label="Verboten" /></div>
    <div><input aria-label="Bearbeitbar" /></div>
  </Editor>);
  expect(screen.getByRole('textbox', { name: 'Bearbeitbar' })).toHaveFocus();
});

it('retains focus on the notice when there is no nearby editable field', async () => {
  const current = draft();
  const { rerender } = render(<Editor state={current}><p>Nur Informationen</p></Editor>);
  fireEvent.click(screen.getByRole('button', { name: 'Entwurf übernehmen' }));
  await waitFor(() => expect(current.recover).toHaveBeenCalledOnce());
  rerender(<Editor state={{ ...current, recovery: null, status: 'ready' }}><p>Nur Informationen</p></Editor>);
  expect(screen.getByRole('region', { name: 'Entwurfssicherung' })).toHaveFocus();
});

it('does not override a deliberate focus target selected by the calling form', async () => {
  const current = draft();
  const onRestore = vi.fn(() => document.querySelector('#review-action')?.focus());
  const { rerender } = render(<Editor state={current} onRestore={onRestore}>
    <input aria-label="Feld" /><button id="review-action" type="button">Weiter prüfen</button>
  </Editor>);
  fireEvent.click(screen.getByRole('button', { name: 'Entwurf übernehmen' }));
  await waitFor(() => expect(onRestore).toHaveBeenCalledOnce());
  rerender(<Editor state={{ ...current, recovery: null, status: 'ready' }} onRestore={onRestore}>
    <input aria-label="Feld" /><button id="review-action" type="button">Weiter prüfen</button>
  </Editor>);
  expect(screen.getByRole('button', { name: 'Weiter prüfen' })).toHaveFocus();
});

it('waits for the draft writer to be ready before shifting focus to restored fields', async () => {
  const current = draft();
  const { rerender } = render(<Editor state={current} />);
  fireEvent.click(screen.getByRole('button', { name: 'Entwurf übernehmen' }));
  await waitFor(() => expect(current.recover).toHaveBeenCalledOnce());
  rerender(<Editor state={{ ...current, recovery: null, ready: false, status: 'loading' }} />);
  expect(screen.getByRole('textbox', { name: 'Notiz' })).not.toHaveFocus();
  rerender(<Editor state={{ ...current, recovery: null, ready: true, status: 'ready' }} />);
  expect(screen.getByRole('textbox', { name: 'Notiz' })).toHaveFocus();
});

it('never hands focus to a different record when a previous recovery resolves late', async () => {
  let complete;
  const previous = draft('old');
  previous.recover = vi.fn(() => new Promise(resolve => { complete = resolve; }));
  const onRestore = vi.fn();
  const { rerender } = render(<Editor state={previous} onRestore={onRestore} />);
  fireEvent.click(screen.getByRole('button', { name: 'Entwurf übernehmen' }));
  expect(previous.recover).toHaveBeenCalledOnce();
  const current = draft('new');
  rerender(<Editor state={current} onRestore={onRestore} />);
  const discard = screen.getByRole('button', { name: 'Entwurf verwerfen' });
  discard.focus();
  await act(async () => { complete(); });
  expect(onRestore).not.toHaveBeenCalled();
  expect(discard).toHaveFocus();
  expect(screen.getByRole('textbox', { name: 'Notiz' })).not.toHaveFocus();
  expect(current.recover).not.toHaveBeenCalled();
});

it('ignores irrelevant controls preceding the notice and focuses only the adjacent editor', async () => {
  const current = draft();
  function Page({ state }) {
    return <><button type="button">Globale Navigation</button>
      <aside><input aria-label="Fremdes Suchfeld" /></aside>
      <Editor state={state}><form><input aria-label="Facheingabe" /></form></Editor></>;
  }
  const { rerender } = render(<Page state={current} />);
  fireEvent.click(screen.getByRole('button', { name: 'Entwurf übernehmen' }));
  await waitFor(() => expect(current.recover).toHaveBeenCalledOnce());
  rerender(<Page state={{ ...current, recovery: null, status: 'ready' }} />);
  expect(screen.getByRole('textbox', { name: 'Facheingabe' })).toHaveFocus();
  expect(screen.getByRole('textbox', { name: 'Fremdes Suchfeld' })).not.toHaveFocus();
});

it('does not move focus or apply recovered data after an unsuccessful recovery', async () => {
  const current = draft();
  current.recover = vi.fn().mockRejectedValue(new Error('Entwurf wurde zwischenzeitlich geändert'));
  const onRestore = vi.fn();
  render(<Editor state={current} onRestore={onRestore} />);
  const resume = screen.getByRole('button', { name: 'Entwurf übernehmen' });
  resume.focus();
  fireEvent.click(resume);
  expect(await screen.findByRole('alert')).toHaveTextContent('Entwurf wurde zwischenzeitlich geändert');
  expect(resume).toHaveFocus();
  expect(screen.getByRole('textbox', { name: 'Notiz' })).not.toHaveFocus();
  expect(onRestore).not.toHaveBeenCalled();
  expect(current.clear).not.toHaveBeenCalled();
});
