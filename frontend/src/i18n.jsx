/* eslint-disable react-refresh/only-export-components */
import { createContext, useContext, useState, useEffect, useCallback } from 'react';

const I18nContext = createContext(null);

// Cache loaded translations
const translationCache = {};

const BUILTIN_TRANSLATIONS = {
  'de-DE': {
    navigation: {
      main: {
        contractWizard: 'Mietvertrag-Wizard',
        notificationTemplates: 'Benachrichtigungsvorlagen',
      },
    },
    contractWizard: {
      description: 'Erstellen Sie Schritt fuer Schritt einen rechtssicheren Mietvertrag.',
    },
    pages: {
      dashboard: {
        process: {
          title: 'Kernprozess',
          subtitle: 'Objekt -> Einheit -> Mieter -> Vertrag -> Sollstellung -> Zahlung -> Mahnung',
          nextLabel: 'Naechster Schritt',
          nextAttention: 'Dringendster Blocker',
          complete: 'Alles bereit',
          steps: {
            property: 'Objekt',
            unit: 'Einheit',
            tenant: 'Mieter',
            contract: 'Vertrag',
            charge: 'Sollstellung',
            payment: 'Zahlung',
            dunning: 'Mahnung',
          },
          actions: {
            createProperty: 'Objekt anlegen',
            createUnit: 'Einheit anlegen',
            createTenant: 'Mieter anlegen',
            createContract: 'Vertrag erstellen',
            createCharge: 'Sollstellung erzeugen',
            matchPayment: 'Zahlung zuordnen',
            createDunning: 'Mahnung vorbereiten',
            reviewDunning: 'Mahnstatus pruefen',
          },
        },
        workflow: {
          title: 'Arbeitszentrale',
          subtitle: 'Gefuehrte Prozesssicht ueber Bestand, Vermietung, Finanzen, Abrechnung und Betrieb.',
          configure: 'Arbeitsweise anpassen',
          progress: 'Fortschritt',
          status: {
            complete: 'Bereit',
            attention: 'Pruefen',
            blocked: 'Starten',
            ready: 'Aktiv',
          },
          portfolio: {
            title: 'Bestand aufbauen',
            description: 'Portfolios, Immobilien und Einheiten als belastbare Verwaltungsbasis.',
          },
          rental: {
            title: 'Vermietung sichern',
            description: 'Mieter, Vertraege und freie Einheiten im Blick behalten.',
          },
          finance: {
            title: 'Zahlungen steuern',
            description: 'Sollstellungen, offene Forderungen und Rechnungen aktiv nachhalten.',
          },
          billing: {
            title: 'Abrechnung abschliessen',
            description: 'Verteilerschluessel, Rechnungen und Abrechnungsperioden revisionsfaehig fuehren.',
          },
          operations: {
            title: 'Betrieb erledigen',
            description: 'Dokumente, Aufgaben und Instandhaltung ohne stille Rueckstaende bearbeiten.',
          },
          actions: {
            createPortfolio: 'Portfolio anlegen',
            createProperty: 'Immobilie anlegen',
            manageUnits: 'Einheiten pruefen',
            createTenant: 'Mieter anlegen',
            createContract: 'Vertrag erstellen',
            reviewContracts: 'Vertraege pruefen',
            reviewReceivables: 'Forderungen pruefen',
            createCharges: 'Sollstellungen oeffnen',
            createAllocationKeys: 'Schluessel pflegen',
            reviewPreflight: 'Preflight pruefen',
            openStatements: 'Abrechnung oeffnen',
            reviewMaintenance: 'Wartung pruefen',
            reviewTasks: 'Aufgaben oeffnen',
            reviewDocuments: 'Dokumente pruefen',
          },
          metrics: {
            units: '{{count}} Einheiten',
            vacancies: '{{count}} freie Einheiten',
            openReceivables: '{{count}} offene Forderungen',
            openInvoices: '{{count}} offene Rechnungen',
            openTasks: '{{count}} offene Aufgaben',
          },
          steps: {
            portfolios: 'Portfolios',
            properties: 'Immobilien',
            units: 'Einheiten',
            tenants: 'Mieter',
            activeContracts: 'Aktive Vertraege',
            accounts: 'Konten',
            rentCharges: 'Sollstellungen',
            receivablesClear: 'Forderungen geklaert',
            allocationKeys: 'Verteilerschluessel',
            invoices: 'Rechnungen',
            statements: 'Abrechnungen',
            documents: 'Dokumente',
            maintenanceClear: 'Wartung geklaert',
            tasksClear: 'Aufgaben geklaert',
          },
        },
        attention: {
          title: 'Heute wichtig',
          subtitle: 'Die naechsten operativen Blocker in Reihenfolge der Dringlichkeit.',
          emptyTitle: 'Alles im gruenen Bereich',
          emptyText: 'Keine akuten Rueckstaende aus den aktuellen Dashboard-Daten.',
          overdueReceivables: 'Ueberfaellige Forderungen',
          dunningReceivables: 'Offene Mahnungen',
          openReceivables: 'Offene Forderungen',
          billingPreflightBlockers: 'Abrechnungen mit Preflight-Fehlern',
          maintenanceEscalations: 'Instandhaltung mit Eskalation',
          expiringContracts: 'Auslaufende Vertraege',
          missingContractDocuments: 'Fehlende Vertragsdokumente',
          openMaintenance: 'Offene Instandhaltung',
          openTasks: 'Offene Aufgaben',
          unreadNotifications: 'Ungelesene Hinweise',
        },
      },
    },
  },
  'en-US': {
    navigation: {
      main: {
        contractWizard: 'Lease Wizard',
        notificationTemplates: 'Notification Templates',
      },
    },
    contractWizard: {
      description: 'Create a legally sound lease agreement step by step.',
    },
    pages: {
      dashboard: {
        process: {
          title: 'Core process',
          subtitle: 'Property -> Unit -> Tenant -> Contract -> Charge -> Payment -> Dunning',
          nextLabel: 'Next step',
          nextAttention: 'Most urgent blocker',
          complete: 'Everything ready',
          steps: {
            property: 'Property',
            unit: 'Unit',
            tenant: 'Tenant',
            contract: 'Contract',
            charge: 'Charge',
            payment: 'Payment',
            dunning: 'Dunning',
          },
          actions: {
            createProperty: 'Create property',
            createUnit: 'Create unit',
            createTenant: 'Create tenant',
            createContract: 'Create contract',
            createCharge: 'Create rent charge',
            matchPayment: 'Match payment',
            createDunning: 'Prepare dunning',
            reviewDunning: 'Review dunning status',
          },
        },
        workflow: {
          title: 'Work Center',
          subtitle: 'Guided process view across portfolio, leasing, finance, billing, and operations.',
          configure: 'Adjust workflow',
          progress: 'Progress',
          status: {
            complete: 'Ready',
            attention: 'Review',
            blocked: 'Start',
            ready: 'Active',
          },
          portfolio: {
            title: 'Build portfolio',
            description: 'Portfolios, properties, and units as the reliable management base.',
          },
          rental: {
            title: 'Secure leasing',
            description: 'Keep tenants, contracts, and vacancies in view.',
          },
          finance: {
            title: 'Control payments',
            description: 'Track rent charges, receivables, and invoices actively.',
          },
          billing: {
            title: 'Close statements',
            description: 'Maintain allocation keys, invoices, and billing periods with revisions.',
          },
          operations: {
            title: 'Run operations',
            description: 'Process documents, tasks, and maintenance without hidden backlog.',
          },
          actions: {
            createPortfolio: 'Create portfolio',
            createProperty: 'Create property',
            manageUnits: 'Review units',
            createTenant: 'Create tenant',
            createContract: 'Create contract',
            reviewContracts: 'Review contracts',
            reviewReceivables: 'Review receivables',
            createCharges: 'Open rent charges',
            createAllocationKeys: 'Maintain keys',
            reviewPreflight: 'Review preflight',
            openStatements: 'Open statements',
            reviewMaintenance: 'Review maintenance',
            reviewTasks: 'Open tasks',
            reviewDocuments: 'Review documents',
          },
          metrics: {
            units: '{{count}} units',
            vacancies: '{{count}} vacant units',
            openReceivables: '{{count}} open receivables',
            openInvoices: '{{count}} open invoices',
            openTasks: '{{count}} open tasks',
          },
          steps: {
            portfolios: 'Portfolios',
            properties: 'Properties',
            units: 'Units',
            tenants: 'Tenants',
            activeContracts: 'Active contracts',
            accounts: 'Accounts',
            rentCharges: 'Rent charges',
            receivablesClear: 'Receivables clear',
            allocationKeys: 'Allocation keys',
            invoices: 'Invoices',
            statements: 'Statements',
            documents: 'Documents',
            maintenanceClear: 'Maintenance clear',
            tasksClear: 'Tasks clear',
          },
        },
        attention: {
          title: 'Important today',
          subtitle: 'The next operational blockers ordered by urgency.',
          emptyTitle: 'Everything looks good',
          emptyText: 'No urgent backlog in the current dashboard data.',
          overdueReceivables: 'Overdue receivables',
          dunningReceivables: 'Open dunning',
          openReceivables: 'Open receivables',
          billingPreflightBlockers: 'Statements with preflight errors',
          maintenanceEscalations: 'Maintenance escalations',
          expiringContracts: 'Expiring contracts',
          missingContractDocuments: 'Missing contract documents',
          openMaintenance: 'Open maintenance',
          openTasks: 'Open tasks',
          unreadNotifications: 'Unread notices',
        },
      },
    },
  },
  'es-ES': {
    navigation: {
      main: {
        contractWizard: 'Asistente de contrato',
        notificationTemplates: 'Plantillas de notificacion',
      },
    },
    contractWizard: {
      description: 'Cree paso a paso un contrato de arrendamiento juridicamente solido.',
    },
    pages: {
      dashboard: {
        process: {
          title: 'Proceso principal',
          subtitle: 'Inmueble -> Unidad -> Inquilino -> Contrato -> Cargo -> Pago -> Reclamacion',
          nextLabel: 'Siguiente paso',
          nextAttention: 'Bloqueo mas urgente',
          complete: 'Todo listo',
          steps: {
            property: 'Inmueble',
            unit: 'Unidad',
            tenant: 'Inquilino',
            contract: 'Contrato',
            charge: 'Cargo',
            payment: 'Pago',
            dunning: 'Reclamacion',
          },
          actions: {
            createProperty: 'Crear inmueble',
            createUnit: 'Crear unidad',
            createTenant: 'Crear inquilino',
            createContract: 'Crear contrato',
            createCharge: 'Crear cargo',
            matchPayment: 'Conciliar pago',
            createDunning: 'Preparar reclamacion',
            reviewDunning: 'Revisar estado',
          },
        },
        workflow: {
          title: 'Centro de trabajo',
          subtitle: 'Vista guiada de procesos para cartera, alquileres, finanzas, liquidaciones y operaciones.',
          configure: 'Ajustar flujo',
          progress: 'Progreso',
          status: {
            complete: 'Listo',
            attention: 'Revisar',
            blocked: 'Iniciar',
            ready: 'Activo',
          },
          portfolio: {
            title: 'Crear cartera',
            description: 'Carteras, inmuebles y unidades como base fiable de gestion.',
          },
          rental: {
            title: 'Asegurar alquileres',
            description: 'Mantenga visibles inquilinos, contratos y vacantes.',
          },
          finance: {
            title: 'Controlar pagos',
            description: 'Controle cargos de alquiler, cobros pendientes y facturas.',
          },
          billing: {
            title: 'Cerrar liquidaciones',
            description: 'Gestione claves de reparto, facturas y periodos con revision.',
          },
          operations: {
            title: 'Gestionar operacion',
            description: 'Procese documentos, tareas y mantenimiento sin retrasos ocultos.',
          },
          actions: {
            createPortfolio: 'Crear cartera',
            createProperty: 'Crear inmueble',
            manageUnits: 'Revisar unidades',
            createTenant: 'Crear inquilino',
            createContract: 'Crear contrato',
            reviewContracts: 'Revisar contratos',
            reviewReceivables: 'Revisar cobros',
            createCharges: 'Abrir cargos',
            createAllocationKeys: 'Mantener claves',
            reviewPreflight: 'Revisar preflight',
            openStatements: 'Abrir liquidaciones',
            reviewMaintenance: 'Revisar mantenimiento',
            reviewTasks: 'Abrir tareas',
            reviewDocuments: 'Revisar documentos',
          },
          metrics: {
            units: '{{count}} unidades',
            vacancies: '{{count}} unidades vacantes',
            openReceivables: '{{count}} cobros pendientes',
            openInvoices: '{{count}} facturas abiertas',
            openTasks: '{{count}} tareas abiertas',
          },
          steps: {
            portfolios: 'Carteras',
            properties: 'Inmuebles',
            units: 'Unidades',
            tenants: 'Inquilinos',
            activeContracts: 'Contratos activos',
            accounts: 'Cuentas',
            rentCharges: 'Cargos',
            receivablesClear: 'Cobros resueltos',
            allocationKeys: 'Claves de reparto',
            invoices: 'Facturas',
            statements: 'Liquidaciones',
            documents: 'Documentos',
            maintenanceClear: 'Mantenimiento resuelto',
            tasksClear: 'Tareas resueltas',
          },
        },
        attention: {
          title: 'Importante hoy',
          subtitle: 'Los proximos bloqueos operativos por urgencia.',
          emptyTitle: 'Todo esta en orden',
          emptyText: 'No hay retrasos urgentes en los datos actuales.',
          overdueReceivables: 'Cobros vencidos',
          dunningReceivables: 'Reclamaciones abiertas',
          openReceivables: 'Cobros pendientes',
          billingPreflightBlockers: 'Liquidaciones con errores preflight',
          maintenanceEscalations: 'Mantenimiento escalado',
          expiringContracts: 'Contratos por vencer',
          missingContractDocuments: 'Documentos de contrato faltantes',
          openMaintenance: 'Mantenimiento abierto',
          openTasks: 'Tareas abiertas',
          unreadNotifications: 'Avisos sin leer',
        },
      },
    },
  },
};

