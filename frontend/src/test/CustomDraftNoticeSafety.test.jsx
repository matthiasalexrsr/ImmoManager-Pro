import { afterEach, expect, it, vi } from 'vitest';
import { act, cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import CustomDraftNotice from '../components/CustomDraftNotice';
import de from '../../../i18n/de-DE.json';
import en from '../../../i18n/en-US.json';
import es from '../../../i18n/es-ES.json';

afterEach(cleanup);
const makeDraft = (sessionKey = 'draft-A', body = 'Wichtiger Entwurf') => ({
  enabled: true, sessionKey, status: 'recovery',
  recovery: { values: { body }, source_state: { status: 'current' } },
  clear: vi.fn().mockResolvedValue(undefined),
  recover: vi.fn().mockResolvedValue(undefined),
  retry: vi.fn(),
});

it('requires a second deliberate action and allows cancel without deleting a recovered draft', () => {
  const draft = makeDraft();
  const onRestore = vi.fn();
  render(<CustomDraftNotice draft={draft} onRestore={onRestore} />);
  const discard = screen.getByRole('button', { name: 'Entwurf verwerfen' });
  expect(discard).toHaveAttribute('aria-expanded', 'false');
  expect(discard).not.toHaveAttribute('aria-controls');
  fireEvent.click(discard);
  const group = screen.getByRole('group', { name: 'Entwurf verwerfen bestätigen' });
  expect(discard).toHaveAttribute('aria-expanded', 'true');
  expect(discard).toHaveAttribute('aria-controls', group.id);
  expect(group).toHaveTextContent('Die ungespeicherten Eingaben gehen verloren');
  expect(draft.clear).not.toHaveBeenCalled();
  const keep = within(group).getByRole('button', { name: 'Entwurf behalten' });
  expect(keep).toHaveFocus();
  fireEvent.click(keep);
  expect(discard).toHaveFocus();
  expect(screen.queryByRole('group', { name: 'Entwurf verwerfen bestätigen' })).not.toBeInTheDocument();
  expect(draft.clear).not.toHaveBeenCalled();
  expect(onRestore).not.toHaveBeenCalled();
  expect(screen.getByText('Wichtiger Entwurf')).toBeInTheDocument();
});

it('Escape cancels only the draft-discard confirmation, and Ctrl+Enter cannot reach an outer form', () => {
  const draft = makeDraft();
  const parentHotkey = vi.fn();
  render(<div onKeyDown={parentHotkey}><CustomDraftNotice draft={draft} /></div>);
  const discard = screen.getByRole('button', { name: 'Entwurf verwerfen' });
  fireEvent.click(discard);
  const keep = screen.getByRole('button', { name: 'Entwurf behalten' });
  fireEvent.keyDown(keep, { key: 'Enter', ctrlKey: true });
  expect(parentHotkey).not.toHaveBeenCalled();
  expect(draft.clear).not.toHaveBeenCalled();
  fireEvent.keyDown(keep, { key: 'Escape' });
  expect(screen.queryByRole('group', { name: 'Entwurf verwerfen bestätigen' })).not.toBeInTheDocument();
  expect(discard).toHaveFocus();
  expect(parentHotkey).not.toHaveBeenCalled();
  expect(draft.clear).not.toHaveBeenCalled();
});

it('runs at most one confirmed deletion and leaves accessible focus after completion', async () => {
  let resolveDelete;
  const draft = makeDraft();
  draft.clear = vi.fn(() => new Promise(resolve => { resolveDelete = resolve; }));
  render(<CustomDraftNotice draft={draft} />);
  fireEvent.click(screen.getByRole('button', { name: 'Entwurf verwerfen' }));
  const confirm = screen.getByRole('button', { name: 'Endgültig verwerfen' });
  fireEvent.click(confirm);
  fireEvent.click(confirm);
  expect(draft.clear).toHaveBeenCalledTimes(1);
  expect(confirm).toBeDisabled();
  await act(async () => { resolveDelete(); });
  expect(screen.queryByRole('group', { name: 'Entwurf verwerfen bestätigen' })).not.toBeInTheDocument();
  expect(screen.getByRole('region', { name: 'Entwurfssicherung' })).toHaveFocus();
});

it('preserves the recovery when deletion fails, and retries only after another explicit click', async () => {
  const draft = makeDraft();
  draft.clear = vi.fn().mockRejectedValueOnce(new Error('Sicherung offline')).mockResolvedValue(undefined);
  render(<CustomDraftNotice draft={draft} />);
  fireEvent.click(screen.getByRole('button', { name: 'Entwurf verwerfen' }));
  fireEvent.click(screen.getByRole('button', { name: 'Endgültig verwerfen' }));
  expect(await screen.findByText('Sicherung offline')).toHaveAttribute('role', 'alert');
  expect(screen.getByRole('group', { name: 'Entwurf verwerfen bestätigen' })).toBeInTheDocument();
  expect(screen.getByText('Wichtiger Entwurf')).toBeInTheDocument();
  expect(draft.retry).not.toHaveBeenCalled();
  expect(draft.clear).toHaveBeenCalledTimes(1);
  await act(async () => { fireEvent.click(screen.getByRole('button', { name: 'Endgültig verwerfen' })); });
  expect(draft.clear).toHaveBeenCalledTimes(2);
  expect(screen.queryByRole('group', { name: 'Entwurf verwerfen bestätigen' })).not.toBeInTheDocument();
});

it('cannot apply an old deletion result to a newly opened draft session', async () => {
  let resolveOld;
  const draftA = makeDraft('A', 'Alter Entwurf');
  draftA.clear = vi.fn(() => new Promise(resolve => { resolveOld = resolve; }));
  const { rerender } = render(<CustomDraftNotice draft={draftA} />);
  fireEvent.click(screen.getByRole('button', { name: 'Entwurf verwerfen' }));
  fireEvent.click(screen.getByRole('button', { name: 'Endgültig verwerfen' }));
  expect(draftA.clear).toHaveBeenCalledOnce();
  const draftB = makeDraft('B', 'Neuer Entwurf');
  rerender(<CustomDraftNotice draft={draftB} />);
  expect(screen.getByText('Neuer Entwurf')).toBeInTheDocument();
  expect(screen.queryByRole('group', { name: 'Entwurf verwerfen bestätigen' })).not.toBeInTheDocument();
  await act(async () => { resolveOld(); });
  expect(screen.getByText('Neuer Entwurf')).toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Entwurf verwerfen' })).toBeEnabled();
  expect(draftB.clear).not.toHaveBeenCalled();
});

it('honors an external lock while a recovered-draft confirmation is visible', () => {
  const draft = makeDraft();
  const { rerender } = render(<CustomDraftNotice draft={draft} />);
  fireEvent.click(screen.getByRole('button', { name: 'Entwurf verwerfen' }));
  rerender(<CustomDraftNotice draft={draft} locked />);
  const keep = screen.getByRole('button', { name: 'Entwurf behalten' });
  const confirm = screen.getByRole('button', { name: 'Endgültig verwerfen' });
  expect(keep).toBeDisabled();
  expect(confirm).toBeDisabled();
  fireEvent.keyDown(screen.getByRole('group', { name: 'Entwurf verwerfen bestätigen' }), { key: 'Escape' });
  expect(screen.getByRole('group', { name: 'Entwurf verwerfen bestätigen' })).toBeInTheDocument();
  expect(draft.clear).not.toHaveBeenCalled();
  rerender(<CustomDraftNotice draft={draft} />);
  expect(keep).toBeEnabled();
  fireEvent.click(keep);
  expect(draft.clear).not.toHaveBeenCalled();
});

it('uses shared translations for the discard action and both confirmation choices', () => {
  for (const locale of [de, en, es]) {
    expect(locale.ui.form.discardDraft).toBeTruthy();
    expect(locale.ui.form.keepRecoveredDraft).toBeTruthy();
    expect(locale.ui.form.discardRecoveredDraft).toBeTruthy();
    expect(locale.ui.form.recoveredDiscardWarning).toBeTruthy();
    expect(locale.ui.form.confirmRecoveredDiscard).toBeTruthy();
  }
});
