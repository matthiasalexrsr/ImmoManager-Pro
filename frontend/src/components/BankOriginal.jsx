import { useEffect, useRef, useState } from 'react';
import { api } from '../api';
import { bankOriginalPath } from '../utils/bankOriginal';

export default function BankOriginal({ value }) {
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const mounted = useRef(true);
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);
  const download = async () => {
    const current = api.captureSession(); setBusy(true); setError('');
    try {
      const blob = await api.getBlob(bankOriginalPath(value)); current();
      if (!mounted.current) return;
      const url = URL.createObjectURL(blob); const anchor = document.createElement('a');
      anchor.href = url; anchor.download = 'Bankoriginal.bin'; anchor.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (e) { if (mounted.current && e.code !== 'SESSION_CHANGED') setError(e.message); }
    finally { if (mounted.current) setBusy(false); }
  };
  return <span><button type="button" className="btn btn-sm btn-secondary" disabled={busy || !bankOriginalPath(value)} onClick={download}>Bankquelle herunterladen</button>{error && <span role="alert">{error}</span>}</span>;
}
