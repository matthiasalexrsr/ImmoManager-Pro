import { Link } from 'react-router-dom';
import { buildDashboardWorkflow } from '../utils/dashboardWorkflow';
import './DashboardWorkflow.css';
import {
  AccountIcon,
  ArrowRightIcon,
  ContractIcon,
  DocumentIcon,
  InvoiceIcon,
  MaintenanceIcon,
  PortfolioIcon,
  PropertyIcon,
  StatementIcon,
  TenantIcon,
  UnitIcon,
} from './Icons';

const ICONS = {
  account: AccountIcon,
  billing: StatementIcon,
  charge: AccountIcon,
  contract: ContractIcon,
  document: DocumentIcon,
  dunning: InvoiceIcon,
  finance: AccountIcon,
  invoice: InvoiceIcon,
  maintenance: MaintenanceIcon,
  operations: MaintenanceIcon,
  payment: AccountIcon,
  portfolio: PortfolioIcon,
  property: PropertyIcon,
  rental: ContractIcon,
  tenant: TenantIcon,
  unit: UnitIcon,
};

function interpolate(fallback, params) {
  let value = fallback || '';
  if (!params) return value;
  Object.entries(params).forEach(([key, replacement]) => {
    value = value.replace(`{{${key}}}`, replacement ?? '');
  });
  return value;
}

function translate(t, key, fallback, params) {
  if (!key) return interpolate(fallback, params);
  const value = t(key, params);
  return value === key ? interpolate(fallback, params) : value;
}

function ProcessJourney({ steps, nextStep, t }) {
  return (
    <div className="process-journey" aria-labelledby="process-journey-heading">
      <div className="process-journey-header">
        <div>
          <h3 id="process-journey-heading">
            {translate(t, 'pages.dashboard.process.title', 'Kernprozess')}
          </h3>
          <p>
            {translate(
              t,
              'pages.dashboard.process.subtitle',
              'Objekt -> Einheit -> Mieter -> Vertrag -> Sollstellung -> Zahlung -> Mahnung',
            )}
          </p>
        </div>
        {nextStep ? (
          <Link to={nextStep.to} className={`process-next-action process-next-${nextStep.tone}`}>
            <span>
              <small>{translate(t, 'pages.dashboard.process.nextLabel', 'Naechster Schritt')}</small>
              <strong>{translate(t, nextStep.labelKey, nextStep.labelFallback)}</strong>
            </span>
            <ArrowRightIcon size={16} />
          </Link>
        ) : (
          <div className="process-next-complete">
            <small>{translate(t, 'pages.dashboard.process.nextLabel', 'Naechster Schritt')}</small>
            <strong>{translate(t, 'pages.dashboard.process.complete', 'Alles bereit')}</strong>
          </div>
        )}
      </div>
      <div className="process-steps" role="list">
        {steps.map(step => {
          const Icon = ICONS[step.id] || PortfolioIcon;
          const isCurrent = step.status === 'active' || step.status === 'attention';
          return (
            <Link
              key={step.id}
              to={step.to}
              role="listitem"
              className={`process-step process-step-${step.status}`}
              aria-current={isCurrent ? 'step' : undefined}
            >
              <span className="process-step-icon"><Icon size={18} /></span>
              <span className="process-step-label">{translate(t, step.labelKey, step.fallback)}</span>
              <strong>{step.count}</strong>
            </Link>
          );
        })}
      </div>
    </div>
  );
}

