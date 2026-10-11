import { useEffect, useRef, useState } from 'react';
import { NavLink, Outlet, useLocation, useNavigate } from 'react-router-dom';
import { logout } from '../api';
import './Shell.css';
import { useTranslation } from '../i18n';
import { usePreferences } from '../contexts/PreferencesContext';
import SearchBar from './SearchBar';
import NotificationBell from './NotificationBell';
import { TutorialProvider, useTutorial } from './Tutorial';
import { PartyWorkspaceProvider } from '../features/partyWorkspace/PartyWorkspace';
import {
  DashboardIcon, PortfolioIcon, PropertyIcon, UnitIcon,
  TenantIcon, ContractIcon, AccountIcon, BookingIcon,
  InvoiceIcon, MaintenanceIcon, TaskIcon, DocumentIcon,
  SunIcon, MoonIcon, LogoutIcon, ChevronLeftIcon, ChevronRightIcon,
  RentIcon, MeterIcon, ContactIcon, StatementIcon, MessageIcon, SettingsIcon,
  CategoryIcon, DepositIcon, InsuranceIcon, IntegrationIcon,
  CalendarIcon, ChartIcon, SearchIcon, MenuIcon, CloseIcon, HelpIcon,
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
      { to: '/service-contracts', labelKey: 'navigation.main.serviceContracts', fallback: 'Objektverträge', icon: ContractIcon },
    ],
  },
  {
    labelKey: 'navigation.sections.tenants',
    fallback: 'Mieter & Verträge',
    items: [
      { to: '/tenants', labelKey: 'tenantsContracts.tenants.title', fallback: 'Mieter', icon: TenantIcon },
      { to: '/contracts', labelKey: 'tenantsContracts.contracts.title', fallback: 'Verträge', icon: ContractIcon },
      { to: '/contract-wizard', labelKey: 'navigation.main.contractWizard', fallback: 'Mietvertrag-Wizard', icon: ContractIcon },
      { to: '/contacts', labelKey: 'navigation.main.contacts', fallback: 'Kontakte', icon: ContactIcon },
      { to: '/deposits', labelKey: 'navigation.main.deposits', fallback: 'Kautionen', icon: DepositIcon },
      { to: '/rent-adjustments', labelKey: 'navigation.main.rentAdjustments', fallback: 'Mietanpassungen', icon: RentIcon },
      { to: '/handover-protocols', labelKey: 'navigation.main.handoverProtocols', fallback: 'Übergabeprotokolle', icon: DocumentIcon },
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
      { to: '/rent-overview', labelKey: 'navigation.main.rentOverview', fallback: 'Mietübersicht', icon: RentIcon },
      { to: '/statements', labelKey: 'navigation.main.statements', fallback: 'Abrechnungen', icon: StatementIcon },
      { to: '/receivables', labelKey: 'navigation.main.receivables', fallback: 'Forderungen', icon: InvoiceIcon },
      { to: '/review', labelKey: 'navigation.main.review', fallback: 'Prüfliste', icon: InvoiceIcon },
      { to: '/rent-charges', labelKey: 'navigation.main.rentCharges', fallback: 'Sollstellungen', icon: RentIcon },
    ],
  },
  {
    labelKey: 'navigation.sections.operations',
    fallback: 'Betrieb',
    items: [
      { to: '/calendar', labelKey: 'navigation.main.calendar', fallback: 'Kalender', icon: CalendarIcon },
      { to: '/maintenance', labelKey: 'navigation.main.maintenance', fallback: 'Wartung', icon: MaintenanceIcon },
      { to: '/tasks', labelKey: 'navigation.main.tasks', fallback: 'Aufgaben', icon: TaskIcon },
      { to: '/documents', labelKey: 'navigation.main.documents', fallback: 'Dokumente', icon: DocumentIcon },
      { to: '/meters', labelKey: 'navigation.main.meters', fallback: 'Zähler', icon: MeterIcon },
      { to: '/messages', labelKey: 'navigation.main.messages', fallback: 'Nachrichten', icon: MessageIcon },
    ],
  },
  {
    labelKey: 'navigation.sections.configuration',
    fallback: 'Konfiguration',
    items: [
      { to: '/categories', labelKey: 'navigation.main.categories', fallback: 'Kategorien', icon: CategoryIcon },
      { to: '/budgets', labelKey: 'navigation.main.budgets', fallback: 'Budgets', icon: ChartIcon },
      { to: '/tax-rates', labelKey: 'navigation.main.taxRates', fallback: 'Steuersätze', icon: AccountIcon },
      { to: '/allocation-keys', labelKey: 'navigation.main.allocationKeys', fallback: 'Verteilerschlüssel', icon: StatementIcon },
      { to: '/integrations', labelKey: 'navigation.main.integrations', fallback: 'Schnittstellen', icon: IntegrationIcon },
      { to: '/escalation-rules', labelKey: 'navigation.main.escalationRules', fallback: 'Eskalationsregeln', icon: MaintenanceIcon },
      { to: '/notification-templates', labelKey: 'navigation.main.notificationTemplates', fallback: 'Benachrichtigungsvorlagen', icon: MessageIcon },
      { to: '/history', labelKey: 'navigation.main.history', fallback: 'Änderungsprotokoll', icon: DocumentIcon },
      { to: '/settings', labelKey: 'navigation.main.settings', fallback: 'Einstellungen', icon: SettingsIcon },
    ],
  },
];

