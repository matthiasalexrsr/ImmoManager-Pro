import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import InternalReplyComposer from '../features/communication/InternalReplyComposer';
import de from '../../../i18n/de-DE.json';
import en from '../../../i18n/en-US.json';
import es from '../../../i18n/es-ES.json';

const state = vi.hoisted(() => ({ current: null, locale: 'de-DE' }));
vi.mock('../hooks/useEntityFormDraft', () => ({ default: () => state.current }));
vi.mock('../i18n', async () => {
  const catalogs = {
    'de-DE': (await import('../../../i18n/de-DE.json')).default,
    'en-US': (await import('../../../i18n/en-US.json')).default,
    'es-ES': (await import('../../../i18n/es-ES.json')).default,
  };
  return { useTranslation: () => ({
    t: key => key.split('.').reduce((obj, item) => obj?.[item], catalogs[state.locale]) || key,
  }) };
});

const thread = id => ({ id, subject: 'Fall ' + id });
const notice = { saved: false, sending: false, uncertain: false };
function makeDraft(id = 'a', body = 'Nicht gesendeter Privattext') {
  return {
    enabled: true, ready: true, sessionKey: 'message-reply:' + id, status: 'recovery',
    recovery: { values: { body }, source_state: { status: 'current' } },
    error: '', isCurrent: key => key === 'message-reply:' + id,
    compare: vi.fn().mockResolvedValue(undefined), recover: vi.fn().mockResolvedValue(undefined),
    clear: vi.fn().mockResolvedValue(undefined), stage: vi.fn(), retry: vi.fn(),
  };
}
function show(props = {}) {
  const onChange = vi.fn();
  const onSend = vi.fn();
  const view = render(<InternalReplyComposer thread={thread('a')} value="" onChange={onChange}
    onSend={onSend} notice={notice} {...props} />);
  return { ...view, onChange, onSend };
}
beforeEach(() => { state.current = makeDraft(); state.locale = 'de-DE'; });
afterEach(() => cleanup());

it('requires confirmation, keeps the private text and cancels without deleting or sending', () => {
  const draft = state.current;
  const { onChange, onSend } = show({ value: 'Aktuelle Antwort' });
  const region = screen.getByRole('region', { name: 'Wiedergefundener Antwortentwurf' });
  const discard = within(region).getByRole('button', { name: 'Entwurf verwerfen' });
  expect(discard).toHaveAttribute('aria-expanded', 'false');
  expect(discard).not.toHaveAttribute('aria-controls');
  fireEvent.click(discard);
  const confirmation = within(region).getByRole('group', { name: 'Entwurf verwerfen bestätigen' });
  expect(discard).toHaveAttribute('aria-expanded', 'true');
  expect(discard).toHaveAttribute('aria-controls', confirmation.id);
  expect(confirmation).toHaveTextContent('Die ungespeicherten Eingaben gehen verloren');
  expect(within(confirmation).getByRole('button', { name: 'Entwurf behalten' })).toHaveFocus();
  expect(screen.getByRole('button', { name: 'Senden' })).toBeDisabled();
  expect(screen.getByRole('textbox', { name: 'Antwort an „Fall a“' })).toBeDisabled();
  expect(draft.clear).not.toHaveBeenCalled();

  fireEvent.click(within(confirmation).getByRole('button', { name: 'Entwurf behalten' }));
  expect(discard).toHaveFocus();
  expect(discard).toHaveAttribute('aria-expanded', 'false');
  expect(discard).not.toHaveAttribute('aria-controls');
  expect(screen.queryByRole('group', { name: 'Entwurf verwerfen bestätigen' })).not.toBeInTheDocument();
  expect(screen.getByText('Nicht gesendeter Privattext')).toBeInTheDocument();
  expect(screen.getByRole('textbox')).toHaveValue('Aktuelle Antwort');
  expect(draft.clear).not.toHaveBeenCalled();
  expect(onChange).not.toHaveBeenCalled();
  expect(onSend).not.toHaveBeenCalled();
});

