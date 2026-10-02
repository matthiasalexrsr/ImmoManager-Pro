import { useCallback, useEffect, useRef, useState } from 'react';
import { Link, NavLink, Outlet, useLocation, useNavigate } from 'react-router-dom';
import { logout } from '../api';
import { useTranslation } from '../i18n';
import { usePreferences } from '../contexts/PreferencesContext';
import { useAuth } from '../contexts/AuthContext';
import SearchBar from './SearchBar';
import NotificationBell from './NotificationBell';
import './AppShell.css';
import {
  DashboardIcon, PortfolioIcon, PropertyIcon, UnitIcon, TenantIcon, ContractIcon,
  AccountIcon, BookingIcon, InvoiceIcon, MaintenanceIcon, TaskIcon, DocumentIcon,
  SunIcon, MoonIcon, LogoutIcon, ChevronLeftIcon, ChevronRightIcon, RentIcon,
  MeterIcon, ContactIcon, StatementIcon, MessageIcon, SettingsIcon, CategoryIcon,
  DepositIcon, InsuranceIcon, IntegrationIcon, CalendarIcon, ChartIcon, SearchIcon,
  MenuIcon, CloseIcon,
} from './Icons';

// Route paths and existing translation keys stay unchanged. SearchBar owns search.
const NAV_SECTIONS = [
  { labelKey: 'navigation.sections.overview', items: [
    ['/', 'navigation.main.dashboard', DashboardIcon],
  ] },
  { labelKey: 'navigation.sections.portfolio', items: [
    ['/portfolios', 'navigation.main.portfolio', PortfolioIcon],
    ['/properties', 'navigation.main.properties', PropertyIcon],
    ['/units', 'units.list.title', UnitIcon],
    ['/insurances', 'navigation.main.insurances', InsuranceIcon],
  ] },
  { labelKey: 'navigation.sections.tenants', items: [
    ['/tenants', 'tenantsContracts.tenants.title', TenantIcon],
    ['/contracts', 'tenantsContracts.contracts.title', ContractIcon],
    ['/contract-wizard', 'navigation.main.contractWizard', ContractIcon],
    ['/contacts', 'navigation.main.contacts', ContactIcon],
    ['/deposits', 'navigation.main.deposits', DepositIcon],
    ['/rent-adjustments', 'navigation.main.rentAdjustments', RentIcon],
    ['/handover-protocols', 'navigation.main.handoverProtocols', DocumentIcon],
    ['/tenancy-workflows', 'navigation.main.tenancyWorkflows', TaskIcon],
  ] },
  { labelKey: 'navigation.sections.vacancy', items: [
    ['/leads', 'navigation.main.leads', TenantIcon],
    ['/listings', 'navigation.main.listings', SearchIcon],
    ['/viewings', 'navigation.main.viewings', CalendarIcon],
  ] },
  { labelKey: 'navigation.sections.finance', items: [
    ['/accounts', 'finance.accounts.title', AccountIcon],
    ['/bookings', 'finance.bookings.title', BookingIcon],
    ['/datev', 'pages.datev.title', DocumentIcon],
    ['/annual-tax', 'finance.tax', DocumentIcon],
    ['/invoices', 'finance.invoices.title', InvoiceIcon],
    ['/rent-overview', 'navigation.main.rentOverview', RentIcon],
    ['/statements', 'navigation.main.statements', StatementIcon],
    ['/receivables', 'navigation.main.receivables', InvoiceIcon],
    ['/rent-charges', 'navigation.main.rentCharges', RentIcon],
  ] },
  { labelKey: 'navigation.sections.operations', items: [
    ['/calendar', 'navigation.main.calendar', CalendarIcon],
    ['/maintenance', 'navigation.main.maintenance', MaintenanceIcon],
    ['/tasks', 'navigation.main.tasks', TaskIcon],
    ['/documents', 'navigation.main.documents', DocumentIcon],
    ['/meters', 'navigation.main.meters', MeterIcon],
    ['/messages', 'navigation.main.messages', MessageIcon],
    ['/outbox', 'pages.outbox.title', MessageIcon],
  ] },
  { labelKey: 'navigation.sections.configuration', items: [
    ['/categories', 'navigation.main.categories', CategoryIcon],
    ['/budgets', 'navigation.main.budgets', ChartIcon],
    ['/tax-rates', 'navigation.main.taxRates', AccountIcon],
    ['/allocation-keys', 'navigation.main.allocationKeys', StatementIcon],
    ['/integrations', 'navigation.main.integrations', IntegrationIcon],
    ['/escalation-rules', 'navigation.main.escalationRules', MaintenanceIcon],
    ['/notification-templates', 'navigation.main.notificationTemplates', MessageIcon],
    ['/history', 'navigation.main.history', DocumentIcon],
    ['/settings', 'navigation.main.settings', SettingsIcon],
  ] },
];
const LOCALES = [
  { code: 'de-DE', label: 'DE', name: 'Deutsch' },
  { code: 'en-US', label: 'EN', name: 'English' },
  { code: 'es-ES', label: 'ES', name: 'Español' },
];
const MOBILE_QUERY = '(max-width: 768px)';
const mobileMatches = () => typeof window.matchMedia === 'function' && window.matchMedia(MOBILE_QUERY).matches;
const FOCUSABLE = 'a[href],button:not([disabled]),input:not([disabled]):not([type="hidden"]),select:not([disabled]),textarea:not([disabled]),[tabindex]:not([tabindex="-1"])';
function focusableIn(element) {
  return [...element.querySelectorAll(FOCUSABLE)].filter(node => {
    const style = window.getComputedStyle(node);
    return !node.closest('[hidden], [inert], [aria-hidden="true"]')
      && style.display !== 'none' && style.visibility !== 'hidden' && node.getClientRects().length > 0;
  });
}

