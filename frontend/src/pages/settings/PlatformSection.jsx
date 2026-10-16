import { useCallback, useEffect, useRef, useState } from 'react';
import { api } from '../../api';

export default function PlatformSection() {
  const [data, setData] = useState(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState('');
  const pending = useRef(null);
  const load = useCallback(async () => {
    const current = api.captureSession();
    try {
      const result = await api.get('/admin/operations/platform');
      if (!result?.storage || !result?.portable_export || !Array.isArray(result.plugins)) throw new Error('Unvollständige Betriebsantwort. Bitte erneut laden.');
      current(); setData(result); setError('');
    } catch (err) {
      try { current(); } catch { return; }
      setError(err.message || 'Betriebsdaten konnten nicht geladen werden.');
    }
  }, []);
  useEffect(() => { load(); }, [load]);
  const change = async (plugin, operation, backupRevision = null) => {
    const current = api.captureSession();
    const intent = `${plugin.name}:${plugin.revision}:${operation}:${backupRevision}`;
    if (pending.current?.intent !== intent) {
      pending.current = { intent, body: { operation, expected_revision: plugin.revision,
        idempotency_key: crypto.randomUUID(), backup_revision: backupRevision } };
    }
    setBusy(true); setError(''); setMessage('');
    try {
      const result = await api.post(`/admin/operations/plugins/${encodeURIComponent(plugin.name)}`, pending.current.body);
      current(); pending.current = null;
      setMessage(`${plugin.name}: Stand ${result.revision} gespeichert. Programm vor weiterer Pluginverwendung neu starten.`);
      await load();
    } catch (err) {
      try { current(); } catch { return; }
      setError(`${err.message || 'Änderung fehlgeschlagen.'} Bei unklarem Ausgang dieselbe Aktion erneut versuchen.`);
    } finally {
      try { current(); setBusy(false); } catch { /* Account changed: discard this response. */ }
    }
  };
  return <section aria-label="Speicher und Plugins" style={{ padding: '1rem', overflowWrap: 'anywhere', minWidth: 0 }}>
    <h3>Speicher und Plugins</h3>
    <p>Plugins führen vertrauenswürdigen Python-Code im Programmprozess aus. Sie sind nicht isoliert. Nur geprüfte Pakete installieren.</p>
    {error && <p role="alert">{error}</p>}
    {message && <p role="status">{message}</p>}
    <button type="button" className="btn btn-secondary" disabled={busy} onClick={load}>Stand neu laden</button>
    {data && <>
      <p>Originalspeicher: <strong>{data.storage.backend === 's3' ? 'S3-kompatibler Speicher' : 'Lokaler Speicher'}</strong> · Konfiguration: {data.storage.origin}</p>
      <p>{data.portable_export.passphrase_configured
        ? 'Passphrase für den geschützten Runtime-Export ist eingerichtet.'
        : 'Für portable Vollsicherungen muss eine Backup-Passphrase in der Installation eingerichtet werden.'}</p>
      <p>Eine Datenprüfung bestätigt noch keine erfolgreiche Anmeldung oder Browserprüfung nach der Wiederherstellung.</p>
      {data.plugins.length === 0 && <p>Keine kompatiblen Pluginpakete geladen.</p>}
      {(data.plugin_errors || []).map(item => <p role="alert" key={item.package}>
        Plugin {item.package}: {item.status === 'directory_missing' ? 'Paketverzeichnis fehlt.' : 'Paket ist unvollständig oder nicht kompatibel.'} Bitte Paketdeklaration und Prüfsummen prüfen.
      </p>)}
      {data.plugins.map(plugin => <article key={plugin.name} style={{ borderTop: '1px solid var(--border)', paddingBlock: '.75rem' }}>
        <strong>{plugin.name}</strong> · Paket {plugin.version} · installiert {plugin.installed_version || 'noch nicht'} · Revision {plugin.revision}
        <p>Status: {plugin.enabled ? 'Freigegeben' : 'Deaktiviert'} · Datenstruktur {plugin.declaration.schema_version}</p>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: '.5rem' }}>
          <button type="button" className="btn btn-primary" disabled={busy} onClick={() => change(plugin, 'upgrade')}>Paket geprüft übernehmen</button>
          <button type="button" className="btn btn-secondary" disabled={busy || !plugin.enabled} onClick={() => change(plugin, 'uninstall')}>Deaktivieren und Daten sichern</button>
          {plugin.backup_revisions.map(revision => <button type="button" className="btn btn-secondary" disabled={busy} key={revision}
            onClick={() => change(plugin, 'restore', revision)}>Datenstand {revision} wiederherstellen</button>)}
        </div>
      </article>)}
    </>}
  </section>;
}