it('Escape cancels the confirmation; Ctrl+Enter does not submit from the reply or confirmation', () => {
  const parentKey = vi.fn(), onSend = vi.fn();
  render(<div onKeyDown={parentKey}><InternalReplyComposer thread={thread('a')} value="Nachricht"
    onChange={vi.fn()} onSend={onSend} notice={notice} /></div>);
  const discard = screen.getByRole('button', { name: 'Entwurf verwerfen' });
  fireEvent.click(discard);
  const keep = screen.getByRole('button', { name: 'Entwurf behalten' });
  fireEvent.keyDown(keep, { key: 'Enter', ctrlKey: true });
  expect(parentKey).not.toHaveBeenCalled();
  fireEvent.keyDown(screen.getByRole('textbox'), { key: 'Enter', ctrlKey: true });
  expect(onSend).not.toHaveBeenCalled();
  fireEvent.keyDown(keep, { key: 'Escape' });
  expect(discard).toHaveFocus();
  expect(screen.queryByRole('group', { name: 'Entwurf verwerfen bestätigen' })).not.toBeInTheDocument();
  expect(state.current.clear).not.toHaveBeenCalled();
  expect(onSend).not.toHaveBeenCalled();
});

it('issues exactly one confirmed deletion and restores textarea focus when recovery disappears', async () => {
  let complete;
  const draft = state.current;
  draft.clear = vi.fn(() => new Promise(resolve => { complete = resolve; }));
  const { rerender, onChange, onSend } = show();
  const discard = screen.getByRole('button', { name: 'Entwurf verwerfen' });
  fireEvent.click(discard);
  const confirm = screen.getByRole('button', { name: 'Endgültig verwerfen' });
  fireEvent.click(confirm);
  fireEvent.click(confirm);
  expect(draft.clear).toHaveBeenCalledTimes(1);
  expect(confirm).toBeDisabled();
  expect(screen.getByRole('button', { name: 'Senden' })).toBeDisabled();
  await act(async () => { complete(); });
  expect(screen.queryByRole('group', { name: 'Entwurf verwerfen bestätigen' })).not.toBeInTheDocument();

  state.current = { ...draft, recovery: null };
  rerender(<InternalReplyComposer thread={thread('a')} value="" onChange={onChange} onSend={onSend} notice={notice} />);
  await waitFor(() => expect(screen.getByRole('textbox')).toHaveFocus());
  expect(onChange).not.toHaveBeenCalled();
  expect(onSend).not.toHaveBeenCalled();
});

it('keeps recovery visible after offline failure and only retries on a second confirmation', async () => {
  const draft = state.current;
  draft.clear = vi.fn().mockRejectedValueOnce(new Error('Entwurfdienst offline')).mockResolvedValue(undefined);
  const { onSend } = show();
  fireEvent.click(screen.getByRole('button', { name: 'Entwurf verwerfen' }));
  fireEvent.click(screen.getByRole('button', { name: 'Endgültig verwerfen' }));
  expect(await screen.findByText('Entwurfdienst offline')).toHaveAttribute('role', 'alert');
  expect(screen.getByText('Nicht gesendeter Privattext')).toBeInTheDocument();
  expect(screen.getByRole('group', { name: 'Entwurf verwerfen bestätigen' })).toBeInTheDocument();
  expect(draft.clear).toHaveBeenCalledTimes(1);
  expect(draft.retry).not.toHaveBeenCalled();
  expect(onSend).not.toHaveBeenCalled();

  await act(async () => { fireEvent.click(screen.getByRole('button', { name: 'Endgültig verwerfen' })); });
  expect(draft.clear).toHaveBeenCalledTimes(2);
  expect(screen.queryByRole('group', { name: 'Entwurf verwerfen bestätigen' })).not.toBeInTheDocument();
  expect(screen.queryByText('Entwurfdienst offline')).not.toBeInTheDocument();
});

it('ignores a previous thread deletion result rather than mutating the newly opened composer', async () => {
  let finish;
  const draftA = state.current;
  draftA.clear = vi.fn(() => new Promise(resolve => { finish = resolve; }));
  const onChange = vi.fn(), onSend = vi.fn();
  const { rerender } = show({ onChange, onSend });
  fireEvent.click(screen.getByRole('button', { name: 'Entwurf verwerfen' }));
  fireEvent.click(screen.getByRole('button', { name: 'Endgültig verwerfen' }));
  expect(draftA.clear).toHaveBeenCalledTimes(1);
  const draftB = makeDraft('b', 'Antwortentwurf B');
  state.current = draftB;
  rerender(<InternalReplyComposer thread={thread('b')} value="Text B"
    onChange={onChange} onSend={onSend} notice={notice} />);
  expect(screen.getByText('Antwortentwurf B')).toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Entwurf verwerfen' })).toBeEnabled();
  await act(async () => finish());
  expect(screen.getByText('Antwortentwurf B')).toBeInTheDocument();
  expect(screen.queryByRole('group', { name: 'Entwurf verwerfen bestätigen' })).not.toBeInTheDocument();
  expect(draftB.clear).not.toHaveBeenCalled();
  expect(onChange).not.toHaveBeenCalled();
  expect(onSend).not.toHaveBeenCalled();
});

