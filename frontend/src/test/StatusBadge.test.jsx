import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import StatusBadge from '../components/StatusBadge';

const TEXTS = { 'status.badge.finalized': 'Abgeschlossen', 'status.badge.overdue': 'Überfällig' };
vi.mock('../i18n', () => ({ useTranslation: () => ({ t: key => TEXTS[key] ?? key }) }));

describe('StatusBadge', () => {
  it('shows the translated word instead of the stored code', () => {
    // Regression: badges showed "finalized", "overdue", "active" in the German UI.
    render(<><StatusBadge status="finalized" /><StatusBadge status="OVERDUE" /></>);

    expect(screen.getByText('Abgeschlossen')).toHaveClass('badge-green');
    expect(screen.getByText('Überfällig')).toHaveClass('badge-red');
  });

  it('keeps unknown statuses as they are', () => {
    render(<StatusBadge status="Sonderfall" />);

    expect(screen.getByText('Sonderfall')).toHaveClass('badge-gray');
  });
});
