// The app's pages, as the sidebar groups them. The global search offers the same entries,
// so a page can be opened by typing its name instead of opening its group.
import {
  DashboardIcon, PortfolioIcon, PropertyIcon, UnitIcon,
  TenantIcon, ContractIcon, AccountIcon, BookingIcon,
  InvoiceIcon, MaintenanceIcon, TaskIcon, DocumentIcon,
  SunIcon, MoonIcon, LogoutIcon, ChevronLeftIcon, ChevronRightIcon,
  RentIcon, MeterIcon, ContactIcon, StatementIcon, MessageIcon, SettingsIcon,
  CategoryIcon, DepositIcon, InsuranceIcon, IntegrationIcon,
  CalendarIcon, ChartIcon, SearchIcon, MenuIcon, CloseIcon, HelpIcon, BellIcon,
} from './Icons';

export const NAV_SECTIONS = [
  {
    labelKey: 'navigation.sections.overview',
    fallback: 'Overview',
    items: [
      { to: '/', labelKey: 'navigation.main.dashboard', fallback: 'Dashboard', icon: DashboardIcon },
      { to: '/work-center', labelKey: 'navigation.main.workCenter', fallback: 'Arbeitszentrale', icon: TaskIcon },
      { to: '/assistant', labelKey: 'navigation.main.assistant', fallback: 'KI-Assistent', icon: MessageIcon },
      { to: '/notifications', labelKey: 'navigation.main.notifications', fallback: 'Benachrichtigungen', icon: BellIcon },
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
      { to: '/reports', labelKey: 'navigation.main.reports', fallback: 'Auswertungen', icon: ChartIcon },
      { to: '/tax-exports', labelKey: 'navigation.main.taxExports', fallback: 'Steueraufbereitung / DATEV', icon: ChartIcon },
      { to: '/accounts', labelKey: 'finance.accounts.title', fallback: 'Konten', icon: AccountIcon },
      { to: '/bookings', labelKey: 'finance.bookings.title', fallback: 'Buchungen', icon: BookingIcon },
      { to: '/invoices', labelKey: 'finance.invoices.title', fallback: 'Rechnungen', icon: InvoiceIcon },
      { to: '/invoice-review', labelKey: 'navigation.main.invoiceReview', fallback: 'Rechnungsprüfung', icon: InvoiceIcon },
      { to: '/rent-overview', labelKey: 'navigation.main.rentOverview', fallback: 'Mietübersicht', icon: RentIcon },
      { to: '/statements', labelKey: 'navigation.main.statements', fallback: 'Abrechnungen', icon: StatementIcon },
      { to: '/receivables', labelKey: 'navigation.main.receivables', fallback: 'Forderungen', icon: InvoiceIcon },
      { to: '/dunning', labelKey: 'navigation.main.dunning', fallback: 'Mahnwesen', icon: InvoiceIcon },
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
      { to: '/integration-connections', labelKey: 'navigation.main.connectionWorkspace', fallback: 'Verbindungen und Vorgänge', icon: IntegrationIcon },
      { to: '/escalation-rules', labelKey: 'navigation.main.escalationRules', fallback: 'Eskalationsregeln', icon: MaintenanceIcon },
      { to: '/notification-templates', labelKey: 'navigation.main.notificationTemplates', fallback: 'Benachrichtigungsvorlagen', icon: MessageIcon },
      { to: '/history', labelKey: 'navigation.main.history', fallback: 'Änderungsprotokoll', icon: DocumentIcon },
      { to: '/settings', labelKey: 'navigation.main.settings', fallback: 'Einstellungen', icon: SettingsIcon },
    ],
  },
];

// Frequent "new" entries the global search offers directly. `?neu=1` makes the page's list
// open its New form once (see DataTable); the contract wizard is a page of its own.
export const QUICK_ACTIONS = [
  { to: '/bookings?neu=1', area: '/bookings', labelKey: 'navigation.actions.booking', fallback: 'Neue Buchung', icon: BookingIcon },
  { to: '/tasks?neu=1', area: '/tasks', labelKey: 'navigation.actions.task', fallback: 'Neue Aufgabe', icon: TaskIcon },
  { to: '/invoices?neu=1', area: '/invoices', labelKey: 'navigation.actions.invoice', fallback: 'Neue Rechnung', icon: InvoiceIcon },
  { to: '/contacts?neu=1', area: '/contacts', labelKey: 'navigation.actions.contact', fallback: 'Neuer Kontakt', icon: ContactIcon },
  { to: '/maintenance?neu=1', area: '/maintenance', labelKey: 'navigation.actions.maintenance', fallback: 'Neuer Wartungsfall', icon: MaintenanceIcon },
  { to: '/calendar?neu=1', area: '/calendar', labelKey: 'navigation.actions.event', fallback: 'Neuer Termin', icon: CalendarIcon },
  { to: '/receivables?neu=1', area: '/receivables', labelKey: 'navigation.actions.receivable', fallback: 'Neue Forderung', icon: InvoiceIcon },
  { to: '/units?neu=1', area: '/units', labelKey: 'navigation.actions.unit', fallback: 'Neue Einheit', icon: UnitIcon },
  { to: '/leads?neu=1', area: '/leads', labelKey: 'navigation.actions.lead', fallback: 'Neuer Interessent', icon: TenantIcon },
  { to: '/contract-wizard', area: '/contracts', labelKey: 'navigation.actions.contract', fallback: 'Neuer Mietvertrag', icon: ContractIcon },
];

// Pages without their own sidebar entry. The top bar names them and places them in the
// section of the entry they are opened from (instead of "Arbeitsplatz / Dashboard").
export const SUB_PAGES = [
  { to: '/document-queue', parent: '/work-center', labelKey: 'navigation.sub.documentQueue', fallback: 'Dokumenteneingang' },
  { to: '/duplicate-check', parent: '/work-center', labelKey: 'navigation.sub.duplicateCheck', fallback: 'Dubletten prüfen' },
  { to: '/teha', parent: '/integration-connections', labelKey: 'navigation.sub.teha', fallback: 'TEHA Kundenportal' },
];
