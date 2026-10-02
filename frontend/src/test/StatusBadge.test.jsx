import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import StatusBadge from '../components/StatusBadge';
import de from '../../../i18n/de-DE.json';
import en from '../../../i18n/en-US.json';
import es from '../../../i18n/es-ES.json';

const context = vi.hoisted(() => ({ locale: 'de' }));
const catalogs = { de, en, es };
vi.mock('../i18n', () => ({ useTranslation: () => ({ t: key => key.split('.').reduce((value, part) => value?.[part], catalogs[context.locale]) || key }) }));
beforeEach(() => { context.locale = 'de'; });

describe.each(Object.keys(catalogs))('status labels in %s', locale => {
  it.each([['ACTIVE', 'status.general.active'], [' partiallyPaid ', 'status.payment.partiallyPaid'], ['inReview', 'status.contract.inReview'], ['aktiv', 'status.general.active']])('translates %s using the explicit catalog key', (status, key) => {
    context.locale = locale;
    render(<StatusBadge status={status} />);
    const label = key.split('.').reduce((value, part) => value[part], catalogs[locale]);
    expect(screen.getByText(label)).toBeInTheDocument();
    expect(screen.queryByRole('status')).not.toBeInTheDocument();
    expect(screen.getByText(label).parentElement.querySelector('[aria-hidden="true"]')).toBeInTheDocument();
  });
});

it('keeps unknown status visible and avoids translation key leakage', () => {
  render(<StatusBadge status="  FutureStatus  " />);
  expect(screen.getByText('FutureStatus')).toBeInTheDocument();
  expect(screen.queryByText(/status\./)).not.toBeInTheDocument();
});

it.each([null, undefined, '', '   '])('renders no badge for an empty status (%s)', status => {
  const { container } = render(<StatusBadge status={status} />);
  expect(container).toBeEmptyDOMElement();
});
