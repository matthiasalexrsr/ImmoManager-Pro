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

function buildProcessStep(id, labelKey, fallback, done, count, to, options = {}) {
  const tone = options.tone || 'normal';
  const isDone = Boolean(done);
  return {
    id,
    labelKey,
    fallback,
    done: isDone,
    count: asNumber(count),
    to,
    tone,
    status: tone === 'attention' ? 'attention' : isDone ? 'done' : 'active',
    actionKey: options.actionKey,
    actionFallback: options.actionFallback,
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

function buildNextStep(processSteps, attentionItems) {
  const processStep = processSteps.find(step => !step.done || step.tone === 'attention');
  if (processStep) {
    return {
      id: `process-${processStep.id}`,
      tone: processStep.tone === 'attention' ? 'attention' : 'ready',
      labelKey: processStep.actionKey,
      labelFallback: processStep.actionFallback,
      detailKey: processStep.labelKey,
      detailFallback: processStep.fallback,
      value: processStep.count,
      to: processStep.to,
    };
  }

  const attentionItem = attentionItems[0];
  if (!attentionItem) return null;
  return {
    id: `attention-${attentionItem.id}`,
    tone: attentionItem.tone,
    labelKey: attentionItem.titleKey,
    labelFallback: attentionItem.titleFallback,
    detailKey: 'pages.dashboard.process.nextAttention',
    detailFallback: 'Dringendster Blocker',
    value: attentionItem.value,
    to: attentionItem.to,
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
  const paidReceivables = asNumber(stats.paidReceivables);
  const overdueReceivables = asNumber(stats.overdueReceivables) + sumAgingBuckets(aging);
  const dunningReceivables = asNumber(stats.dunningReceivables);
  const openInvoices = asNumber(stats.openInvoices);
  const documents = asNumber(stats.documents);
  const missingContractDocuments = asNumber(stats.missingContractDocuments);
  const openMaintenance = asNumber(stats.openMaintenance);
  const overdueMaintenance = asNumber(stats.overdueMaintenance);
  const maintenanceEscalationCandidates = asNumber(stats.maintenanceEscalationCandidates);
  const openTasks = asNumber(stats.openTasks);
  const billingPeriods = asNumber(stats.billingPeriods);
  const allocationKeys = asNumber(stats.allocationKeys);
  const utilityStatements = asNumber(stats.utilityStatements);
  const billingPreflightBlockers = asNumber(stats.billingPreflightBlockers);
  const billingPreflightWarnings = asNumber(stats.billingPreflightWarnings);
  const expiringContracts = asArray(expiring?.contracts).length;
  const unreadNotifications = asNumber(stats.unreadNotifications) || asArray(notifications).length;

  const processSteps = [
    buildProcessStep(
      'property',
      'pages.dashboard.process.steps.property',
      'Objekt',
      properties > 0,
      properties,
      '/properties',
      {
        actionKey: 'pages.dashboard.process.actions.createProperty',
        actionFallback: 'Objekt anlegen',
      },
    ),
    buildProcessStep(
      'unit',
      'pages.dashboard.process.steps.unit',
      'Einheit',
      units > 0,
      units,
      '/units',
      {
        actionKey: 'pages.dashboard.process.actions.createUnit',
        actionFallback: 'Einheit anlegen',
      },
    ),
    buildProcessStep(
      'tenant',
      'pages.dashboard.process.steps.tenant',
      'Mieter',
      tenants > 0,
      tenants,
      '/tenants',
      {
        actionKey: 'pages.dashboard.process.actions.createTenant',
        actionFallback: 'Mieter anlegen',
      },
    ),
    buildProcessStep(
      'contract',
      'pages.dashboard.process.steps.contract',
      'Vertrag',
      activeContracts > 0,
      activeContracts,
      activeContracts > 0 ? '/contracts' : '/contract-wizard',
      {
        actionKey: 'pages.dashboard.process.actions.createContract',
        actionFallback: 'Vertrag erstellen',
      },
    ),
    buildProcessStep(
      'charge',
      'pages.dashboard.process.steps.charge',
      'Sollstellung',
      rentCharges > 0 || openReceivables > 0 || paidReceivables > 0,
      rentCharges,
      '/rent-charges',
      {
        actionKey: 'pages.dashboard.process.actions.createCharge',
        actionFallback: 'Sollstellung erzeugen',
      },
    ),
    buildProcessStep(
      'payment',
      'pages.dashboard.process.steps.payment',
      'Zahlung',
      paidReceivables > 0 || (rentCharges > 0 && openReceivables === 0 && overdueReceivables === 0),
      paidReceivables,
      '/receivables',
      {
        tone: openReceivables > 0 || overdueReceivables > 0 ? 'attention' : 'normal',
        actionKey: 'pages.dashboard.process.actions.matchPayment',
        actionFallback: 'Zahlung zuordnen',
      },
    ),
    buildProcessStep(
      'dunning',
      'pages.dashboard.process.steps.dunning',
      'Mahnung',
      overdueReceivables === 0 || dunningReceivables > 0,
      dunningReceivables || overdueReceivables,
      '/receivables',
      {
        tone: overdueReceivables > 0 ? 'attention' : 'normal',
        actionKey: overdueReceivables > 0
          ? 'pages.dashboard.process.actions.createDunning'
          : 'pages.dashboard.process.actions.reviewDunning',
        actionFallback: overdueReceivables > 0 ? 'Mahnung vorbereiten' : 'Mahnstatus pruefen',
      },
    ),
  ];

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
      actionFallback: portfolios === 0 ? 'Portfolio anlegen' : properties === 0 ? 'Immobilie anlegen' : 'Einheiten pruefen',
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
      descriptionFallback: 'Mieter, Vertraege und freie Einheiten im Blick behalten.',
      actionTo: tenants === 0 ? '/tenants' : activeContracts === 0 ? '/contract-wizard' : '/contracts',
      actionKey: tenants === 0
        ? 'pages.dashboard.workflow.actions.createTenant'
        : activeContracts === 0
          ? 'pages.dashboard.workflow.actions.createContract'
          : 'pages.dashboard.workflow.actions.reviewContracts',
      actionFallback: tenants === 0 ? 'Mieter anlegen' : activeContracts === 0 ? 'Vertrag erstellen' : 'Vertraege pruefen',
      metricKey: 'pages.dashboard.workflow.metrics.vacancies',
      metricFallback: '{{count}} freie Einheiten',
      metricCount: vacantUnits,
      hasWarning: vacantUnits > 0 || expiringContracts > 0,
      steps: [
        buildStep('pages.dashboard.workflow.steps.units', 'Einheiten', units > 0, units, '/units'),
        buildStep('pages.dashboard.workflow.steps.tenants', 'Mieter', tenants > 0, tenants, '/tenants'),
        buildStep('pages.dashboard.workflow.steps.activeContracts', 'Aktive Vertraege', activeContracts > 0, activeContracts, '/contracts'),
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
      actionFallback: overdueReceivables > 0 || openReceivables > 0 ? 'Forderungen pruefen' : 'Sollstellungen oeffnen',
      metricKey: 'pages.dashboard.workflow.metrics.openReceivables',
      metricFallback: '{{count}} offene Forderungen',
      metricCount: openReceivables,
      hasWarning: overdueReceivables > 0 || dunningReceivables > 0 || openReceivables > 0 || openInvoices > 0,
      steps: [
        buildStep('pages.dashboard.workflow.steps.accounts', 'Konten', accounts > 0, accounts, '/accounts'),
        buildStep('pages.dashboard.workflow.steps.rentCharges', 'Sollstellungen', rentCharges > 0 || activeContracts > 0, rentCharges, '/rent-charges'),
        buildStep('pages.dashboard.workflow.steps.receivablesClear', 'Forderungen geklaert', openReceivables === 0, openReceivables, '/receivables'),
      ],
    }),
    withComputedProgress({
      id: 'billing',
      icon: 'billing',
      titleKey: 'pages.dashboard.workflow.billing.title',
      titleFallback: 'Abrechnung abschliessen',
      descriptionKey: 'pages.dashboard.workflow.billing.description',
      descriptionFallback: 'Verteilerschluessel, Rechnungen und Abrechnungsperioden revisionsfaehig fuehren.',
      actionTo: allocationKeys === 0 ? '/allocation-keys' : '/statements',
      actionKey: allocationKeys === 0
        ? 'pages.dashboard.workflow.actions.createAllocationKeys'
        : billingPreflightBlockers > 0
          ? 'pages.dashboard.workflow.actions.reviewPreflight'
          : 'pages.dashboard.workflow.actions.openStatements',
      actionFallback: allocationKeys === 0
        ? 'Schluessel pflegen'
        : billingPreflightBlockers > 0
          ? 'Preflight pruefen'
          : 'Abrechnung oeffnen',
      metricKey: 'pages.dashboard.workflow.metrics.openInvoices',
      metricFallback: '{{count}} offene Rechnungen',
      metricCount: openInvoices,
      hasWarning: openInvoices > 0 || billingPreflightBlockers > 0 || billingPreflightWarnings > 0,
      steps: [
        buildStep('pages.dashboard.workflow.steps.allocationKeys', 'Verteilerschluessel', allocationKeys > 0, allocationKeys, '/allocation-keys'),
        buildStep('pages.dashboard.workflow.steps.invoices', 'Rechnungen', openInvoices === 0, openInvoices, '/invoices'),
        buildStep(
          'pages.dashboard.workflow.steps.statements',
          'Abrechnungen',
          (billingPeriods > 0 || utilityStatements > 0) && billingPreflightBlockers === 0,
          utilityStatements || billingPreflightBlockers,
          '/statements',
        ),
      ],
    }),
    withComputedProgress({
      id: 'operations',
      icon: 'operations',
      titleKey: 'pages.dashboard.workflow.operations.title',
      titleFallback: 'Betrieb erledigen',
      descriptionKey: 'pages.dashboard.workflow.operations.description',
      descriptionFallback: 'Dokumente, Aufgaben und Instandhaltung ohne stille Rueckstaende bearbeiten.',
      actionTo: openMaintenance > 0 ? '/maintenance' : openTasks > 0 ? '/tasks' : '/documents',
      actionKey: openMaintenance > 0
        ? 'pages.dashboard.workflow.actions.reviewMaintenance'
        : openTasks > 0
          ? 'pages.dashboard.workflow.actions.reviewTasks'
          : 'pages.dashboard.workflow.actions.reviewDocuments',
      actionFallback: openMaintenance > 0 ? 'Wartung pruefen' : openTasks > 0 ? 'Aufgaben oeffnen' : 'Dokumente pruefen',
      metricKey: 'pages.dashboard.workflow.metrics.openTasks',
      metricFallback: '{{count}} offene Aufgaben',
      metricCount: openTasks,
      hasWarning: openMaintenance > 0
        || overdueMaintenance > 0
        || maintenanceEscalationCandidates > 0
        || missingContractDocuments > 0
        || openTasks > 0
        || unreadNotifications > 0,
      steps: [
        buildStep(
          'pages.dashboard.workflow.steps.documents',
          'Dokumente',
          documents > 0 && missingContractDocuments === 0,
          missingContractDocuments || documents,
          '/documents',
        ),
        buildStep(
          'pages.dashboard.workflow.steps.maintenanceClear',
          'Wartung geklaert',
          openMaintenance === 0 && overdueMaintenance === 0,
          overdueMaintenance || openMaintenance,
          '/maintenance',
        ),
        buildStep('pages.dashboard.workflow.steps.tasksClear', 'Aufgaben geklaert', openTasks === 0, openTasks, '/tasks'),
      ],
    }),
  ];

  const attentionItems = [
    overdueReceivables > 0 && {
      id: 'overdue-receivables',
      tone: 'critical',
      icon: 'invoice',
      titleKey: 'pages.dashboard.attention.overdueReceivables',
      titleFallback: 'Ueberfaellige Forderungen',
      value: overdueReceivables,
      to: '/receivables',
    },
    dunningReceivables > 0 && {
      id: 'dunning-receivables',
      tone: 'critical',
      icon: 'invoice',
      titleKey: 'pages.dashboard.attention.dunningReceivables',
      titleFallback: 'Offene Mahnungen',
      value: dunningReceivables,
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
    billingPreflightBlockers > 0 && {
      id: 'billing-preflight-blockers',
      tone: 'critical',
      icon: 'billing',
      titleKey: 'pages.dashboard.attention.billingPreflightBlockers',
      titleFallback: 'Abrechnungen mit Preflight-Fehlern',
      value: billingPreflightBlockers,
      to: '/statements',
    },
    maintenanceEscalationCandidates > 0 && {
      id: 'maintenance-escalations',
      tone: 'critical',
      icon: 'maintenance',
      titleKey: 'pages.dashboard.attention.maintenanceEscalations',
      titleFallback: 'Instandhaltung mit Eskalation',
      value: maintenanceEscalationCandidates,
      to: '/maintenance',
    },
    expiringContracts > 0 && {
      id: 'expiring-contracts',
      tone: 'warning',
      icon: 'contract',
      titleKey: 'pages.dashboard.attention.expiringContracts',
      titleFallback: 'Auslaufende Vertraege',
      value: expiringContracts,
      to: '/contracts',
    },
    missingContractDocuments > 0 && {
      id: 'missing-contract-documents',
      tone: 'warning',
      icon: 'document',
      titleKey: 'pages.dashboard.attention.missingContractDocuments',
      titleFallback: 'Fehlende Vertragsdokumente',
      value: missingContractDocuments,
      to: '/documents',
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

  const nextStep = buildNextStep(processSteps, attentionItems);

  return { workflows, attentionItems, processSteps, nextStep };
}
