import { afterEach, describe, it, expect, vi } from 'vitest';
import { useEffect } from 'react';
import { render, act, cleanup, fireEvent, screen, within } from '@testing-library/react';
import { ToastProvider, useToast } from '../components/Toast';

afterEach(() => { cleanup(); vi.useRealTimers(); });

describe('useToast', () => {
  it('keeps the same object when a toast is shown', () => {
    // Regression: a new object per render re-ran effects that depend on it; a refused request
    // whose error toast re-rendered the page then repeated itself endlessly (settings, non-admins).
    let runs = 0;
    function Probe() {
      const toast = useToast();
      useEffect(() => { runs += 1; }, [toast]);
      return <button onClick={() => toast.error('x')}>show</button>;
    }
    const { getByText } = render(<ToastProvider><Probe /></ToastProvider>);
    act(() => { getByText('show').click(); });
    act(() => { getByText('show').click(); });
    expect(runs).toBe(1);
  });
});


function ToastActions() {
  const toast = useToast();
  return <>
    <button onClick={() => toast.error('Verbindung fehlgeschlagen – Bitte erneut prüfen')}>Fehler zeigen</button>
    <button onClick={() => toast.success('Gespeichert')}>Erfolg zeigen</button>
  </>;
}

describe('Benachrichtigungen im Arbeitsalltag', () => {
  it('kennzeichnet Fehler und bietet eine echte Schließen-Schaltfläche', () => {
    render(<ToastProvider><ToastActions /></ToastProvider>);
    fireEvent.click(screen.getByRole('button', { name: 'Fehler zeigen' }));
    const error = screen.getByRole('alert');
    expect(error).toHaveTextContent('Verbindung fehlgeschlagen');
    const dismiss = within(error).getByRole('button', { name: 'Meldung schließen' });
    dismiss.focus();
    expect(dismiss).toHaveFocus();
    fireEvent.click(dismiss);
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });

  it('zeigt maximal fünf gleichzeitige Meldungen, ohne den Arbeitsplatz zu überdecken', () => {
    let count = 0;
    function Many() {
      const toast = useToast();
      return <button onClick={() => toast.info(`Status ${++count}`)}>Weitere Meldung</button>;
    }
    render(<ToastProvider><Many /></ToastProvider>);
    for (let index = 0; index < 7; index++) {
      fireEvent.click(screen.getByRole('button', { name: 'Weitere Meldung' }));
    }
    const messages = screen.getAllByRole('status');
    expect(messages).toHaveLength(5);
    expect(screen.queryByText('Status 1')).not.toBeInTheDocument();
    expect(screen.queryByText('Status 2')).not.toBeInTheDocument();
    expect(screen.getByText('Status 7')).toBeInTheDocument();
  });

  it('pausiert das Ausblenden während des Lesens mit Maus und Tastatur', () => {
    vi.useFakeTimers();
    render(<ToastProvider><ToastActions /></ToastProvider>);
    fireEvent.click(screen.getByRole('button', { name: 'Fehler zeigen' }));
    let alert = screen.getByRole('alert');
    act(() => vi.advanceTimersByTime(2000));
    fireEvent.mouseEnter(alert);
    act(() => vi.advanceTimersByTime(10000));
    expect(screen.getByRole('alert')).toBeInTheDocument();
    fireEvent.mouseLeave(alert);
    act(() => vi.advanceTimersByTime(3999));
    expect(screen.getByRole('alert')).toBeInTheDocument();
    act(() => vi.advanceTimersByTime(1));
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'Erfolg zeigen' }));
    alert = screen.getByRole('status');
    const dismiss = within(alert).getByRole('button', { name: 'Meldung schließen' });
    fireEvent.focus(dismiss);
    act(() => vi.advanceTimersByTime(10000));
    expect(screen.getByRole('status')).toBeInTheDocument();
    fireEvent.blur(dismiss, { relatedTarget: null });
    act(() => vi.advanceTimersByTime(4000));
    expect(screen.queryByRole('status')).not.toBeInTheDocument();
  });

  it('beendet ausstehende Zeitgeber, wenn der Benachrichtigungsbereich entfernt wird', () => {
    vi.useFakeTimers();
    const { unmount } = render(<ToastProvider><ToastActions /></ToastProvider>);
    fireEvent.click(screen.getByRole('button', { name: 'Fehler zeigen' }));
    expect(vi.getTimerCount()).toBeGreaterThan(0);
    unmount();
    expect(vi.getTimerCount()).toBe(0);
  });
});
