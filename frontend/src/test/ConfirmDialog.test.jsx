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
  const dialog = screen.getByRole('dialog', { name: 'Bestätigung' });
  const cancel = within(dialog).getByRole('button', { name: 'Abbrechen' });
  expect(cancel).toHaveFocus();
  fireEvent.keyDown(cancel, { key: 'Tab', shiftKey: true });
  expect(within(dialog).getByRole('button', { name: 'Bestätigen' })).toHaveFocus();
  await act(async () => fireEvent.keyDown(document, { key: 'Escape' }));
  expect(results).toEqual([['first', false]]); expect(trigger).toHaveFocus();
  expect(document.body.style.overflow).toBe('');
});
it('resolves overlapping requests individually and cancels remaining requests on logout or unmount', async () => {
  const results = [];
  const view = render(<ConfirmProvider><Actions results={results} multiple /></ConfirmProvider>);
  fireEvent.click(screen.getByRole('button', { name: 'Löschaktion' }));
  expect(screen.getByRole('dialog')).toHaveTextContent('Erstes Foto löschen?');
  await act(async () => fireEvent.click(screen.getByRole('button', { name: 'Bestätigen' })));
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
  expect(screen.queryByRole('dialog', { name: 'Bestätigung' })).not.toBeInTheDocument();
  expect(results).toEqual([['first', false]]);
});
