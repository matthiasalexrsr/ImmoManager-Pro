function asNumber(value) {
  const numberValue = Number(value);
  return Number.isFinite(numberValue) ? numberValue : 0;
}

function asArray(value) {
  return Array.isArray(value) ? value : [];
}

function buildStep(labelKey, fallback, done, count, to) {
  return {
    labelKey,
    fallback,
    done: Boolean(done),
    count: asNumber(count),
    to,
  };
}

function progressFor(steps) {
  if (!steps.length) return 0;
  return Math.round((steps.filter(step => step.done).length / steps.length) * 100);
}

function statusFor(progress, hasWarning = false) {
  if (hasWarning) return 'attention';
  if (progress >= 100) return 'complete';
  if (progress === 0) return 'blocked';
  return 'ready';
}

function sumAgingBuckets(aging) {
  const buckets = aging?.buckets || {};
  return asNumber(buckets.days1to30)
    + asNumber(buckets.days31to60)
    + asNumber(buckets.days61to90)
    + asNumber(buckets.days90plus);
}

function withComputedProgress(item) {
  const progress = progressFor(item.steps);
  return {
    ...item,
    progress,
    status: statusFor(progress, item.hasWarning),
  };
}

export function buildDashboardWorkflow({ stats = {}, aging = null, expiring = null, notifications = [] } = {}) {
  const portfolios = asNumber(stats.portfolios);
  const properties = asNumber(stats.properties);
  const units = asNumber(stats.units);
  const vacantUnits = Math.max(0, units - asNumber(stats.unitsOccupied) - asNumber(stats.unitsReserved));
  const tenants = asNumber(stats.tenants);
  const activeContracts = asNumber(stats.contractsActive);
  const accounts = asNumber(stats.accounts);
  const rentCharges = asNumber(stats.rentCharges);
  const openReceivables = asNumber(stats.openReceivables || aging?.openTotal);
  const overdueReceivables = asNumber(stats.overdueReceivables) + sumAgingBuckets(aging);
  const openInvoices = asNumber(stats.openInvoices);
  const documents = asNumber(stats.documents);
  const openMaintenance = asNumber(stats.openMaintenance);
  const openTasks = asNumber(stats.openTasks);
  const billingPeriods = asNumber(stats.billingPeriods);
  const allocationKeys = asNumber(stats.allocationKeys);
  const utilityStatements = asNumber(stats.utilityStatements);
  const expiringContracts = asArray(expiring?.contracts).length;
  const unreadNotifications = asNumber(stats.unreadNotifications) || asArray(notifications).length;

  const workflows = [
    withComputedProgress({
      id: 'portfolio',
      icon: 'portfolio',
      titleKey: 'pages.dashboard.workflow.portfolio.title',
      titleFallback: 'Bestand aufbauen',
      descriptionKey: 'pages.dashboard.workflow.portfolio.description',
      descriptionFallback: 'Portfolios, Immobilien und Einheiten als belastbare Verwaltungsbasis.',
      actionTo: portfolios === 0 ? '/portfolios' : properties === 0 ? '/properties' : '/units',
      actionKey: portfolios === 0
        ? 'pages.dashboard.workflow.actions.createPortfolio'
        : properties === 0
          ? 'pages.dashboard.workflow.actions.createProperty'
          : 'pages.dashboard.workflow.actions.manageUnits',
      actionFallback: portfolios === 0 ? 'Portfolio anlegen' : properties === 0 ? 'Immobilie anlegen' : 'Einheiten prüfen',
      metricKey: 'pages.dashboard.workflow.metrics.units',
      metricFallback: '{{count}} Einheiten',
      metricCount: units,
      steps: [
        buildStep('pages.dashboard.workflow.steps.portfolios', 'Portfolios', portfolios > 0, portfolios, '/portfolios'),
        buildStep('pages.dashboard.workflow.steps.properties', 'Immobilien', properties > 0, properties, '/properties'),
        buildStep('pages.dashboard.workflow.steps.units', 'Einheiten', units > 0, units, '/units'),
      ],
    }),
    withComputedProgress({
      id: 'rental',
      icon: 'rental',
      titleKey: 'pages.dashboard.workflow.rental.title',
      titleFallback: 'Vermietung sichern',
      descriptionKey: 'pages.dashboard.workflow.rental.description',
      descriptionFallback: 'Mieter, Verträge und freie Einheiten im Blick behalten.',
      actionTo: tenants === 0 ? '/tenants' : activeContracts === 0 ? '/contract-wizard' : '/contracts',
      actionKey: tenants === 0
        ? 'pages.dashboard.workflow.actions.createTenant'
        : activeContracts === 0
          ? 'pages.dashboard.workflow.actions.createContract'
          : 'pages.dashboard.workflow.actions.reviewContracts',
      actionFallback: tenants === 0 ? 'Mieter anlegen' : activeContracts === 0 ? 'Vertrag erstellen' : 'Verträge prüfen',
      metricKey: 'pages.dashboard.workflow.metrics.vacancies',
      metricFallback: '{{count}} freie Einheiten',
      metricCount: vacantUnits,
      hasWarning: vacantUnits > 0 || expiringContracts > 0,
      steps: [
        buildStep('pages.dashboard.workflow.steps.units', 'Einheiten', units > 0, units, '/units'),
        buildStep('pages.dashboard.workflow.steps.tenants', 'Mieter', tenants > 0, tenants, '/tenants'),
        buildStep('pages.dashboard.workflow.steps.activeContracts', 'Aktive Verträge', activeContracts > 0, activeContracts, '/contracts'),
      ],
    }),
    withComputedProgress({
      id: 'finance',
      icon: 'finance',
      titleKey: 'pages.dashboard.workflow.finance.title',
      titleFallback: 'Zahlungen steuern',
      descriptionKey: 'pages.dashboard.workflow.finance.description',
      descriptionFallback: 'Sollstellungen, offene Forderungen und Rechnungen aktiv nachhalten.',
      actionTo: overdueReceivables > 0 || openReceivables > 0 ? '/receivables' : '/rent-charges',
      actionKey: overdueReceivables > 0 || openReceivables > 0
        ? 'pages.dashboard.workflow.actions.reviewReceivables'
        : 'pages.dashboard.workflow.actions.createCharges',
      actionFallback: overdueReceivables > 0 || openReceivables > 0 ? 'Forderungen prüfen' : 'Sollstellungen öffnen',
      metricKey: 'pages.dashboard.workflow.metrics.openReceivables',
      metricFallback: '{{count}} offene Forderungen',
      metricCount: openReceivables,
      hasWarning: overdueReceivables > 0 || openReceivables > 0 || openInvoices > 0,
      steps: [
        buildStep('pages.dashboard.workflow.steps.accounts', 'Konten', accounts > 0, accounts, '/accounts'),
        buildStep('pages.dashboard.workflow.steps.rentCharges', 'Sollstellungen', rentCharges > 0 || activeContracts > 0, rentCharges, '/rent-charges'),
        buildStep('pages.dashboard.workflow.steps.receivablesClear', 'Forderungen geklärt', openReceivables === 0, openReceivables, '/receivables'),
      ],
    }),
    withComputedProgress({
      id: 'billing',
      icon: 'billing',
      titleKey: 'pages.dashboard.workflow.billing.title',
      titleFallback: 'Abrechnung abschließen',
      descriptionKey: 'pages.dashboard.workflow.billing.description',
      descriptionFallback: 'Verteilerschlüssel, Rechnungen und Abrechnungsperioden revisionsfähig führen.',
      actionTo: allocationKeys === 0 ? '/allocation-keys' : billingPeriods === 0 ? '/statements' : '/statements',
      actionKey: allocationKeys === 0
        ? 'pages.dashboard.workflow.actions.createAllocationKeys'
        : 'pages.dashboard.workflow.actions.openStatements',
      actionFallback: allocationKeys === 0 ? 'Schlüssel pflegen' : 'Abrechnung öffnen',
      metricKey: 'pages.dashboard.workflow.metrics.openInvoices',
      metricFallback: '{{count}} offene Rechnungen',
      metricCount: openInvoices,
      hasWarning: openInvoices > 0,
      steps: [
        buildStep('pages.dashboard.workflow.steps.allocationKeys', 'Verteilerschlüssel', allocationKeys > 0, allocationKeys, '/allocation-keys'),
        buildStep('pages.dashboard.workflow.steps.invoices', 'Rechnungen', openInvoices === 0, openInvoices, '/invoices'),
        buildStep('pages.dashboard.workflow.steps.statements', 'Abrechnungen', billingPeriods > 0 || utilityStatements > 0, utilityStatements, '/statements'),
      ],
    }),
    withComputedProgress({
      id: 'operations',
      icon: 'operations',
      titleKey: 'pages.dashboard.workflow.operations.title',
      titleFallback: 'Betrieb erledigen',
      descriptionKey: 'pages.dashboard.workflow.operations.description',
      descriptionFallback: 'Dokumente, Aufgaben und Instandhaltung ohne stille Rückstände bearbeiten.',
      actionTo: openMaintenance > 0 ? '/maintenance' : openTasks > 0 ? '/tasks' : '/documents',
      actionKey: openMaintenance > 0
        ? 'pages.dashboard.workflow.actions.reviewMaintenance'
        : openTasks > 0
          ? 'pages.dashboard.workflow.actions.reviewTasks'
          : 'pages.dashboard.workflow.actions.reviewDocuments',
      actionFallback: openMaintenance > 0 ? 'Wartung prüfen' : openTasks > 0 ? 'Aufgaben öffnen' : 'Dokumente prüfen',
      metricKey: 'pages.dashboard.workflow.metrics.openTasks',
      metricFallback: '{{count}} offene Aufgaben',
      metricCount: openTasks,
      hasWarning: openMaintenance > 0 || openTasks > 0 || unreadNotifications > 0,
      steps: [
        buildStep('pages.dashboard.workflow.steps.documents', 'Dokumente', documents > 0, documents, '/documents'),
        buildStep('pages.dashboard.workflow.steps.maintenanceClear', 'Wartung geklärt', openMaintenance === 0, openMaintenance, '/maintenance'),
        buildStep('pages.dashboard.workflow.steps.tasksClear', 'Aufgaben geklärt', openTasks === 0, openTasks, '/tasks'),
      ],
    }),
  ];

  const attentionItems = [
    overdueReceivables > 0 && {
      id: 'overdue-receivables',
      tone: 'critical',
      icon: 'invoice',
      titleKey: 'pages.dashboard.attention.overdueReceivables',
      titleFallback: 'Überfällige Forderungen',
      value: overdueReceivables,
      to: '/receivables',
    },
    openReceivables > 0 && {
      id: 'open-receivables',
      tone: 'warning',
      icon: 'account',
      titleKey: 'pages.dashboard.attention.openReceivables',
      titleFallback: 'Offene Forderungen',
      value: openReceivables,
      to: '/receivables',
    },
    expiringContracts > 0 && {
      id: 'expiring-contracts',
      tone: 'warning',
      icon: 'contract',
      titleKey: 'pages.dashboard.attention.expiringContracts',
      titleFallback: 'Auslaufende Verträge',
      value: expiringContracts,
      to: '/contracts',
    },
    openMaintenance > 0 && {
      id: 'open-maintenance',
      tone: 'warning',
      icon: 'maintenance',
      titleKey: 'pages.dashboard.attention.openMaintenance',
      titleFallback: 'Offene Instandhaltung',
      value: openMaintenance,
      to: '/maintenance',
    },
    openTasks > 0 && {
      id: 'open-tasks',
      tone: 'info',
      icon: 'document',
      titleKey: 'pages.dashboard.attention.openTasks',
      titleFallback: 'Offene Aufgaben',
      value: openTasks,
      to: '/tasks',
    },
    unreadNotifications > 0 && {
      id: 'unread-notifications',
      tone: 'info',
      icon: 'document',
      titleKey: 'pages.dashboard.attention.unreadNotifications',
      titleFallback: 'Ungelesene Hinweise',
      value: unreadNotifications,
      to: '/messages',
    },
  ].filter(Boolean);

  return { workflows, attentionItems };
}