function WorkflowCard({ item, t }) {
  const Icon = ICONS[item.icon] || PortfolioIcon;
  const statusLabel = translate(
    t,
    `pages.dashboard.workflow.status.${item.status}`,
    item.status === 'complete' ? 'Bereit' : item.status === 'attention' ? 'Pruefen' : item.status === 'blocked' ? 'Starten' : 'Aktiv',
  );

  return (
    <article className={`workflow-card workflow-card-${item.status}`}>
      <div className="workflow-card-header">
        <span className="workflow-icon"><Icon size={20} /></span>
        <span className={`workflow-status workflow-status-${item.status}`}>{statusLabel}</span>
      </div>
      <h3>{translate(t, item.titleKey, item.titleFallback)}</h3>
      <p>{translate(t, item.descriptionKey, item.descriptionFallback)}</p>
      <div className="workflow-progress" aria-label={translate(t, 'pages.dashboard.workflow.progress', 'Fortschritt')}>
        <div className="workflow-progress-track">
          <span style={{ width: `${item.progress}%` }} />
        </div>
        <strong>{item.progress}%</strong>
      </div>
      <div className="workflow-metric">
        {translate(t, item.metricKey, item.metricFallback, { count: item.metricCount })}
      </div>
      <div className="workflow-steps">
        {item.steps.map(step => (
          <Link
            key={step.labelKey}
            to={step.to}
            className={`workflow-step ${step.done ? 'done' : ''}`}
          >
            <span className="workflow-step-dot" />
            <span>{translate(t, step.labelKey, step.fallback)}</span>
            <strong>{step.count}</strong>
          </Link>
        ))}
      </div>
      <Link to={item.actionTo} className="workflow-action">
        <span>{translate(t, item.actionKey, item.actionFallback)}</span>
        <ArrowRightIcon size={15} />
      </Link>
    </article>
  );
}

function AttentionPanel({ items, t }) {
  return (
    <aside className="attention-panel" aria-labelledby="attention-heading">
      <div className="workflow-section-header compact">
        <div>
          <h2 id="attention-heading">{translate(t, 'pages.dashboard.attention.title', 'Heute wichtig')}</h2>
          <p>{translate(t, 'pages.dashboard.attention.subtitle', 'Die naechsten operativen Blocker in Reihenfolge der Dringlichkeit.')}</p>
        </div>
      </div>
      {items.length === 0 ? (
        <div className="attention-empty">
          <strong>{translate(t, 'pages.dashboard.attention.emptyTitle', 'Alles im gruenen Bereich')}</strong>
          <span>{translate(t, 'pages.dashboard.attention.emptyText', 'Keine akuten Rueckstaende aus den aktuellen Dashboard-Daten.')}</span>
        </div>
      ) : (
        <div className="attention-list">
          {items.map(item => {
            const Icon = ICONS[item.icon] || DocumentIcon;
            return (
              <Link key={item.id} to={item.to} className={`attention-item attention-${item.tone}`}>
                <span className="attention-icon"><Icon size={18} /></span>
                <span className="attention-title">{translate(t, item.titleKey, item.titleFallback)}</span>
                <strong>{item.value}</strong>
                <ArrowRightIcon size={14} />
              </Link>
            );
          })}
        </div>
      )}
    </aside>
  );
}

export default function DashboardWorkflow({ stats, aging, expiring, notifications, t }) {
  const {
    workflows,
    attentionItems,
    processSteps,
    nextStep,
  } = buildDashboardWorkflow({ stats, aging, expiring, notifications });

  return (
    <section className="workflow-cockpit" aria-labelledby="workflow-heading">
      <div className="workflow-main">
        <div className="workflow-section-header">
          <div>
            <h2 id="workflow-heading">{translate(t, 'pages.dashboard.workflow.title', 'Arbeitszentrale')}</h2>
            <p>{translate(t, 'pages.dashboard.workflow.subtitle', 'Gefuehrte Prozesssicht ueber Bestand, Vermietung, Finanzen, Abrechnung und Betrieb.')}</p>
          </div>
          <Link to="/settings" className="workflow-secondary-link">
            {translate(t, 'pages.dashboard.workflow.configure', 'Arbeitsweise anpassen')}
            <ArrowRightIcon size={14} />
          </Link>
        </div>
        <ProcessJourney steps={processSteps} nextStep={nextStep} t={t} />
        <div className="workflow-card-grid">
          {workflows.map(item => <WorkflowCard key={item.id} item={item} t={t} />)}
        </div>
      </div>
      <AttentionPanel items={attentionItems} t={t} />
    </section>
  );
}
