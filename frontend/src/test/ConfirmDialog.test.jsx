import { act, cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { useRef, useState } from 'react';
import { ConfirmProvider, useConfirm } from '../components/ConfirmDialog';
import { useModalDialog } from '../features/partyWorkspace/useModalDialog';

vi.mock('../i18n', () => ({ useTranslation: () => ({ t: () => undefined }) }));
afterEach(cleanup);
function Actions({ results, multiple = false }) {
  const confirm = useConfirm();
  return <button onClick={() => {
    confirm('Erstes Foto löschen?').then(answer => results.push(['first', answer]));
    if (multiple) confirm('Zweites Foto löschen?').then(answer => results.push(['second', answer]));
  }}>Löschaktion</button>;
}
it('focuses cancel, traps focus and returns to the trigger without approving on Escape', async () => {
  const results = [];
  render(<ConfirmProvider><Actions results={results} /></ConfirmProvider>);
  const trigger = screen.getByRole('button', { name: 'Löschaktion' }); trigger.focus(); fireEvent.click(trigger);
  const dialog = screen.getByRole('dialog', { name: 'Wirklich löschen?' });
  const cancel = within(dialog).getByRole('button', { name: 'Abbrechen' });
  expect(cancel).toHaveFocus();
  fireEvent.keyDown(cancel, { key: 'Tab', shiftKey: true });
  expect(within(dialog).getByRole('button', { name: 'Löschen' })).toHaveFocus();
  await act(async () => fireEvent.keyDown(document, { key: 'Escape' }));
  expect(results).toEqual([['first', false]]); expect(trigger).toHaveFocus();
  expect(document.body.style.overflow).toBe('');
});
it('resolves overlapping requests individually and cancels remaining requests on logout or unmount', async () => {
  const results = [];
  const view = render(<ConfirmProvider><Actions results={results} multiple /></ConfirmProvider>);
  fireEvent.click(screen.getByRole('button', { name: 'Löschaktion' }));
  expect(screen.getByRole('dialog')).toHaveTextContent('Erstes Foto löschen?');
  await act(async () => fireEvent.click(screen.getByRole('button', { name: 'Löschen' })));
  expect(screen.getByRole('dialog')).toHaveTextContent('Zweites Foto löschen?');
  expect(results).toEqual([['first', true]]);
  await act(async () => window.dispatchEvent(new Event('workspace-logout')));
  expect(results).toEqual([['first', true], ['second', false]]);
  fireEvent.click(screen.getByRole('button', { name: 'Löschaktion' }));
  await act(async () => view.unmount());
  expect(results.slice(2)).toEqual([['first', false], ['second', false]]);
});
function Outer({ results }) {
  const [open, setOpen] = useState(true);
  const ref = useRef(null);
  useModalDialog(ref, () => setOpen(false), open);
  return open && <section ref={ref} role="dialog" aria-label="Fotoakte" aria-modal="true" tabIndex={-1}><Actions results={results} /></section>;
}
it('keeps an underlying dossier open when cancelling its nested confirmation', async () => {
  const results = [];
  render(<ConfirmProvider><Outer results={results} /></ConfirmProvider>);
  fireEvent.click(screen.getByRole('button', { name: 'Löschaktion' }));
  await act(async () => fireEvent.keyDown(document, { key: 'Escape' }));
  expect(screen.getByRole('dialog', { name: 'Fotoakte' })).toBeInTheDocument();
  expect(screen.queryByRole('dialog', { name: 'Wirklich löschen?' })).not.toBeInTheDocument();
  expect(results).toEqual([['first', false]]);
});

function Ask({ message, options, results }) {
  const confirm = useConfirm();
  return <button onClick={() => { confirm(message, options).then(answer => results.push(answer)); }}>Fragen</button>;
}

it('words a confirmation after its action: only a deletion asks "Wirklich löschen?"', async () => {
  const results = [];
  const { unmount } = render(<ConfirmProvider><Ask message="„Kunze“ als bezahlt markieren?" options={{ action: 'markPaid' }} results={results} /></ConfirmProvider>);
  fireEvent.click(screen.getByRole('button', { name: 'Fragen' }));
  const dialog = screen.getByRole('dialog', { name: 'Bitte bestätigen' });
  const accept = within(dialog).getByRole('button', { name: 'Als bezahlt markieren' });
  expect(accept).toHaveClass('btn-primary');
  await act(async () => fireEvent.click(accept));
  expect(results).toEqual([true]);
  unmount();
  render(<ConfirmProvider><Ask message="Update jetzt anwenden?" results={results} /></ConfirmProvider>);
  fireEvent.click(screen.getByRole('button', { name: 'Fragen' }));
  expect(within(screen.getByRole('dialog', { name: 'Bitte bestätigen' })).getByRole('button', { name: 'Bestätigen' }))
    .toHaveClass('btn-primary');
});

it('a deletion is red and says what it does', () => {
  render(<ConfirmProvider><Ask message="Standort „Hof“ entfernen?" results={[]} /></ConfirmProvider>);
  fireEvent.click(screen.getByRole('button', { name: 'Fragen' }));
  expect(within(screen.getByRole('dialog', { name: 'Wirklich löschen?' })).getByRole('button', { name: 'Löschen' }))
    .toHaveClass('btn-danger');
});
