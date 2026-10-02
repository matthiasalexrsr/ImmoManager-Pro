import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { ConfirmProvider, useConfirm } from '../components/ConfirmDialog';
import de from '../../../i18n/de-DE.json';

vi.mock('../i18n', () => ({ useTranslation: () => ({
  t: key => key.split('.').reduce((value, part) => value?.[part], de) || key,
}) }));

function PaymentDraft({ decision }) {
  const confirm = useConfirm();
  return <form aria-label="Auszahlungsentwurf">
    <input aria-label="Entwurfsnotiz" defaultValue="Vorhandener Entwurf" />
    <button type="button" onClick={async () => decision(await confirm('Die bereits erfolgte Auszahlung belegen?'))}>Erfassen</button>
  </form>;
}

describe('explicit action confirmation', () => {
  it('has a neutral action title, understandable button and trapped keyboard focus', async () => {
    const decision = vi.fn();
    render(<ConfirmProvider><PaymentDraft decision={decision} /></ConfirmProvider>);
    fireEvent.click(screen.getByRole('button', { name: 'Erfassen' }));
    const dialog = await screen.findByRole('alertdialog', { name: 'Vorgang bestätigen' });
    const confirm = screen.getByRole('button', { name: 'Bestätigen' });
    expect(dialog).toHaveTextContent('Die bereits erfolgte Auszahlung belegen?');
    expect(confirm).toHaveFocus();
    fireEvent.keyDown(document, { key: 'Tab' });
    expect(screen.getByRole('button', { name: 'Abbrechen' })).toHaveFocus();
    fireEvent.keyDown(document, { key: 'Tab', shiftKey: true });
    expect(confirm).toHaveFocus();
    fireEvent.click(confirm);
    await vi.waitFor(() => expect(decision).toHaveBeenCalledWith(true));
  });

  it('Escape cancels only confirmation, retains the draft and never confirms', async () => {
    const decision = vi.fn();
    render(<ConfirmProvider><PaymentDraft decision={decision} /></ConfirmProvider>);
    screen.getByRole('button', { name: 'Erfassen' }).focus();
    fireEvent.click(screen.getByRole('button', { name: 'Erfassen' }));
    await screen.findByRole('alertdialog');
    const parentEscape = vi.fn();
    document.addEventListener('keydown', parentEscape);
    try {
      fireEvent.keyDown(document, { key: 'Escape' });
      await vi.waitFor(() => expect(decision).toHaveBeenCalledWith(false));
      expect(parentEscape).not.toHaveBeenCalled();
      expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument();
      expect(screen.getByLabelText('Entwurfsnotiz')).toHaveValue('Vorhandener Entwurf');
      expect(screen.getByRole('button', { name: 'Erfassen' })).toHaveFocus();
    } finally {
      document.removeEventListener('keydown', parentEscape);
    }
  });
});