export default function Layout() {
  const navigate = useNavigate();
  const location = useLocation();
  const { t, locale } = useTranslation();
  const { prefs, toggleTheme, toggleSidebar, updatePrefs } = usePreferences();
  const auth = useAuth();
  const [isMobile, setIsMobile] = useState(mobileMatches);
  const [mobileNavOpen, setMobileNavOpen] = useState(false);
  const sidebarRef = useRef(null);
  const toggleRef = useRef(null);
  const contentRef = useRef(null);
  const closeReason = useRef('dismiss');
  const lastLocation = useRef(location.key);
  const drawerOpen = isMobile && mobileNavOpen;
  const collapsed = !isMobile && prefs.sidebar_collapsed;
  const text = key => t(`appShell.${key}`);
  const active = NAV_SECTIONS.flatMap(section => section.items.map(([to, labelKey]) => ({
    to, labelKey, sectionKey: section.labelKey,
  }))).sort((a, b) => b.to.length - a.to.length).find(item => item.to === '/'
    ? location.pathname === '/' : location.pathname === item.to || location.pathname.startsWith(`${item.to}/`));
  const isDetail = active && location.pathname !== active.to;
  const currentTitle = isDetail ? text('detail') : t(active?.labelKey || 'appShell.page');
  const displayName = auth?.user?.full_name || auth?.user?.username || 'ImmoManager';
  const initials = displayName.split(/\s+/).slice(0, 2).map(part => part[0]).join('').toUpperCase();
  const closeNavigation = useCallback((reason = 'dismiss') => {
    closeReason.current = reason;
    setMobileNavOpen(false);
  }, []);

  useEffect(() => {
    const query = window.matchMedia?.(MOBILE_QUERY);
    if (!query) return undefined;
    const update = () => {
      setIsMobile(query.matches);
      if (!query.matches) closeNavigation('resize');
    };
    query.addEventListener('change', update);
    return () => query.removeEventListener('change', update);
  }, [closeNavigation]);

  useEffect(() => {
    if (lastLocation.current !== location.key) {
      lastLocation.current = location.key;
      closeNavigation('route');
    }
  }, [location.key, closeNavigation]);

  useEffect(() => {
    document.title = `${currentTitle} · ImmoManager Pro`;
  }, [currentTitle]);

  useEffect(() => {
    document.documentElement.lang = locale;
  }, [locale]);

  useEffect(() => {
    if (!drawerOpen) return undefined;
    const sidebar = sidebarRef.current;
    const content = contentRef.current;
    const opener = toggleRef.current;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    const first = () => focusableIn(sidebar)[0] || sidebar;
    const focusDrawer = () => {
      if (sidebar.contains(document.activeElement)) return;
      const current = sidebar.querySelector('a[aria-current="page"]') || first();
      current.focus({ preventScroll: true });
      current.scrollIntoView?.({ block: 'nearest' });
    };
    // Native inert removal becomes focusable after a paint on the first opening.
    let focusFrame = requestAnimationFrame(() => {
      focusFrame = requestAnimationFrame(focusDrawer);
    });
    const finishOpening = event => { if (event.target === sidebar) focusDrawer(); };
    sidebar.addEventListener('transitionend', finishOpening);
    const onKeyDown = event => {
      if (event.defaultPrevented) return;
      if (event.key === 'Escape') {
        event.preventDefault();
        event.stopPropagation();
        closeNavigation();
      }
      if (event.key !== 'Tab') return;
      const elements = focusableIn(sidebar);
      const start = elements[0] || sidebar;
      const end = elements.at(-1) || sidebar;
      if (!sidebar.contains(document.activeElement) || (event.shiftKey && document.activeElement === start)) {
        event.preventDefault();
        (event.shiftKey ? end : start).focus();
      } else if (!event.shiftKey && document.activeElement === end) {
        event.preventDefault();
        start.focus();
      }
    };
    const onFocus = event => {
      if (!sidebar.contains(event.target)) first().focus();
    };
    document.addEventListener('keydown', onKeyDown);
    document.addEventListener('focusin', onFocus);
    return () => {
      cancelAnimationFrame(focusFrame);
      sidebar.removeEventListener('transitionend', finishOpening);
      document.body.style.overflow = previousOverflow;
      document.removeEventListener('keydown', onKeyDown);
      document.removeEventListener('focusin', onFocus);
      // Rerender removes inert before focus returns. Route changes focus the content,
      // dismissals return to the opener, and a desktop resize never targets a hidden button.
      const reason = closeReason.current;
      requestAnimationFrame(() => {
        const target = reason === 'route' || !mobileMatches() ? content : opener;
        if (target?.isConnected) target.focus({ preventScroll: true });
      });
    };
  }, [drawerOpen, closeNavigation]);

  return (
    <div className={`app-layout app-shell ${collapsed ? 'sidebar-collapsed' : ''} ${drawerOpen ? 'mobile-nav-open' : ''}`}>
      <a href="#workspace-content" className="shell-skip-link" inert={drawerOpen}>{text('skipContent')}</a>
      <aside ref={sidebarRef} id="primary-navigation" className="sidebar" tabIndex={-1}
        role={drawerOpen ? 'dialog' : undefined} aria-modal={drawerOpen ? true : undefined}
        aria-label={text('navigation')} aria-hidden={isMobile && !drawerOpen ? true : undefined}
        inert={isMobile && !drawerOpen}>
        <div className="sidebar-header">
          <div className="sidebar-logo" aria-hidden="true">IM</div>
          {!collapsed && <div className="sidebar-brand">
            <span className="sidebar-brand-name">ImmoManager <span>Pro</span></span>
            <span className="sidebar-brand-sub">{text('workspace')}</span>
          </div>}
          <button type="button" className="sidebar-mobile-close" hidden={!isMobile} onClick={() => closeNavigation()}
            aria-label={text('closeNavigation')}><CloseIcon size={20} /></button>
        </div>
        <nav className="sidebar-nav" aria-label={text('navigation')}>
          {NAV_SECTIONS.map(section => <section className="shell-nav-group" key={section.labelKey}>
            {!collapsed && <h2 className="sidebar-section-label">{t(section.labelKey)}</h2>}
            {section.items.map(item => {
              const [to, labelKey, Icon] = item;
              return <NavLink key={to} to={to} end={to === '/'}
              className={({ isActive }) => `nav-link${isActive ? ' active' : ''}`}
              aria-label={t(labelKey)} title={collapsed ? t(labelKey) : undefined}
              onClick={event => {
                if (!event.metaKey && !event.ctrlKey && !event.shiftKey && !event.altKey && event.button === 0) closeNavigation('route');
              }}>
              <span className="icon-wrapper" aria-hidden="true"><Icon size={19} /></span>
              {!collapsed && <span>{t(labelKey)}</span>}
            </NavLink>;
            })}
          </section>)}
        </nav>
        <div className="sidebar-footer">
          <div className="sidebar-controls">
            <button type="button" hidden={isMobile} onClick={toggleSidebar} className="sidebar-control-btn"
              aria-label={t(collapsed ? 'sidebar.expand' : 'sidebar.collapse')}
              title={t(collapsed ? 'sidebar.expand' : 'sidebar.collapse')}>
              {collapsed ? <ChevronRightIcon size={18} /> : <ChevronLeftIcon size={18} />}
            </button>
            <button type="button" onClick={toggleTheme} className="sidebar-control-btn" aria-pressed={prefs.theme === 'dark'} aria-label={t('sidebar.toggleTheme')}
              title={t('sidebar.toggleTheme')}>
              {prefs.theme === 'dark' ? <SunIcon size={18} /> : <MoonIcon size={18} />}
            </button>
            <div className="locale-switcher" role="group" aria-label={text('language')}>
              {LOCALES.map(loc => <button type="button" key={loc.code} className={`locale-btn${locale === loc.code ? ' active' : ''}`}
                aria-label={loc.name} aria-pressed={locale === loc.code} onClick={() => updatePrefs({ locale: loc.code })}>{loc.label}</button>)}
            </div>
          </div>
          <button type="button" onClick={() => { logout(); auth?.clearUser(); navigate('/login'); }} className="btn-logout" aria-label={t('accountMenu.logout')}>
            <LogoutIcon size={17} />{!collapsed && <span>{t('accountMenu.logout')}</span>}
          </button>
        </div>
      </aside>
      {drawerOpen && <div className="mobile-nav-backdrop" aria-hidden="true" onClick={() => closeNavigation()} />}
      <div className="main-content" inert={drawerOpen}>
        <header className="top-bar">
          <div className="top-bar-left">
            <button type="button" ref={toggleRef} className="top-bar-mobile-toggle" hidden={!isMobile}
              onClick={() => { closeReason.current = 'dismiss'; setMobileNavOpen(true); }}
              aria-controls="primary-navigation" aria-expanded={drawerOpen} aria-label={text('openNavigation')}>
              <MenuIcon size={21} />
            </button>
            <nav className="shell-breadcrumbs" aria-label={text('breadcrumb')}>
              <ol>
                {active?.to !== '/' && <li><Link to="/">{t('navigation.main.dashboard')}</Link></li>}
                {active?.to !== '/' && active && <li className="shell-breadcrumb-section"><span>{t(active.sectionKey)}</span></li>}
                {isDetail && <li><Link to={active.to}>{t(active.labelKey)}</Link></li>}
                <li><span aria-current="page" className="top-bar-page-title">{currentTitle}</span></li>
              </ol>
            </nav>
          </div>
          <SearchBar />
          <div className="shell-header-tools">
            <NotificationBell />
            <div className="shell-identity" title={displayName}>
              <span className="shell-avatar" aria-hidden="true">{initials}</span>
              <span className="shell-identity-label"><strong>{displayName}</strong>
                <small>{auth?.isReadonly ? text('readonly') : text('workspace')}</small></span>
            </div>
          </div>
        </header>
        <main ref={contentRef} tabIndex={-1} id="workspace-content" className="main-content-body">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
