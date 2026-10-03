import { useState } from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { TenancyWorkflowPreparationPanel } from '../pages/TenancyWorkflows';

function Harness() {
  const [open, setOpen] = useState(true);
  const [active, setActive] = useState(false);
  const [draft, setDraft] = useState('vorbereitet');

  return (
    <>
      <TenancyWorkflowPreparationPanel
        open={open}
        onToggle={() => setOpen(current => !current)}
        hasActiveChange={active}
        contextLabel="Haus B · Wohnung 2. OG"
      >
        <label>
          Interner Testentwurf
          <input
            aria-label="Interner Testentwurf"
            value={draft}
            onChange={event => setDraft(event.target.value)}
          />
        </label>
        <button type="button" onClick={() => {
          setActive(true);
          setOpen(false);
        }}>
          Erfolg bestätigen
        </button>
        <button type="button">Unverändert erneut senden</button>
      </TenancyWorkflowPreparationPanel>
    </>
  );
}

describe('TenancyWorkflowPreparationPanel', () => {
  it('becomes compact after confirmed success and reopens the same mounted preparation', () => {
    render(<Harness />);

    const draft = screen.getByLabelText('Interner Testentwurf');
    fireEvent.change(draft, { target: { value: 'bleibt gemountet' } });
    fireEvent.click(screen.getByRole('button', { name: 'Erfolg bestätigen' }));

    const reopen = screen.getByRole('button', { name: /Weiteren Wechsel vorbereiten/ });
    expect(reopen).toHaveAttribute('aria-expanded', 'false');
    expect(screen.getByLabelText('Interner Testentwurf')).not.toBeVisible();

    fireEvent.click(reopen);
    expect(screen.getByRole('button', { name: 'Vorbereitung einklappen' }))
      .toHaveAttribute('aria-expanded', 'true');
    expect(screen.getByLabelText('Interner Testentwurf')).toBeVisible();
    expect(screen.getByLabelText('Interner Testentwurf')).toHaveValue('bleibt gemountet');
  });

  it('keeps an unknown-reply retry visible because no success collapse occurs', () => {
    render(<Harness />);

    const retry = screen.getByRole('button', { name: 'Unverändert erneut senden' });
    expect(retry).toBeVisible();
    expect(screen.getByRole('button', { name: 'Vorbereitung einklappen' }))
      .toHaveAttribute('aria-expanded', 'true');
    expect(screen.getByLabelText('Interner Testentwurf')).toBeVisible();
  });

  it('exposes the selected property/unit context on the compact action', () => {
    render(<Harness />);
    fireEvent.click(screen.getByRole('button', { name: 'Erfolg bestätigen' }));

    const compact = screen.getByRole('button', { name: /Weiteren Wechsel vorbereiten/ });
    expect(compact).toHaveTextContent('Haus B · Wohnung 2. OG');
  });
});