function getNestedValue(obj, path) {
  return path.split('.').reduce((o, key) => (o && o[key] !== undefined ? o[key] : null), obj);
}

export function useTranslation() {
  const ctx = useContext(I18nContext);
  if (!ctx) return { t: (key) => key, locale: 'de-DE', setLocale: () => {} };
  return ctx;
}

export function I18nProvider({ children }) {
  const [locale, setLocaleState] = useState(() => localStorage.getItem('locale') || 'de-DE');
  const [translations, setTranslations] = useState({});
  const [fallback, setFallback] = useState({});

  // Load a locale's translations
  const loadTranslations = useCallback(async (loc) => {
    if (translationCache[loc]) return translationCache[loc];
    try {
      const res = await fetch(`/i18n/${loc}`);
      if (res.ok) {
        const data = await res.json();
        translationCache[loc] = data;
        return data;
      }
    } catch (err) { console.warn('[i18n] Failed to load locale:', err.message); }
    return {};
  }, []);

  useEffect(() => {
    // Load current locale and German fallback
    Promise.all([
      loadTranslations(locale),
      locale !== 'de-DE' ? loadTranslations('de-DE') : Promise.resolve({}),
    ]).then(([current, fb]) => {
      setTranslations(current);
      setFallback(fb);
    });
  }, [locale, loadTranslations]);

  const setLocale = useCallback((loc) => {
    localStorage.setItem('locale', loc);
    setLocaleState(loc);
  }, []);

  const t = useCallback((key, params) => {
    let value = getNestedValue(translations, key)
      || getNestedValue(fallback, key)
      || getNestedValue(BUILTIN_TRANSLATIONS[locale], key)
      || getNestedValue(BUILTIN_TRANSLATIONS['de-DE'], key)
      || key;
    if (params && typeof value === 'string') {
      Object.entries(params).forEach(([k, v]) => {
        value = value.replace(`{{${k}}}`, v);
      });
    }
    return value;
  }, [translations, fallback, locale]);

  return (
    <I18nContext.Provider value={{ t, locale, setLocale }}>
      {children}
    </I18nContext.Provider>
  );
}
