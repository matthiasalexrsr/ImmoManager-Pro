import { NavLink, Outlet, useNavigate } from 'react-router-dom';
import { logout } from '../api';
import { useTranslation } from '../i18n';
import { usePreferences } from '../contexts/PreferencesContext';
import SearchBar from './SearchBar';
import NotificationBell from './NotificationBell';
import {
  DashboardIcon, PortfolioIcon, PropertyIcon, UnitIcon,
  TenantIcon, ContractIcon, AccountIcon, BookingIcon,
  InvoiceIcon, MaintenanceIcon, TaskIcon, DocumentIcon,
  SunIcon, MoonIcon, LogoutIcon, ChevronLeftIcon, ChevronRightIcon,
  RentIcon, MeterIcon, ContactIcon, StatementIcon, MessageIcon, SettingsIcon,
  CategoryIcon, DepositIcon, InsuranceIcon, IntegrationIcon,
  CalendarIcon, ChartIcon, SearchIcon,
} from './Icons';

const NAV_SECTIONS = [
  {
    labelKey: 'navigation.sections.overview',
    fallback: 'Overview',
    items: [
      { to: '/', labelKey: 'navigation.main.dashboard', fallback: 'Dashboard', icon: DashboardIcon },
    ],
  },
  {
    labelKey: 'navigation.sections.portfolio',
    fallback: 'Portfolio',
    items: [
      { to: '/portfolios', labelKey: 'navigation.main.portfolio', fallback: 'Portfolios', icon: PortfolioIcon },
      { to: '/properties', labelKey: 'navigation.main.properties', fallback: 'Immobilien', icon: PropertyIcon },
      { to: '/units', labelKey: 'units.list.title', fallback: 'Einheiten', icon: UnitIcon },
      { to: '/insurances', labelKey: 'navigation.main.insurances', fallback: 'Versicherungen', icon: InsuranceIcon },
    ],
  },
  {
    labelKey: 'navigation.sections.tenants',
    fallback: 'Mieter & Vertr\u00e4ge',
    items: [
      { to: '/tenants', labelKey: 'tenantsContracts.tenants.title', fallback: 'Mieter', icon: TenantIcon },
      { to: '/contracts', labelKey: 'tenantsContracts.contracts.title', fallback: 'Vertr\u00e4ge', icon: ContractIcon },
      { to: '/contacts', labelKey: 'navigation.main.contacts', fallback: 'Kontakte', icon: ContactIcon },
      { to: '/deposits', labelKey: 'navigation.main.deposits', fallback: 'Kautionen', icon: DepositIcon },
      { to: '/rent-adjustments', labelKey: 'navigation.main.rentAdjustments', fallback: 'Mietanpassungen', icon: RentIcon },
    ],
  },
  {
    labelKey: 'navigation.sections.vacancy',
    fallback: 'Leerstand',
    items: [
      { to: '/leads', labelKey: 'navigation.main.leads', fallback: 'Interessenten', icon: TenantIcon },
      { to: '/listings', labelKey: 'navigation.main.listings', fallback: 'Inserate', icon: SearchIcon },
      { to: '/viewings', labelKey: 'navigation.main.viewings', fallback: 'Besichtigungen', icon: CalendarIcon },
    ],
  },
  {
    labelKey: 'navigation.sections.finance',
    fallback: 'Finanzen',
    items: [
      { to: '/accounts', labelKey: 'finance.accounts.title', fallback: 'Konten', icon: AccountIcon },
      { to: '/bookings', labelKey: 'finance.bookings.title', fallback: 'Buchungen', icon: BookingIcon },
      { to: '/invoices', labelKey: 'finance.invoices.title', fallback: 'Rechnungen', icon: InvoiceIcon },
      { to: '/rent-overview', labelKey: 'navigation.main.rentOverview', fallback: 'Miet\u00fcbersicht', icon: RentIcon },
      { to: '/statements', labelKey: 'navigation.main.statements', fallback: 'Abrechnungen', icon: StatementIcon },
      { to: '/categories', labelKey: 'navigation.main.categories', fallback: 'Kategorien', icon: CategoryIcon },
      { to: '/budgets', labelKey: 'navigation.main.budgets', fallback: 'Budgets', icon: ChartIcon },
      { to: '/tax-rates', labelKey: 'navigation.main.taxRates', fallback: 'Steuersätze', icon: AccountIcon },
      { to: '/receivables', labelKey: 'navigation.main.receivables', fallback: 'Offene Posten', icon: InvoiceIcon },
      { to: '/rent-charges', labelKey: 'navigation.main.rentCharges', fallback: 'Sollstellung', icon: RentIcon },
    ],
  },
  {
    labelKey: 'navigation.sections.operations',
    fallback: 'Verwaltung',
    items: [
      { to: '/calendar', labelKey: 'navigation.main.calendar', fallback: 'Kalender', icon: CalendarIcon },
      { to: '/maintenance', labelKey: 'navigation.main.maintenance', fallback: 'Wartung', icon: MaintenanceIcon },
      { to: '/tasks', labelKey: 'navigation.main.tasks', fallback: 'Aufgaben', icon: TaskIcon },
      { to: '/documents', labelKey: 'navigation.main.documents', fallback: 'Dokumente', icon: DocumentIcon },
      { to: '/meters', labelKey: 'navigation.main.meters', fallback: 'Z\u00e4hler', icon: MeterIcon },
      { to: '/messages', labelKey: 'navigation.main.messages', fallback: 'Nachrichten', icon: MessageIcon },
      { to: '/integrations', labelKey: 'navigation.main.integrations', fallback: 'Integrationen', icon: IntegrationIcon },
      { to: '/escalation-rules', labelKey: 'navigation.main.escalationRules', fallback: 'Eskalationsregeln', icon: MaintenanceIcon },
      { to: '/notification-templates', labelKey: 'navigation.main.notificationTemplates', fallback: 'Benachrichtigungsvorlagen', icon: MessageIcon },
      { to: '/history', labelKey: 'navigation.main.history', fallback: 'Änderungshistorie', icon: DocumentIcon },
      { to: '/contract-wizard', labelKey: 'navigation.main.contractWizard', fallback: 'Mietvertrag-Wizard', icon: ContractIcon },
      { to: '/settings', labelKey: 'navigation.main.settings', fallback: 'Einstellungen', icon: SettingsIcon },
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

  const tr = (key, fallback) => {
    const result = t(key);
    return result === key ? fallback : result;
  };

  return (
    <div className={`app-layout ${collapsed ? 'sidebar-collapsed' : ''}`}>
      <aside className="sidebar">
        <div className="sidebar-header">
          <div className="sidebar-logo">IM</div>
          {!collapsed && (
            <div className="sidebar-brand">
              <span className="sidebar-brand-name">ImmoManager</span>
              <span className="sidebar-brand-sub">Pro</span>
            </div>
          )}
        </div>
        <nav className="sidebar-nav">
          {NAV_SECTIONS.map((section, si) => (
            <div key={si}>
              {!collapsed && (
                <div className="sidebar-section-label">
                  {tr(section.labelKey, section.fallback)}
                </div>
              )}
              {section.items.map((item) => {
                if (item.externalApp) {
                  return (
                    <a key={item.href} href={item.href} className="nav-link">
                      <span className="icon-wrapper">
                        <item.icon size={18} />
                      </span>
                      {!collapsed && <span>{tr(item.labelKey, item.fallback)}</span>}
                    </a>
                  );
                }

                return (
                  <NavLink
                    key={item.to}
                    to={item.to}
                    end={item.to === '/'}
                    className={({ isActive }) => `nav-link ${isActive ? 'active' : ''}`}
                  >
                    <span className="icon-wrapper">
                      <item.icon size={18} />
                    </span>
                    {!collapsed && <span>{tr(item.labelKey, item.fallback)}</span>}
                  </NavLink>
                );
              })}
            </div>
          ))}
        </nav>
        <div className="sidebar-footer">
          <div className="sidebar-controls">
            <button onClick={toggleSidebar} className="sidebar-control-btn" title={collapsed ? t('sidebar.expand') : t('sidebar.collapse')}>
              {collapsed ? <ChevronRightIcon size={16} /> : <ChevronLeftIcon size={16} />}
            </button>
            <button onClick={toggleTheme} className="sidebar-control-btn" title={t('sidebar.toggleTheme')}>
              {prefs.theme === 'dark' ? <SunIcon size={16} /> : <MoonIcon size={16} />}
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
          <button
            onClick={() => { logout(); navigate('/login'); }}
            className="btn-logout"
          >
            <LogoutIcon size={16} />
            {!collapsed && <span>{t('accountMenu.logout')}</span>}
          </button>
        </div>
      </aside>
      <main className="main-content">
        <div className="top-bar">
          <SearchBar />
          <NotificationBell />
        </div>
        <div className="main-content-body">
          <Outlet />
        </div>
      </main>
    </div>
  );
}
