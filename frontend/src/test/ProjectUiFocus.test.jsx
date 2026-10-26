import { cleanup, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { Modal } from '../features/maintenanceProject/ProjectUi';

vi.mock('../i18n', () => ({ useTranslation: () => ({ locale: 'de-DE' }) }));
afterEach(cleanup);

function show(children) {
  return render(<><button>Außerhalb davor</button><Modal title="E-Rechnung prüfen" onClose={vi.fn()}>{children}</Modal><button>Außerhalb danach</button></>);
}

describe('project modal keyboard boundaries', () => {
  it('wraps Shift+Tab to the visible summary and Tab back to close when details are collapsed', async () => {
    const user = userEvent.setup();
    show(<><button>Original herunterladen</button><details><summary>Begründete Ausnahme</summary>
      <label><input type="checkbox" />Bekannte Dublette</label></details><button disabled>Übernehmen</button></>);
    const close = screen.getByRole('button', { name: 'Schließen' });
    const summary = screen.getByText('Begründete Ausnahme');
    expect(close).toHaveFocus();
    await user.tab({ shift: true });
    expect(summary).toHaveFocus();
    await user.tab();
    expect(close).toHaveFocus();
    // user-event/jsdom does not implement native summary tab stops. Browser QA
    // verifies the whole cycle; here check the trap at each native boundary.
    summary.focus();
    await user.tab();
    expect(close).toHaveFocus();
  });

  it('includes the checkbox after expanding details and recomputes the boundary after collapsing', async () => {
    const user = userEvent.setup();
    show(<details><summary>Begründete Ausnahme</summary><label><input type="checkbox" />Bekannte Dublette</label></details>);
    const close = screen.getByRole('button', { name: 'Schließen' });
    const summary = screen.getByText('Begründete Ausnahme');
    await user.click(summary);
    expect(summary.parentElement).toHaveAttribute('open');
    close.focus();
    await user.tab({ shift: true });
    expect(screen.getByRole('checkbox')).toHaveFocus();
    await user.tab();
    expect(close).toHaveFocus();
    await user.click(summary);
    expect(summary.parentElement).not.toHaveAttribute('open');
    summary.focus();
    await user.tab();
    expect(close).toHaveFocus();
    await user.tab({ shift: true });
    expect(summary).toHaveFocus();
  });

  it('excludes hidden, inert, disabled and negative-tabindex controls, including hidden wrappers', async () => {
    const user = userEvent.setup();
    show(<><button>Letzte sichtbare Aktion</button><input type="hidden" />
      <button disabled>Deaktiviert</button><fieldset disabled><button>Gesperrtes Feld</button></fieldset>
      <button tabIndex={-1}>Nur programmatisch</button><div hidden><button>Verborgen</button></div>
      <div inert><button>Inaktiv</button></div><div aria-hidden="true"><button>Ausgeblendet</button></div>
      <div style={{ display: 'none' }}><button>Kein Layout</button></div>
      <div style={{ visibility: 'hidden' }}><button>Unsichtbar</button></div>
      <details><summary hidden>Verborgener Abschnitt</summary><button>Verborgene Details</button></details></>);
    const close = screen.getByRole('button', { name: 'Schließen' });
    await user.tab({ shift: true });
    expect(screen.getByRole('button', { name: 'Letzte sichtbare Aktion' })).toHaveFocus();
    await user.tab();
    expect(close).toHaveFocus();
  });
});