const LOCALES = [
  { code: 'de-DE', label: 'DE' },
  { code: 'en-US', label: 'EN' },
  { code: 'es-ES', label: 'ES' },
];

function findActiveNavItem(pathname) {
  const navItems = NAV_SECTIONS.flatMap(section => section.items)
    .sort((a, b) => b.to.length - a.to.length);

  return navItems.find(item => item.to === '/'
    ? pathname === '/'
    : pathname === item.to || pathname.startsWith(`${item.to}/`));
}

/** "Testversion" in the top bar when the server runs the test package (fictitious data). */
function TestVersionBadge() {
  const [testversion, setTestversion] = useState(false);
  useEffect(() => {
    fetch('/health').then(r => (r.ok ? r.json() : null)).then(h => setTestversion(!!h?.testversion)).catch(() => {});
  }, []);
  if (!testversion) return null;
  return (
    <span className="testversion-badge" title="Testversion: alle Daten sind frei erfunden">Testversion</span>
  );
}

function TutorialButton() {
  const { start } = useTutorial();
  return (
    <button className="top-bar-icon-btn" onClick={() => start(0)} title="Tutorial: Tour durch die wichtigsten Funktionen"
      aria-label="Tutorial starten" data-tour="tutorial-button">
      <HelpIcon size={18} />
    </button>
  );
}

export default function Layout() {
  return (
    <TutorialProvider>
      <PartyWorkspaceProvider><LayoutFrame /></PartyWorkspaceProvider>
    </TutorialProvider>
  );
}

const PRIMARY_PATHS = ['/', '/properties', '/tenants', '/bookings', '/tasks', '/documents'];
const PRIMARY_ITEMS = PRIMARY_PATHS.map(path => NAV_SECTIONS.flatMap(section => section.items).find(item => item.to === path));
const GROUPS = NAV_SECTIONS.slice(1).map(section => ({ ...section, items: section.items.filter(item => !PRIMARY_PATHS.includes(item.to)) }));
const SHELL_TEXT = {
  de: { navigation: 'Hauptnavigation', open: 'Navigation öffnen', close: 'Navigation schließen', workspace: 'Arbeitsplatz', areas: 'Verwaltungsbereiche', expand: 'Navigation erweitern', collapse: 'Navigation einklappen', theme: 'Darstellung wechseln', logout: 'Abmelden' },
  en: { navigation: 'Main navigation', open: 'Open navigation', close: 'Close navigation', workspace: 'Workspace', areas: 'Management', expand: 'Expand navigation', collapse: 'Collapse navigation', theme: 'Change theme', logout: 'Sign out' },
  es: { navigation: 'Navegación principal', open: 'Abrir navegación', close: 'Cerrar navegación', workspace: 'Área de trabajo', areas: 'Administración', expand: 'Ampliar navegación', collapse: 'Contraer navegación', theme: 'Cambiar tema', logout: 'Cerrar sesión' },
};

