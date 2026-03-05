import { useState, useRef } from 'react';
import { usePreferences } from '../contexts/PreferencesContext';
import { useTranslation } from '../i18n';
import { api } from '../api';

const BASE = (import.meta.env.VITE_API_URL || '/api/v1');

export default function Settings() {
  const { prefs, toggleTheme, toggleSidebar, updatePrefs } = usePreferences();
  const { locale, setLocale } = useTranslation();
  const [exportLoading, setExportLoading] = useState(false);
  const [importLoading, setImportLoading] = useState(false);
  const [importResult, setImportResult] = useState(null);
  const fileRef = useRef(null);

  const handleExport = async () => {
    setExportLoading(true);
    try {
      const token = localStorage.getItem('access_token');
      const res = await fetch(`${BASE}/data/export`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `immomanager_export_${new Date().toISOString().slice(0, 10)}.json`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (err) {
      console.warn('[Settings] export:', err.message);
    } finally {
      setExportLoading(false);
    }
  };

  const handleImport = async (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setImportLoading(true);
    setImportResult(null);
    try {
      const formData = new FormData();
      formData.append('file', file);
      const token = localStorage.getItem('access_token');
      const res = await fetch(`${BASE}/data/import`, {
        method: 'POST',
        body: formData,
        headers: { Authorization: `Bearer ${token}` },
      });
      const data = await res.json();
      setImportResult(data);
    } catch (err) {
      setImportResult({ errors: { general: [err.message] } });
    } finally {
      setImportLoading(false);
      if (fileRef.current) fileRef.current.value = '';
    }
  };

  return (
    <div className="page">
      <h1 className="page-title">Einstellungen</h1>
      <div className="settings-grid">
        <div className="panel">
          <div className="panel-header">Darstellung</div>
          <div className="panel-body settings-section">
            <div className="settings-row">
              <label>Theme</label>
              <div className="settings-control">
                <button
                  className={`btn btn-sm ${prefs.theme === 'light' ? 'btn-primary' : 'btn-secondary'}`}
                  onClick={() => prefs.theme !== 'light' && toggleTheme()}
                >Hell</button>
                <button
                  className={`btn btn-sm ${prefs.theme === 'dark' ? 'btn-primary' : 'btn-secondary'}`}
                  onClick={() => prefs.theme !== 'dark' && toggleTheme()}
                >Dunkel</button>
              </div>
            </div>
            <div className="settings-row">
              <label>Sidebar</label>
              <div className="settings-control">
                <button className="btn btn-sm btn-secondary" onClick={toggleSidebar}>
                  {prefs.sidebar_collapsed ? 'Einblenden' : 'Ausblenden'}
                </button>
              </div>
            </div>
            <div className="settings-row">
              <label>Sprache</label>
              <div className="settings-control">
                {['de-DE', 'en-US', 'es-ES'].map(loc => (
                  <button
                    key={loc}
                    className={`btn btn-sm ${locale === loc ? 'btn-primary' : 'btn-secondary'}`}
                    onClick={() => setLocale(loc)}
                  >{loc.slice(0, 2).toUpperCase()}</button>
                ))}
              </div>
            </div>
          </div>
        </div>

        <div className="panel">
          <div className="panel-header">Tabellen</div>
          <div className="panel-body settings-section">
            <div className="settings-row">
              <label>Einträge pro Seite</label>
              <div className="settings-control">
                <select
                  value={prefs.items_per_page || 25}
                  onChange={e => updatePrefs({ items_per_page: Number(e.target.value) })}
                  className="page-size-select"
                >
                  <option value={10}>10</option>
                  <option value={25}>25</option>
                  <option value={50}>50</option>
                  <option value={100}>100</option>
                </select>
              </div>
            </div>
            <div className="settings-row">
              <label>Datumsformat</label>
              <div className="settings-control">
                <select
                  value={prefs.date_format || 'DD.MM.YYYY'}
                  onChange={e => updatePrefs({ date_format: e.target.value })}
                  className="page-size-select"
                >
                  <option value="DD.MM.YYYY">DD.MM.YYYY</option>
                  <option value="YYYY-MM-DD">YYYY-MM-DD</option>
                  <option value="MM/DD/YYYY">MM/DD/YYYY</option>
                </select>
              </div>
            </div>
            <div className="settings-row">
              <label>Währung</label>
              <div className="settings-control">
                <select
                  value={prefs.currency || 'EUR'}
                  onChange={e => updatePrefs({ currency: e.target.value })}
                  className="page-size-select"
                >
                  <option value="EUR">Euro (€)</option>
                  <option value="CHF">CHF (Fr.)</option>
                  <option value="USD">USD ($)</option>
                </select>
              </div>
            </div>
          </div>
        </div>

        <div className="panel">
          <div className="panel-header">Benachrichtigungen</div>
          <div className="panel-body settings-section">
            <div className="settings-row">
              <label>E-Mail-Benachrichtigungen</label>
              <div className="settings-control">
                <select
                  value={prefs.email_notifications || 'important'}
                  onChange={e => updatePrefs({ email_notifications: e.target.value })}
                  className="page-size-select"
                >
                  <option value="all">Alle</option>
                  <option value="important">Nur wichtige</option>
                  <option value="none">Keine</option>
                </select>
              </div>
            </div>
            <div className="settings-row">
              <label>Erinnerungen</label>
              <div className="settings-control">
                <select
                  value={prefs.reminder_days || '7'}
                  onChange={e => updatePrefs({ reminder_days: e.target.value })}
                  className="page-size-select"
                >
                  <option value="3">3 Tage vorher</option>
                  <option value="7">7 Tage vorher</option>
                  <option value="14">14 Tage vorher</option>
                  <option value="30">30 Tage vorher</option>
                </select>
              </div>
            </div>
          </div>
        </div>

        <div className="panel">
          <div className="panel-header">Daten & Sicherung</div>
          <div className="panel-body settings-section">
            <div className="settings-row">
              <label>Datenbank</label>
              <div className="settings-control">
                <span className="text-muted">SQLite (Persistent)</span>
              </div>
            </div>
            <div className="settings-row">
              <label>Daten exportieren</label>
              <div className="settings-control">
                <button
                  className="btn btn-sm btn-secondary"
                  onClick={handleExport}
                  disabled={exportLoading}
                >
                  {exportLoading ? 'Exportiere...' : 'JSON-Export'}
                </button>
              </div>
            </div>
            <div className="settings-row">
              <label>Daten importieren</label>
              <div className="settings-control">
                <input
                  ref={fileRef}
                  type="file"
                  accept=".json"
                  onChange={handleImport}
                  disabled={importLoading}
                  style={{ fontSize: '0.85rem' }}
                />
              </div>
            </div>
            {importResult && (
              <div className="settings-row">
                <label>Import-Ergebnis</label>
                <div className="settings-control" style={{ flexDirection: 'column', alignItems: 'flex-start' }}>
                  {importResult.imported && Object.entries(importResult.imported).map(([k, v]) => (
                    <span key={k} className="text-muted">{k}: {v} importiert</span>
                  ))}
                  {importResult.errors && Object.keys(importResult.errors).length > 0 && (
                    <span style={{ color: 'var(--danger)' }}>
                      Fehler in: {Object.keys(importResult.errors).join(', ')}
                    </span>
                  )}
                </div>
              </div>
            )}
          </div>
        </div>

        <div className="panel">
          <div className="panel-header">Dokumente & OCR</div>
          <div className="panel-body settings-section">
            <div className="settings-row">
              <label>Automatische OCR</label>
              <div className="settings-control">
                <span className="text-muted">Aktiv (für PDF, PNG, JPG, TIFF)</span>
              </div>
            </div>
            <div className="settings-row">
              <label>OCR-Sprachen</label>
              <div className="settings-control">
                <span className="text-muted">Deutsch + Englisch</span>
              </div>
            </div>
            <div className="settings-row">
              <label>Dateispeicher</label>
              <div className="settings-control">
                <span className="text-muted">Lokal (uploads/)</span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
