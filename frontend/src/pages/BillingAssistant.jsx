import { useCallback, useEffect, useMemo, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { AlertTriangle, Check, Info } from 'lucide-react';
import { useCanWrite } from '../contexts/AuthContext';
import { useToast } from '../components/Toast';
import { STEPS, billingAssistantApi } from '../features/billingAssistant/billingAssistantApi';
import { CheckStep, CostsStep, KeysStep, OccupancyStep, PeriodStep, ReadingsStep, ResultStep } from '../features/billingAssistant/AssistantSteps';
import '../features/billingAssistant/billingAssistant.css';

const INTRO = {
  period: 'Immobilie und Abrechnungszeitraum wählen. Der Assistent zeigt, was für dieses Haus gilt.',
  occupancy: 'Wer hat die Einheiten im Zeitraum genutzt? Mieterwechsel und Leerstand bestimmen die Anteile.',
  keys: 'Nach welchen Schlüsseln werden die Kosten verteilt? Vorschläge passend zu Zählern und Einheiten dieses Hauses.',
  costs: 'Die Betriebskosten des Zeitraums: einzeln erfassen, aus dem Vorjahr übernehmen oder das Dokument des Messdienstes einlesen.',
  readings: 'Die Zählerstände, die die Verbrauchsschlüssel brauchen – zu Beginn, am Ende und bei jedem Mieterwechsel.',
  check: 'Die Prüfung der Abrechnung: was vorher geklärt werden muss und was sich ansehen lohnt.',
  result: 'Die Einzelabrechnungen je Nutzer. Danach geht es auf der Abrechnungsseite mit Schreiben, Prüfung und Versand weiter.',
};

/** The utility statement as a guided sequence of steps, with the situation of the chosen property. */
export default function BillingAssistant({ service = billingAssistantApi }) {
  const [params, setParams] = useSearchParams();
  const propertyId = params.get('property_id') || '';
  const periodId = params.get('period_id') || '';
  const step = STEPS.some(item => item.key === params.get('step')) ? params.get('step') : 'period';
  const [properties, setProperties] = useState([]);
  const [view, setView] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [revision, setRevision] = useState(0);
  const toast = useToast();
  const canCosts = useCanWrite('/billing/cost-items');
  const canPeriods = useCanWrite('/billing/periods');
  const canMeters = useCanWrite('/meters');
  const canKeys = useCanWrite('/billing/allocation-keys');

  const go = useCallback(values => setParams(previous => {
    const next = new URLSearchParams(previous);
    Object.entries(values).forEach(([key, value]) => (value ? next.set(key, value) : next.delete(key)));
    return next;
  }), [setParams]);

  useEffect(() => {
    const controller = new AbortController();
    service.properties({ signal: controller.signal }).then(list => {
      if (!controller.signal.aborted) setProperties((list || []).slice().sort((a, b) => (a.name || '').localeCompare(b.name || '', 'de')));
    }).catch(() => {});
    return () => controller.abort();
  }, [service]);

  useEffect(() => {
    if (!propertyId) { setView(null); return undefined; }
    const controller = new AbortController();
    setLoading(true); setError('');
    service.guide(propertyId, periodId, { signal: controller.signal }).then(data => {
      if (!controller.signal.aborted) setView(data);
    }).catch(failure => {
      if (!controller.signal.aborted) setError(failure.message || 'Die Angaben zur Immobilie konnten nicht geladen werden.');
    }).finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [service, propertyId, periodId, revision]);

  const reload = () => setRevision(value => value + 1);
  const act = async (task, success) => {
    setBusy(true);
    try { const result = await task(); if (success) toast?.success(success); reload(); return result ?? true; }
    catch (failure) { toast?.error(failure.message || 'Das hat nicht geklappt.'); return false; }
    finally { setBusy(false); }
  };

  const index = STEPS.findIndex(item => item.key === step);
  const reachable = key => key === 'period' || Boolean(view?.period);
  const hints = useMemo(() => (view?.hints || []).filter(hint => hint.step === step), [view, step]);
  const otherWarnings = useMemo(() => (view?.hints || []).filter(hint => hint.step !== step && hint.level === 'warning'), [view, step]);
  const editable = view?.period && ['draft', 'review'].includes(view.period.status);
  const writeCosts = canCosts && editable;

  const content = !view ? null : {
    period: <PeriodStep key={view.period?.id || view.property.id} view={view} canWrite={canPeriods} busy={busy}
      onChoose={id => go({ period_id: id })}
      onCreate={form => act(async () => {
        const created = await service.createPeriod({ property_id: view.property.id, ...form, status: 'draft' });
        go({ period_id: created.id, step: 'occupancy' });
      }, 'Abrechnung angelegt')} />,
    occupancy: <OccupancyStep view={view} />,
    keys: <KeysStep view={view} canWrite={canKeys} busy={busy} onCreateKey={key => act(() => service.createKey({
      property_id: view.property.id, name: key.name, key_type: key.key_type, meter_type: key.meter_type || null,
      measure_unit: key.measure_unit || null }), `Schlüssel „${key.name}“ angelegt`)} />,
    costs: <CostsStep view={view} canWrite={writeCosts} busy={busy} onImported={reload}
      onAdd={form => act(() => service.addCost({ billing_period_id: view.period.id, description: form.description.trim(),
        amount: Number(form.amount), allocation_key_id: form.allocation_key_id, is_recoverable: form.is_recoverable,
        cost_category: form.category || null, consumption_share: form.consumption_share ? Number(form.consumption_share) : null }),
      `„${form.description.trim()}“ erfasst`)}
      onRemove={row => act(() => service.removeCost(row.id), `„${row.description}“ entfernt`)} />,
    readings: <ReadingsStep view={view} canWrite={canMeters} busy={busy} onImported={reload}
      onSave={(row, value) => act(() => service.addReading(row.meter_id, { reading_date: row.day, value }), 'Zählerstand gespeichert')} />,
    check: <CheckStep view={view} />,
    result: <ResultStep view={view} canWrite={canCosts} busy={busy}
      onGenerate={() => act(() => service.generate(view.period.id), 'Einzelabrechnungen erzeugt')} />,
  }[step];

  return (
    <div className="page billing-assistant">
      <h1 className="page-title">Nebenkosten-Assistent</h1>
      <p className="page-subtitle">Schritt für Schritt zur Nebenkostenabrechnung – mit dem, was für die gewählte Immobilie gilt.</p>
      <div className="assistant-property">
        <label>Immobilie
          <select value={propertyId} onChange={event => go({ property_id: event.target.value, period_id: '', step: 'period' })}>
            <option value="">Bitte wählen</option>
            {properties.map(property => <option key={property.id} value={property.id}>{property.name}</option>)}
          </select></label>
        {view?.period && <span className="assistant-current">{view.period.label}</span>}
        <Link className="btn btn-sm btn-secondary" to={view?.period ? `/statements?period_id=${encodeURIComponent(view.period.id)}` : '/statements'}>Zur Abrechnungsseite</Link>
      </div>

      {propertyId && <ol className="assistant-progress" aria-label="Schritte">
        {STEPS.map((item, position) => {
          const done = view?.steps?.find(entry => entry.key === item.key)?.done;
          return <li key={item.key} className={`${position === index ? 'is-active' : ''}${done ? ' is-done' : ''}`}>
            <button type="button" disabled={!reachable(item.key)} aria-current={position === index ? 'step' : undefined}
              onClick={() => go({ step: item.key })}>
              <span className="assistant-progress-number">{done && position !== index ? <Check size={14} aria-hidden="true" /> : position + 1}</span>
              <span>{item.label}</span></button></li>;
        })}
      </ol>}

      {!propertyId && <p className="assistant-empty">Bitte oben die Immobilie wählen. Der Assistent führt dann durch Zeitraum, Nutzer,
        Verteilerschlüssel, Kosten und Zählerstände bis zu den Einzelabrechnungen.</p>}
      {error && <p role="alert" className="alert alert-error">{error} <button type="button" className="btn btn-sm btn-secondary" onClick={reload}>Erneut laden</button></p>}
      {loading && !view && <p role="status" className="text-muted">Die Angaben zur Immobilie werden zusammengestellt …</p>}

      {view && <div className="assistant-layout">
        <section className="panel assistant-main" aria-labelledby="assistant-step-title" aria-busy={loading || undefined}>
          <h2 id="assistant-step-title">{index + 1}. {STEPS[index].label}</h2>
          <p className="text-muted">{INTRO[step]}</p>
          {view.period && !editable && step !== 'period' && <p className="alert alert-info">Diese Abrechnung ist „{view.period.status}“ und lässt sich hier nur
            ansehen; Änderungen über eine Korrektur auf der Abrechnungsseite.</p>}
          {content}
          <div className="assistant-nav">
            <button type="button" className="btn btn-secondary" disabled={index === 0} onClick={() => go({ step: STEPS[index - 1].key })}>Zurück</button>
            {index < STEPS.length - 1 && <button type="button" className="btn btn-primary" disabled={!reachable(STEPS[index + 1].key)}
              onClick={() => go({ step: STEPS[index + 1].key })}>Weiter: {STEPS[index + 1].label}</button>}
          </div>
        </section>
        <aside className="assistant-hints" aria-label="Hinweise zu dieser Immobilie">
          <h2>Für dieses Haus</h2>
          {hints.length === 0 && <p className="text-muted">Für diesen Schritt keine Besonderheiten.</p>}
          <ul>{hints.map((hint, position) => <li key={position} className={`assistant-hint is-${hint.level}`}>
            {hint.level === 'warning' ? <AlertTriangle size={16} aria-hidden="true" /> : <Info size={16} aria-hidden="true" />}
            <span>{hint.text}{hint.link && <> <Link to={hint.link}>Öffnen</Link></>}</span></li>)}</ul>
          {otherWarnings.length > 0 && <details><summary>Weitere Hinweise ({otherWarnings.length})</summary>
            <ul>{otherWarnings.map((hint, position) => <li key={position} className="assistant-hint is-warning">
              <AlertTriangle size={16} aria-hidden="true" /><span>{hint.text}</span></li>)}</ul></details>}
        </aside>
      </div>}
    </div>
  );
}
