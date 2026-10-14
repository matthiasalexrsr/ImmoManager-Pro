import { describe, it, expect } from 'vitest';
import { useEffect } from 'react';
import { render, act } from '@testing-library/react';
import { ToastProvider, useToast } from '../components/Toast';

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
