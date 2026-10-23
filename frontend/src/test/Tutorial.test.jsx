import { describe, it, expect, beforeEach, vi } from 'vitest';
import { useEffect } from 'react';
import { render, screen, fireEvent, act } from '@testing-library/react';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';
import { AuthProvider, useAuth } from '../contexts/AuthContext';
import { TutorialProvider, useTutorial } from '../components/Tutorial';

vi.mock('../api', () => ({ api: { get: vi.fn(() => Promise.resolve({ write: null })) } }));

const STEPS = [
  { route: '/', title: 'Willkommen' },
  { route: '/tenants', target: ['#missing'], title: 'Mieter' },
  { route: '/', title: 'Fertig' },
];

function SignedIn({ children }) {
  const { updateUser } = useAuth();
  useEffect(() => { updateUser({ id: 'u1', role: 'eigentuemer' }); }, [updateUser]);
  return children;
}

function Where() {
  return <div data-testid="where">{useLocation().pathname}</div>;
}

function Restart() {
  const { start } = useTutorial();
  return <button onClick={() => start(0)}>Hilfe</button>;
}

function renderApp() {
  return render(
    <MemoryRouter initialEntries={['/']}>
      <AuthProvider>
        <SignedIn>
          <TutorialProvider steps={STEPS}>
            <Routes><Route path="*" element={<Where />} /></Routes>
            <Restart />
          </TutorialProvider>
        </SignedIn>
      </AuthProvider>
    </MemoryRouter>,
  );
}

describe('Tutorial', () => {
  beforeEach(() => localStorage.clear());

  it('offers the tour once to a new user and walks through the steps', async () => {
    renderApp();
    expect(await screen.findByText('Kurze Tour durch ImmoManager Pro?')).toBeTruthy();

    fireEvent.click(screen.getByText('Tour starten'));
    expect(screen.getByText('Willkommen')).toBeTruthy();
    expect(screen.getByText('Schritt 1 von 3')).toBeTruthy();

    act(() => { fireEvent.keyDown(window, { key: 'ArrowRight' }); });
    expect(screen.getByText('Mieter')).toBeTruthy();
    expect(screen.getByTestId('where').textContent).toBe('/tenants');   // the step opens its page

    act(() => { fireEvent.keyDown(window, { key: 'ArrowLeft' }); });
    expect(screen.getByText('Willkommen')).toBeTruthy();

    act(() => { fireEvent.keyDown(window, { key: 'Escape' }); });
    expect(screen.queryByText('Willkommen')).toBeNull();
    expect(JSON.parse(localStorage.getItem('immo.tutorial.u1')).offered).toBe(true);
  });

  it('does not ask again, but starts from the help button', async () => {
    localStorage.setItem('immo.tutorial.u1', JSON.stringify({ offered: true }));
    renderApp();
    await act(async () => {});
    expect(screen.queryByText('Kurze Tour durch ImmoManager Pro?')).toBeNull();

    fireEvent.click(screen.getByText('Hilfe'));
    expect(screen.getByText('Willkommen')).toBeTruthy();
    fireEvent.click(screen.getByText('Weiter'));
    fireEvent.click(screen.getByText('Weiter'));
    fireEvent.click(screen.getByText('Fertig', { selector: 'button' }));
    expect(screen.queryByText('Schritt 3 von 3')).toBeNull();
    expect(JSON.parse(localStorage.getItem('immo.tutorial.u1')).finished).toBe(true);
  });
});
