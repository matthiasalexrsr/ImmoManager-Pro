import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import MoreMenu from '../components/MoreMenu';

afterEach(cleanup);

describe('"Mehr" menu', () => {
  it('explains each rarely used entry and closes after choosing or with Escape', () => {
    const open = vi.fn();
    render(<MemoryRouter><MoreMenu items={[
      { key: 'a', label: 'Aktenwerk …', description: 'Belege an ein DMS übergeben.', onSelect: open },
      { key: 't', label: 'TEHA-Empfang', description: 'Daten des Messdienstes.', to: '/teha' },
      null,
    ]} /></MemoryRouter>);
    const toggle = screen.getByRole('button', { name: 'Mehr' });
    expect(toggle).toHaveAttribute('aria-expanded', 'false');
    fireEvent.click(toggle);
    expect(toggle).toHaveAttribute('aria-expanded', 'true');
    expect(screen.getByRole('button', { name: /Aktenwerk …\s*Belege an ein DMS übergeben\./ })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /TEHA-Empfang/ })).toHaveAttribute('href', '/teha');
    fireEvent.click(screen.getByRole('button', { name: /Aktenwerk/ }));
    expect(open).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole('list', { name: 'Mehr' })).toBeNull();
    fireEvent.click(toggle);
    fireEvent.keyDown(document, { key: 'Escape' });
    expect(screen.queryByRole('list', { name: 'Mehr' })).toBeNull();
    expect(toggle).toHaveFocus();
  });

  it('shows nothing without entries', () => {
    const { container } = render(<MemoryRouter><MoreMenu items={[]} /></MemoryRouter>);
    expect(container).toBeEmptyDOMElement();
  });
});