it('blocks destructive actions while the message send is uncertain or still pending', () => {
  const onSend = vi.fn();
  const { rerender } = show({ onSend, notice: { ...notice, uncertain: true }, value: 'Noch unbestätigt' });
  expect(screen.getByRole('button', { name: 'Entwurf verwerfen' })).toBeDisabled();
  expect(screen.getByRole('button', { name: 'Entwurf übernehmen' })).toBeDisabled();
  expect(screen.getByRole('button', { name: 'Senden' })).toBeDisabled();
  fireEvent.keyDown(screen.getByRole('textbox'), { key: 'Enter', ctrlKey: true });
  expect(onSend).not.toHaveBeenCalled();
  rerender(<InternalReplyComposer thread={thread('a')} value="Noch unbestätigt"
    onChange={vi.fn()} onSend={onSend} notice={{ ...notice, sending: true }} />);
  expect(screen.getByRole('button', { name: 'Entwurf verwerfen' })).toBeDisabled();
  expect(screen.getByRole('button', { name: 'Wird gespeichert …' })).toBeDisabled();
  expect(state.current.clear).not.toHaveBeenCalled();
});

it('retains explicit comparison before restoring the private reply', async () => {
  const draft = state.current;
  const { onChange } = show();
  fireEvent.click(screen.getByRole('button', { name: 'Entwurf übernehmen' }));
  await waitFor(() => expect(draft.recover).toHaveBeenCalledWith(draft.recovery.values));
  expect(draft.compare).toHaveBeenCalledOnce();
  expect(onChange).toHaveBeenCalledWith('Nicht gesendeter Privattext');
  expect(draft.clear).not.toHaveBeenCalled();
});

it('prevents an old recovery result from changing a different conversation', async () => {
  let resolveComparison;
  const draftA = state.current;
  draftA.compare = vi.fn(() => new Promise(resolve => { resolveComparison = resolve; }));
  const onChange = vi.fn(), onSend = vi.fn();
  const { rerender } = show({ onChange, onSend });
  fireEvent.click(screen.getByRole('button', { name: 'Entwurf übernehmen' }));
  const draftB = makeDraft('b', 'B bleibt privat');
  state.current = draftB;
  rerender(<InternalReplyComposer thread={thread('b')} value="Aktuelle Eingabe B"
    onChange={onChange} onSend={onSend} notice={notice} />);
  await act(async () => resolveComparison());
  expect(draftA.recover).not.toHaveBeenCalled();
  expect(onChange).not.toHaveBeenCalled();
  expect(screen.getByText('B bleibt privat')).toBeInTheDocument();
  expect(screen.getByRole('textbox')).toHaveValue('Aktuelle Eingabe B');
});

it('continues using the completed-send cleanup only after confirmed delivery', async () => {
  const draft = { ...state.current, recovery: null, status: 'ready' };
  state.current = draft;
  const { onSend } = show({ value: '', notice: { ...notice, saved: true } });
  await waitFor(() => expect(draft.clear).toHaveBeenCalledWith({ completed: true }));
  expect(onSend).not.toHaveBeenCalled();
});

it.each([
  ['de-DE', de], ['en-US', en], ['es-ES', es],
])('uses the current %s labels for the destructive confirmation', (locale, catalog) => {
  state.locale = locale;
  show();
  const discard = screen.getByRole('button', { name: catalog.ui.form.discardDraft });
  fireEvent.click(discard);
  const group = screen.getByRole('group', { name: catalog.ui.form.confirmRecoveredDiscard });
  expect(group).toHaveTextContent(catalog.ui.form.recoveredDiscardWarning);
  expect(within(group).getByRole('button', { name: catalog.ui.form.keepRecoveredDraft })).toBeInTheDocument();
  expect(within(group).getByRole('button', { name: catalog.ui.form.discardRecoveredDraft })).toBeInTheDocument();
});