function LayoutFrame() {
  const navigate = useNavigate();
  const location = useLocation();
  const { t, locale, setLocale } = useTranslation();
  const { prefs, toggleTheme, toggleSidebar } = usePreferences();
  const words = SHELL_TEXT[locale?.slice(0, 2)] || SHELL_TEXT.de;
  const [mobile, setMobile] = useState(() => window.matchMedia?.('(max-width: 768px)').matches || false);
  const [mobileNavOpen, setMobileNavOpen] = useState(false);
  const [groupsOpen, setGroupsOpen] = useState({});
  const [loggingOut, setLoggingOut] = useState(false);
  const [logoutError, setLogoutError] = useState(null);
  const sidebarRef = useRef(null);
  const closeRef = useRef(null);
  const menuRef = useRef(null);
  const previousPathRef = useRef(location.pathname);
  const collapsed = prefs.sidebar_collapsed && !mobile;
  const tr = (key, fallback) => { const result = t(key); return !result || result === key ? fallback : result; };
  const activeItem = findActiveNavItem(location.pathname);
  const activeSection = NAV_SECTIONS.find(section => section.items.includes(activeItem));
  const activeGroup = GROUPS.find(section => section.items.some(item => item.to === activeItem?.to))?.labelKey;
  const currentPageTitle = activeItem ? tr(activeItem.labelKey, activeItem.fallback) : tr('navigation.main.dashboard', 'Dashboard');

  useEffect(() => {
    if (activeGroup) setGroupsOpen(current => ({ ...current, [activeGroup]: true }));
  }, [activeGroup, location.pathname]);

  useEffect(() => {
    const query = window.matchMedia?.('(max-width: 768px)');
    if (!query) return;
    const update = event => { setMobile(event.matches); if (!event.matches) setMobileNavOpen(false); };
    query.addEventListener('change', update);
    return () => query.removeEventListener('change', update);
  }, []);

  useEffect(() => {
    setMobileNavOpen(false);
    if (previousPathRef.current === location.pathname) return;
    previousPathRef.current = location.pathname;
    window.scrollTo(0, 0);
  }, [location.pathname]);

  useEffect(() => {
    if (!mobileNavOpen) return;
    const returnFocus = document.activeElement;
    const menuButton = menuRef.current;
    const originalOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    closeRef.current?.focus();
    const keydown = event => {
      if (event.key === 'Escape') { event.preventDefault(); setMobileNavOpen(false); }
      if (event.key !== 'Tab') return;
      const controls = [...sidebarRef.current.querySelectorAll(':is(a[href], button:not(:disabled), input, select, [tabindex="0"])')]
        .filter(element => getComputedStyle(element).display !== 'none' && getComputedStyle(element).visibility !== 'hidden');
      const first = controls[0];
      const last = controls.at(-1);
      if (event.shiftKey && (document.activeElement === first || !sidebarRef.current.contains(document.activeElement))) {
        event.preventDefault(); last?.focus();
      } else if (!event.shiftKey && (document.activeElement === last || !sidebarRef.current.contains(document.activeElement))) {
        event.preventDefault(); first?.focus();
      }
    };
    window.addEventListener('keydown', keydown);
    return () => {
      document.body.style.overflow = originalOverflow;
      window.removeEventListener('keydown', keydown);
      if (returnFocus?.isConnected) returnFocus.focus();
      else menuButton?.focus();
    };
  }, [mobileNavOpen]);

  const handleLogout = async () => {
    if (loggingOut) return;
    setLoggingOut(true); setLogoutError(null);
    try { await logout(); navigate('/login'); }
    catch (error) { setLogoutError(error.message); }
    finally { setLoggingOut(false); }
  };
  const toggleGroup = key => {
    if (collapsed) {
      toggleSidebar();
      setGroupsOpen(current => ({ ...current, [key]: true }));
    } else setGroupsOpen(current => ({ ...current, [key]: !current[key] }));
  };
  const navItem = item => {
    const label = tr(item.labelKey, item.fallback);
    return <NavLink key={item.to} to={item.to} end={item.to === '/'}
      className={({ isActive }) => `nav-link ${isActive ? 'active' : ''}`}
      aria-label={label} title={collapsed ? label : undefined} onClick={() => setMobileNavOpen(false)}>
      <span className="icon-wrapper"><item.icon size={19} /></span>
      <span className="nav-label">{label}</span>
    </NavLink>;
  };

  return (
    <div className={`app-layout workspace-shell ${collapsed ? 'sidebar-collapsed' : ''} ${mobileNavOpen ? 'mobile-nav-open' : ''}`}>
      <aside ref={sidebarRef} className="sidebar" role={mobileNavOpen ? 'dialog' : undefined}
        aria-modal={mobileNavOpen ? true : undefined} aria-label={words.navigation} inert={mobile && !mobileNavOpen ? true : undefined}>
        <div className="sidebar-header">
          <div className="sidebar-logo" aria-hidden="true">IM</div>
          <div className="sidebar-brand"><span className="sidebar-brand-name">ImmoManager</span><span className="sidebar-brand-sub">PRO · {words.workspace}</span></div>
          {mobile && <button ref={closeRef} type="button" className="sidebar-mobile-close" onClick={() => setMobileNavOpen(false)} aria-label={words.close}><CloseIcon size={20} /></button>}
        </div>
        <nav className="sidebar-nav" id="primary-navigation" aria-label={words.navigation}>
          <div className="nav-primary">{PRIMARY_ITEMS.map(navItem)}</div>
          <div className="sidebar-section-label">{words.areas}</div>
          {GROUPS.map((section, index) => {
            const open = !collapsed && Boolean(groupsOpen[section.labelKey]);
            const label = tr(section.labelKey, section.fallback);
            const GroupIcon = section.labelKey.endsWith('configuration') ? SettingsIcon : section.items[0].icon;
            return <div className="nav-group" key={section.labelKey}>
              <button type="button" className={`nav-group-toggle ${activeSection?.labelKey === section.labelKey ? 'has-current' : ''}`}
                aria-label={label} title={collapsed ? label : undefined} aria-expanded={open} aria-controls={`nav-group-${index}`}
                onClick={() => toggleGroup(section.labelKey)}>
                <span className="icon-wrapper"><GroupIcon size={19} /></span><span className="nav-label">{label}</span>
                <ChevronRightIcon size={14} className="nav-group-chevron" />
              </button>
              {open && <div className="nav-group-items" id={`nav-group-${index}`}>{section.items.map(navItem)}</div>}
            </div>;
          })}
        </nav>
        <div className="sidebar-footer">
          <div className="sidebar-controls">
            {!mobile && <button type="button" onClick={toggleSidebar} className="sidebar-control-btn sidebar-collapse-toggle" aria-label={collapsed ? words.expand : words.collapse} title={collapsed ? words.expand : words.collapse}>{collapsed ? <ChevronRightIcon size={17} /> : <ChevronLeftIcon size={17} />}</button>}
            <button type="button" onClick={toggleTheme} className="sidebar-control-btn" aria-label={words.theme} title={words.theme}>{prefs.theme === 'dark' ? <SunIcon size={17} /> : <MoonIcon size={17} />}</button>
            <div className="locale-switcher">{LOCALES.map(loc => <button type="button" key={loc.code} className={`locale-btn ${locale === loc.code ? 'active' : ''}`} aria-pressed={locale === loc.code} onClick={() => setLocale(loc.code)}>{loc.label}</button>)}</div>
          </div>
          <button type="button" onClick={handleLogout} disabled={loggingOut} className="btn-logout" aria-label={tr('accountMenu.logout', words.logout)} title={collapsed ? tr('accountMenu.logout', words.logout) : undefined}><LogoutIcon size={18} /><span>{tr('accountMenu.logout', words.logout)}</span></button>
          {logoutError && <p className="shell-logout-error" role="alert">{logoutError}</p>}
        </div>
      </aside>
      {mobileNavOpen && <button type="button" className="mobile-nav-backdrop" tabIndex={-1} onClick={() => setMobileNavOpen(false)} aria-label={words.close} />}
      <main className="main-content" inert={mobileNavOpen ? true : undefined}>
        <div className="top-bar">
          <div className="top-bar-left">
            {mobile && <button ref={menuRef} type="button" className="top-bar-mobile-toggle" onClick={() => setMobileNavOpen(true)} aria-controls="primary-navigation" aria-expanded={mobileNavOpen} aria-label={words.open}><MenuIcon size={20} /></button>}
            <div className="top-bar-page-title"><span className="shell-context">{activeSection ? tr(activeSection.labelKey, activeSection.fallback) : words.workspace}</span><span className="shell-context-divider" aria-hidden="true">/</span><span>{currentPageTitle}</span></div>
          </div>
          <SearchBar />
          <div className="top-bar-utilities"><TestVersionBadge /><TutorialButton /><NotificationBell /></div>
        </div>
        <div className="main-content-body">
          <h1 className="page-title page-title-auto">{currentPageTitle}</h1>
          <Outlet />
        </div>
      </main>
    </div>
  );
}
