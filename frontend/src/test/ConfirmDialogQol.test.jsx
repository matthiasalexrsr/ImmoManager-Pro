import { afterEach, describe, expect, it, vi } from 'vitest';
import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { ConfirmProvider, useConfirm } from '../components/ConfirmDialog';

afterEach(() => cleanup());

function Requester({ outcome }) {
  const confirm = useConfirm();
  return <>
    <button onClick={() => { void confirm('Ersten Eintrag löschen?').then(value => outcome('first', value)); }}>Erster Auftrag</button>
    <button onClick={() => { void confirm('Zweiten Eintrag löschen?').then(value => outcome('second', value)); }}>Zweiter Auftrag</button>
  </>;
}

describe('sichere globale Bestätigungen', () => {
  it('legt konkurrierende Fragen in die Warteschlange und beantwortet beide genau einmal', async () => {
    const outcome = vi.fn();
    render(<ConfirmProvider><Requester outcome={outcome} /></ConfirmProvider>);
    fireEvent.click(screen.getByRole('button', { name: 'Erster Auftrag' }));
    fireEvent.click(screen.getByRole('button', { name: 'Zweiter Auftrag' }));
    let dialog = screen.getByRole('dialog', { name: /Bestätigung/ });
    expect(dialog).toHaveAttribute('aria-modal', 'true');
    expect(within(dialog).getByText('Ersten Eintrag löschen?')).toBeInTheDocument();
    expect(screen.queryByText('Zweiten Eintrag löschen?')).not.toBeInTheDocument();

    fireEvent.click(within(dialog).getByRole('button', { name: 'Abbrechen' }));
    await waitFor(() => expect(outcome).toHaveBeenCalledWith('first', false));
    dialog = screen.getByRole('dialog');
    expect(within(dialog).getByText('Zweiten Eintrag löschen?')).toBeInTheDocument();
    fireEvent.click(within(dialog).getByRole('button', { name: 'Bestätigen' }));
    await waitFor(() => expect(outcome).toHaveBeenCalledWith('second', true));
    expect(outcome).toHaveBeenCalledTimes(2);
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });

  it('fokussiert die sichere Aktion, hält Tab im Dialog und gibt den Fokus zurück', async () => {
    render(<ConfirmProvider><Requester outcome={vi.fn()} /></ConfirmProvider>);
    const trigger = screen.getByRole('button', { name: 'Erster Auftrag' });
    trigger.focus();
    fireEvent.click(trigger);
    const dialog = screen.getByRole('dialog');
    const cancel = within(dialog).getByRole('button', { name: 'Abbrechen' });
    const accept = within(dialog).getByRole('button', { name: 'Bestätigen' });
    expect(cancel).toHaveFocus();
    fireEvent.keyDown(cancel, { key: 'Tab', shiftKey: true });
    expect(accept).toHaveFocus();
    fireEvent.keyDown(accept, { key: 'Tab' });
    expect(cancel).toHaveFocus();
    fireEvent.keyDown(cancel, { key: 'Escape' });
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
    expect(trigger).toHaveFocus();
  });

  it('löst ausstehende Zusagen bei Entfernung der Oberfläche sicher als abgebrochen auf', async () => {
    const outcome = vi.fn();
    const { unmount } = render(<ConfirmProvider><Requester outcome={outcome} /></ConfirmProvider>);
    fireEvent.click(screen.getByRole('button', { name: 'Erster Auftrag' }));
    fireEvent.click(screen.getByRole('button', { name: 'Zweiter Auftrag' }));
    await act(async () => { unmount(); });
    await waitFor(() => expect(outcome).toHaveBeenCalledTimes(2));
    expect(outcome.mock.calls).toEqual(expect.arrayContaining([['first', false], ['second', false]]));
  });

  it('schließt bei einem Klick auf den Hintergrund, nicht beim Klick auf den Dialog', async () => {
    const outcome = vi.fn();
    render(<ConfirmProvider><Requester outcome={outcome} /></ConfirmProvider>);
    fireEvent.click(screen.getByRole('button', { name: 'Erster Auftrag' }));
    const dialog = screen.getByRole('dialog');
    fireEvent.click(dialog);
    expect(dialog).toBeInTheDocument();
    fireEvent.click(dialog.parentElement);
    await waitFor(() => expect(outcome).toHaveBeenCalledWith('first', false));
  });
});


it('fokussiert auch bei der nächsten Frage nach einer Bestätigung wieder Abbrechen', async () => {
  const outcome = vi.fn();
  render(<ConfirmProvider><Requester outcome={outcome} /></ConfirmProvider>);
  fireEvent.click(screen.getByRole('button', { name: 'Erster Auftrag' }));
  fireEvent.click(screen.getByRole('button', { name: 'Zweiter Auftrag' }));
  fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Bestätigen' }));
  await waitFor(() => expect(outcome).toHaveBeenCalledWith('first', true));
  const next = screen.getByRole('dialog');
  expect(within(next).getByText('Zweiten Eintrag löschen?')).toBeInTheDocument();
  expect(within(next).getByRole('button', { name: 'Abbrechen' })).toHaveFocus();
  fireEvent.click(within(next).getByRole('button', { name: 'Abbrechen' }));
  await waitFor(() => expect(outcome).toHaveBeenCalledWith('second', false));
});
