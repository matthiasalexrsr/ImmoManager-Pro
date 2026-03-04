import { NavLink, Outlet, useNavigate } from 'react-router-dom';
import { logout } from '../api';
import { useTranslation } from '../i18n';
import { usePreferences } from '../contexts/PreferencesContext';
import SearchBar from './SearchBar';
import NotificationBell from './NotificationBell';

const NAV = [
  { to: '/', labelKey: 'navigation.main.dashboard', icon: '\uD83D\uDCCA' },
  { to: '/portfolios', labelKey: 'navigation.main.portfolio', icon: '\uD83C\uDFE2' },
  { to: '/properties', labelKey: 'navigation.main.properties', icon: '\uD83C\uDFE0' },
  { to: '/units', labelKey: 'units.list.title', icon: '\uD83D\uDEAA' },
  { to: '/tenants', labelKey: 'tenantsContracts.tenants.title', icon: '\uD83D\uDC64' },
  { to: '/contracts', labelKey: 'tenantsContracts.contracts.title', icon: '\uD83D\uDCC4' },
  { to: '/accounts', labelKey: 'finance.accounts.title', icon: '\uD83C\uDFE6' },
  { to: '/bookings', labelKey: 'finance.bookings.title', icon: '\uD83D\uDCB6' },
  { to: '/invoices', labelKey: 'finance.invoices.title', icon: '\uD83E\uDDFE' },
  { to: '/maintenance', labelKey: 'navigation.main.maintenance', icon: '\uD83D\uDD27' },
  { to: '/tasks', labelKey: 'navigation.main.tasks', icon: '\u2705' },
  { to: '/documents', labelKey: 'navigation.main.documents', icon: '\uD83D\uDCC1' },
  { to: '/rent-overview', labelKey: 'navigation.main.rentOverview', icon: '\uD83D\uDCB0' },
  { to: '/meters', labelKey: 'navigation.main.meters', icon: '\uD83D\uDCA7' },
  { to: '/contacts', labelKey: 'navigation.main.contacts', icon: '\uD83D\uDCD5' },
  { to: '/statements', labelKey: 'navigation.main.statements', icon: '\uD83D\uDCCB' },
  { to: '/messages', labelKey: 'navigation.main.messages', icon: '\u2709' },
  { to: '/settings', labelKey: 'navigation.main.settings', icon: '\u2699' },
];

const LOCALES = [
  { code: 'de-DE', label: 'DE' },
  { code: 'en-US', label: 'EN' },
  { code: 'es-ES', label: 'ES' },
];

export default function Layout() {
  const navigate = useNavigate();
  const { t, locale, setLocale } = useTranslation();
  const { prefs, toggleTheme, toggleSidebar } = usePreferences();
  const collapsed = prefs.sidebar_collapsed;

  return (
    <div className={`app-layout ${collapsed ? 'sidebar-collapsed' : ''}`}>
      <aside className={`sidebar ${collapsed ? 'collapsed' : ''}`}>
        <div className="sidebar-header">
          <h1>{collapsed ? 'IM' : 'ImmoManager'}</h1>
          {!collapsed && <span className="subtitle">Pro</span>}
        </div>
        <nav>
          {NAV.map(({ to, labelKey, icon }) => (
            <NavLink key={to} to={to} className={({ isActive }) => isActive ? 'nav-link active' : 'nav-link'}>
              <span className="nav-icon">{icon}</span>
              {!collapsed && <span>{t(labelKey)}</span>}
            </NavLink>
          ))}
        </nav>
        <div className="sidebar-footer">
          <div className="sidebar-controls">
            <button onClick={toggleSidebar} className="sidebar-control-btn" title={collapsed ? 'Sidebar einblenden' : 'Sidebar ausblenden'}>
              {collapsed ? '\u25B6' : '\u25C0'}
            </button>
            <button onClick={toggleTheme} className="sidebar-control-btn" title="Theme wechseln">
              {prefs.theme === 'dark' ? '\u2600' : '\u263D'}
            </button>
            <div className="locale-switcher">
              {LOCALES.map(loc => (
                <button
                  key={loc.code}
                  className={`locale-btn ${locale === loc.code ? 'active' : ''}`}
                  onClick={() => setLocale(loc.code)}
                >
                  {loc.label}
                </button>
              ))}
            </div>
          </div>
          <button onClick={() => { logout(); navigate('/login'); }} className="btn-logout">
            {t('accountMenu.logout')}
          </button>
        </div>
      </aside>
      <main className="main-content">
        <div className="top-bar">
          <SearchBar />
          <NotificationBell />
        </div>
        <Outlet />
      </main>
    </div>
  );
}
