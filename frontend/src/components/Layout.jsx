import { useEffect, useRef, useState } from 'react';
import { NavLink, Outlet, useLocation, useNavigate } from 'react-router-dom';
import { logout } from '../api';
import './Shell.css';
import { useTranslation } from '../i18n';
import { usePreferences } from '../contexts/PreferencesContext';
import SearchBar from './SearchBar';
import QuickAccess from '../features/workCenter/QuickAccess';
import NotificationBell from './NotificationBell';
import { TutorialProvider, useTutorial } from './Tutorial';
import { PartyWorkspaceProvider } from '../features/partyWorkspace/PartyWorkspace';
import {
  SunIcon, MoonIcon, LogoutIcon, ChevronLeftIcon, ChevronRightIcon,
  SettingsIcon, MenuIcon, CloseIcon, HelpIcon,
} from './Icons';
import { Keyboard, Star } from 'lucide-react';
import { NAV_SECTIONS, SUB_PAGES } from './navigation';
import ShortcutHelp from './ShortcutHelp';
import { useAuth } from '../contexts/AuthContext';
import { useNavFavorites } from '../utils/navFavorites';
import { dropNewEntry, holdNewEntry, requestNewEntry } from '../utils/newEntry';
import useNavigationState from '../hooks/useNavigationState';


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

const findSubPage = pathname => SUB_PAGES.find(page => pathname === page.to || pathname.startsWith(`${page.to}/`));

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
const ALL_ITEMS = NAV_SECTIONS.flatMap(section => section.items);
const PINNABLE_PATHS = ALL_ITEMS.map(item => item.to).filter(path => !PRIMARY_PATHS.includes(path));
const isEditable = element => element instanceof HTMLElement
  && (element.isContentEditable || ['INPUT', 'TEXTAREA', 'SELECT'].includes(element.tagName));
const PRIMARY_ITEMS = PRIMARY_PATHS.map(path => NAV_SECTIONS.flatMap(section => section.items).find(item => item.to === path));
// Keep every non-primary destination, including the work center in the
// Overview section. Dropping the whole first group hid that real page.
const GROUPS = NAV_SECTIONS.map(section => ({
  ...section, items: section.items.filter(item => !PRIMARY_PATHS.includes(item.to)),
})).filter(section => section.items.length > 0);
const SHELL_TEXT = {
  de: { skip: 'Zum Hauptinhalt springen', favorites: 'Favoriten', pin: 'Als Favorit in die Seitenleiste', unpin: 'Aus den Favoriten entfernen', shortcuts: 'Tastenkürzel', navigation: 'Hauptnavigation', open: 'Navigation öffnen', close: 'Navigation schließen', workspace: 'Arbeitsplatz', areas: 'Verwaltungsbereiche', expand: 'Navigation erweitern', collapse: 'Navigation einklappen', theme: 'Darstellung wechseln', logout: 'Abmelden' },
  en: { skip: 'Skip to main content', favorites: 'Favourites', pin: 'Pin to the sidebar', unpin: 'Remove from favourites', shortcuts: 'Keyboard shortcuts', navigation: 'Main navigation', open: 'Open navigation', close: 'Close navigation', workspace: 'Workspace', areas: 'Management', expand: 'Expand navigation', collapse: 'Collapse navigation', theme: 'Change theme', logout: 'Sign out' },
  es: { skip: 'Saltar al contenido principal', favorites: 'Favoritos', pin: 'Fijar en la barra lateral', unpin: 'Quitar de favoritos', shortcuts: 'Atajos de teclado', navigation: 'Navegación principal', open: 'Abrir navegación', close: 'Cerrar navegación', workspace: 'Área de trabajo', areas: 'Administración', expand: 'Ampliar navegación', collapse: 'Contraer navegación', theme: 'Cambiar tema', logout: 'Cerrar sesión' },
};

