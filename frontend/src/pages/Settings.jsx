import { usePreferences } from '../contexts/PreferencesContext';
import { useTranslation } from '../i18n';

export default function Settings() {
  const { prefs, toggleTheme, toggleSidebar, updatePrefs } = usePreferences();
  const { locale, setLocale } = useTranslation();

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
          <div className="panel-header">Daten</div>
          <div className="panel-body settings-section">
            <div className="settings-row">
              <label>Datenbank</label>
              <div className="settings-control">
                <span className="text-muted">Lokal (SQLite / In-Memory)</span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
