import { NavLink, Outlet, useNavigate } from 'react-router-dom';
import { logout } from '../api';
import { useTranslation } from '../i18n';
import { usePreferences } from '../contexts/PreferencesContext';
import SearchBar from './SearchBar';
import NotificationBell from './NotificationBell';
import {
  LayoutDashboard,
  Building2,
  Home,
  DoorOpen,
  Users,
  FileText,
  Landmark,
  Receipt,
  CreditCard,
  Wrench,
  CheckSquare,
  FolderOpen,
  Building,
  Sun,
  Moon,
  LogOut,
  PanelLeftClose,
  PanelLeftOpen,
} from 'lucide-react';

const NAV_SECTIONS = [
  {
    label: 'Übersicht',
    items: [
      { to: '/', labelKey: 'navigation.main.dashboard', icon: LayoutDashboard },
    ],
  },
  {
    label: 'Immobilien',
    items: [
      { to: '/portfolios', labelKey: 'navigation.main.portfolio', icon: Building2 },
      { to: '/properties', labelKey: 'navigation.main.properties', icon: Home },
      { to: '/units', labelKey: 'units.list.title', icon: DoorOpen },
    ],
  },
  {
    label: 'Mieter & Verträge',
    items: [
      { to: '/tenants', labelKey: 'tenantsContracts.tenants.title', icon: Users },
      { to: '/contracts', labelKey: 'tenantsContracts.contracts.title', icon: FileText },
    ],
  },
  {
    label: 'Finanzen',
    items: [
      { to: '/accounts', labelKey: 'finance.accounts.title', icon: Landmark },
      { to: '/bookings', labelKey: 'finance.bookings.title', icon: Receipt },
      { to: '/invoices', labelKey: 'finance.invoices.title', icon: CreditCard },
    ],
  },
  {
    label: 'Verwaltung',
    items: [
      { to: '/maintenance', labelKey: 'navigation.main.maintenance', icon: Wrench },
      { to: '/tasks', labelKey: 'navigation.main.tasks', icon: CheckSquare },
      { to: '/documents', labelKey: 'navigation.main.documents', icon: FolderOpen },
    ],
  },
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

  const handleLogout = () => {
    logout();
    navigate('/login');
  };

  return (
    <div className={`app-layout${collapsed ? ' sidebar-collapsed' : ''}`}>
      <aside className={`sidebar${collapsed ? ' collapsed' : ''}`}>
        {/* Sidebar Header */}
        <div className="sidebar-header">
          <div className="logo-icon">
            <Building size={collapsed ? 24 : 28} />
          </div>
          {!collapsed && (
            <div className="logo-text">
              <span className="logo-title">ImmoManager</span>
              <span className="logo-subtitle">PRO</span>
            </div>
          )}
        </div>

        {/* Sidebar Navigation */}
        <nav className="sidebar-nav">
          {NAV_SECTIONS.map((section) => (
            <div key={section.label} className="nav-section">
              {!collapsed && (
                <div className="nav-section-label">{section.label}</div>
              )}
              {section.items.map(({ to, labelKey, icon: Icon }) => (
                <NavLink
                  key={to}
                  to={to}
                  end={to === '/'}
                  className={({ isActive }) =>
                    `nav-link${isActive ? ' active' : ''}`
                  }
                  title={collapsed ? t(labelKey) : undefined}
                >
                  <span className="nav-icon">
                    <Icon size={20} />
                  </span>
                  {!collapsed && <span>{t(labelKey)}</span>}
                </NavLink>
              ))}
            </div>
          ))}
        </nav>

        {/* Sidebar Footer */}
        <div className="sidebar-footer">
          <div className="sidebar-controls">
            <button
              onClick={toggleSidebar}
              className="sidebar-control-btn"
              title={collapsed ? 'Sidebar einblenden' : 'Sidebar ausblenden'}
            >
              {collapsed ? (
                <PanelLeftOpen size={18} />
              ) : (
                <PanelLeftClose size={18} />
              )}
            </button>
            <button
              onClick={toggleTheme}
              className="sidebar-control-btn"
              title="Theme wechseln"
            >
              {prefs.theme === 'dark' ? (
                <Sun size={18} />
              ) : (
                <Moon size={18} />
              )}
            </button>
            {!collapsed && (
              <div className="locale-switcher">
                {LOCALES.map((loc) => (
                  <button
                    key={loc.code}
                    className={`locale-btn${locale === loc.code ? ' active' : ''}`}
                    onClick={() => setLocale(loc.code)}
                  >
                    {loc.label}
                  </button>
                ))}
              </div>
            )}
          </div>
          <button onClick={handleLogout} className="btn-logout" title={t('accountMenu.logout')}>
            <LogOut size={18} />
            {!collapsed && <span>{t('accountMenu.logout')}</span>}
          </button>
        </div>
      </aside>

      {/* Main Content Area */}
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