function LayoutFrame() {
  useNavigationState();
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
  const [showShortcuts, setShowShortcuts] = useState(false);
  const [favorites, toggleFavorite] = useNavFavorites(useAuth()?.user?.id, PINNABLE_PATHS);
  const favoriteItems = favorites.map(path => ALL_ITEMS.find(item => item.to === path)).filter(Boolean);
  const sidebarRef = useRef(null);
  const closeRef = useRef(null);
  const menuRef = useRef(null);
  const previousPathRef = useRef(location.pathname);
  const collapsed = prefs.sidebar_collapsed && !mobile;
  const tr = (key, fallback) => { const result = t(key); return !result || result === key ? fallback : result; };
  const activeItem = findActiveNavItem(location.pathname);
  const subPage = activeItem ? null : findSubPage(location.pathname);
  // A sub-page belongs to the section (and open group) of the entry it is opened from.
  const sectionItem = activeItem || ALL_ITEMS.find(item => item.to === subPage?.parent);
  const activeSection = NAV_SECTIONS.find(section => section.items.includes(sectionItem));
  const activeGroup = GROUPS.find(section => section.items.some(item => item.to === sectionItem?.to))?.labelKey;
  const currentPageTitle = activeItem ? tr(activeItem.labelKey, activeItem.fallback)
    : subPage ? tr(subPage.labelKey, subPage.fallback) : tr('pages.notFound.title', 'Seite nicht gefunden');

  // /bookings?neu=1 (a quick action of the search): drop the marker so a reload or a later
  // filter change does not open the form again, then ask the page's list for its New form.
  useEffect(() => {
    const params = new URLSearchParams(location.search);
    if (params.get('neu') !== '1') { dropNewEntry(location.pathname); return; }
    params.delete('neu');
    const { prefill, ...state } = location.state || {};
    navigate({ pathname: location.pathname, search: params.toString() ? `?${params}` : '', hash: location.hash },
      { replace: true, state: Object.keys(state).length ? state : null });
    if (!requestNewEntry(prefill)) holdNewEntry(location.pathname, prefill);
  }, [location, navigate]);

  // "?" shows the shortcuts, Alt+N asks the page's list for its New form. Never while typing
  // or while a dialog is open (its own keys apply there).
  useEffect(() => {
    const keydown = event => {
      if (event.defaultPrevented || event.ctrlKey || event.metaKey || isEditable(event.target)) return;
      if (document.querySelector('[aria-modal="true"]')) return;
      if (event.key === '?') { event.preventDefault(); setShowShortcuts(true); }
      else if (event.altKey && event.code === 'KeyN') { event.preventDefault(); requestNewEntry(); }
    };
    document.addEventListener('keydown', keydown);
    return () => document.removeEventListener('keydown', keydown);
  }, []);

  // The browser tab and history name the page, so several open tabs can be told apart.
  useEffect(() => { document.title = `${currentPageTitle} · ImmoManager Pro`; }, [currentPageTitle]);

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
      <a className="skip-to-content" href="#main-content"
        onClick={event => { event.preventDefault(); document.getElementById('main-content')?.focus(); }}>
        {words.skip}
      </a>
      <aside ref={sidebarRef} className="sidebar" role={mobileNavOpen ? 'dialog' : undefined}
        aria-modal={mobileNavOpen ? true : undefined} aria-label={words.navigation} inert={mobile && !mobileNavOpen ? true : undefined}>
        <div className="sidebar-header">
          <div className="sidebar-logo" aria-hidden="true">IM</div>
          <div className="sidebar-brand"><span className="sidebar-brand-name">ImmoManager</span><span className="sidebar-brand-sub">PRO · {words.workspace}</span></div>
          {mobile && <button ref={closeRef} type="button" className="sidebar-mobile-close" onClick={() => setMobileNavOpen(false)} aria-label={words.close}><CloseIcon size={20} /></button>}
        </div>
        <nav className="sidebar-nav" id="primary-navigation" aria-label={words.navigation}>
          <div className="nav-primary">{PRIMARY_ITEMS.map(navItem)}</div>
          {favoriteItems.length > 0 && <>
            <div className="sidebar-section-label">{words.favorites}</div>
            <div className="nav-favorites">{favoriteItems.map(navItem)}</div>
          </>}
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
      <main id="main-content" className="main-content" tabIndex={-1} inert={mobileNavOpen ? true : undefined}>
        <div className="top-bar">
          <div className="top-bar-left">
            {mobile && <button ref={menuRef} type="button" className="top-bar-mobile-toggle" onClick={() => setMobileNavOpen(true)} aria-controls="primary-navigation" aria-expanded={mobileNavOpen} aria-label={words.open}><MenuIcon size={20} /></button>}
            <div className="top-bar-page-title"><span className="shell-context">{activeSection ? tr(activeSection.labelKey, activeSection.fallback) : words.workspace}</span><span className="shell-context-divider" aria-hidden="true">/</span><span>{currentPageTitle}</span>
              {activeItem && PINNABLE_PATHS.includes(activeItem.to) && (() => {
                const pinned = favorites.includes(activeItem.to);
                return <button type="button" className={`favorite-toggle${pinned ? ' is-pinned' : ''}`} aria-pressed={pinned}
                  aria-label={`${pinned ? words.unpin : words.pin}: ${currentPageTitle}`} title={pinned ? words.unpin : words.pin}
                  onClick={() => toggleFavorite(activeItem.to)}><Star size={15} aria-hidden="true" fill={pinned ? 'currentColor' : 'none'} /></button>;
              })()}
            </div>
          </div>
          <SearchBar />
          <div className="top-bar-utilities"><QuickAccess /><TestVersionBadge />
            <button type="button" className="top-bar-icon-btn top-bar-shortcuts" onClick={() => setShowShortcuts(true)} title={`${words.shortcuts} (?)`} aria-label={words.shortcuts}><Keyboard size={18} aria-hidden="true" /></button>
            <TutorialButton /><NotificationBell /></div>
        </div>
        <div className="main-content-body">
          <h1 className="page-title page-title-auto">{currentPageTitle}</h1>
          <Outlet />
        </div>
      </main>
      {showShortcuts && <ShortcutHelp onClose={() => setShowShortcuts(false)} />}
    </div>
  );
}
