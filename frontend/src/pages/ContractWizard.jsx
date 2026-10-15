import { useEffect, useLayoutEffect, useRef, useState } from 'react';
import { useTranslation } from '../i18n';
import useFormDraft from '../hooks/useFormDraft';
import CustomDraftNotice from '../components/CustomDraftNotice';
import { useAuth } from '../contexts/AuthContext';

const DRAFT_FIELDS = [{ key: 'form' }];

export default function ContractWizard() {
  const { t } = useTranslation();
  const iframeRef = useRef(null);
  const owner = useAuth()?.user?.id;
  const [frameOwner, setFrameOwner] = useState(null);
  const frameReady = frameOwner === owner;

  const [wizardStatus, setWizardStatus] = useState({
    loading: true,
    available: false,
    reason: null,
  });
  const draft = useFormDraft({ context: 'contract-wizard', fields: DRAFT_FIELDS, enabled: wizardStatus.available });
  const draftRef = useRef(draft);
  useLayoutEffect(() => { draftRef.current = draft; }, [draft]);
  const [draftValues, setDraftValues] = useState(null);
  useEffect(() => { setDraftValues(null); }, [owner]);
  useEffect(() => {
    if (!owner || frameOwner !== owner) return;
    const receive = event => {
      if (event.origin !== window.location.origin || event.source !== iframeRef.current?.contentWindow
        || event.data?.type !== 'immo-wizard-draft' || !event.data.form || !draftRef.current.ready
        || !draftRef.current.isCurrent(draftRef.current.sessionKey) || draftRef.current.recovery) return;
      const next = { form: event.data.form };
      setDraftValues(next); draftRef.current.stage(next);
    };
    window.addEventListener('message', receive);
    return () => window.removeEventListener('message', receive);
  }, [owner, frameOwner]);

  const label = t('navigation.main.contractWizard');
  const title = label === 'navigation.main.contractWizard' ? 'Mietvertrag-Wizard' : label;

  useEffect(() => {
    let cancelled = false;

    fetch('/health')
      .then((res) => res.json())
      .then((data) => {
        if (cancelled) return;
        setWizardStatus({
          loading: false,
          available: Boolean(data.contract_wizard_available),
          reason: data.contract_wizard_reason ?? null,
        });
      })
      .catch((err) => {
        if (cancelled) return;
        setWizardStatus({
          loading: false,
          available: false,
          reason: err?.message ?? 'health check failed',
        });
      });

    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (!wizardStatus.available) return;

    const iframe = iframeRef.current;
    if (!iframe) return;

    const onLoad = () => {
      try {
        const doc = iframe.contentDocument || iframe.contentWindow?.document;
        if (!doc) return;

        const header = doc.querySelector('header');
        if (header) header.style.display = 'none';

        const style = doc.createElement('style');
        style.textContent = `
          body, input, select, textarea, button { font-family: 'Inter', system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif !important; }
          body { background: transparent !important; margin: 0; padding: 0; color: #111827; }
          h1, h2, h3, h4, label { font-family: inherit !important; }
          .container { max-width: 100% !important; padding: 0 !important; margin: 0 !important; }
          /* Same look as the rest of the app: teal accents, app buttons and inputs. */
          .progressbar li.active::before { background-color: #0d9488 !important; border-color: #0d9488 !important; color: #fff !important; }
          .progressbar li.active ~ li::before { background-color: #fff !important; border-color: #d1d5db !important; color: #6b7280 !important; }
          .progressbar li.active { color: #0d9488 !important; }
          .navigation button.next, .navigation #download { background-color: #0d9488 !important; }
          .navigation button.next:hover, .navigation #download:hover { background-color: #0f766e !important; }
          .add-person, #add-staffel {
            margin-top: 0.75rem; padding: 0.45rem 0.9rem; font-size: 0.875rem; font-weight: 500; cursor: pointer;
            color: #0d9488; background: #f0fdfa; border: 1px solid #99f6e4; border-radius: 6px;
          }
          .add-person:hover, #add-staffel:hover { background: #ccfbf1; }
          input:focus, select:focus, textarea:focus { border-color: #0d9488 !important; box-shadow: 0 0 0 3px rgba(13, 148, 136, 0.15) !important; outline: none; }
        `;
        doc.head.appendChild(style);
      } catch {
        // Cross-origin: cannot modify iframe content
      }
    };

    iframe.addEventListener('load', onLoad);
    return () => iframe.removeEventListener('load', onLoad);
  }, [wizardStatus.available]);

  if (wizardStatus.loading) {
    return <div className="page">Mietvertrag-Wizard wird geprüft …</div>;
  }

  if (!wizardStatus.available) {
    return (
      <div className="page">
        <h2 style={{ margin: '0 0 12px 0' }}>{title}</h2>
        <p className="text-muted" style={{ margin: '0 0 16px 0' }}>
          Der Mietvertrag-Wizard ist in diesem Build nicht verfügbar.
        </p>
        {wizardStatus.reason && (
          <pre
            style={{
              padding: '12px',
              borderRadius: '8px',
              background: '#f8fafc',
              border: '1px solid #e2e8f0',
              whiteSpace: 'pre-wrap',
            }}
          >
            {wizardStatus.reason}
          </pre>
        )}
      </div>
    );
  }

  return (
    <div className="page" style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
      <h1 className="page-title">{title}</h1>
      <p className="page-subtitle">
        {t('contractWizard.description') !== 'contractWizard.description'
          ? t('contractWizard.description')
          : 'Erstellen Sie Schritt für Schritt einen rechtssicheren Mietvertrag.'}
      </p>
      <CustomDraftNotice draft={{ ...draft, recover: draft.resume }} currentValues={draftValues} locked={!frameReady}
        onRestore={values => { if (!frameReady || !draft.isCurrent(draft.sessionKey)) return;
          iframeRef.current?.contentWindow?.immoWizardDraft?.restore(values.form); setDraftValues(values); draft.stage(values); }} />

      <iframe
        key={owner}
        ref={iframeRef}
        src="/mietvertrag/"
        title={title}
        onLoad={() => setFrameOwner(iframeRef.current?.contentWindow?.immoWizardDraft ? owner : null)}
        inert={draft.enabled && (!draft.ready || Boolean(draft.recovery)) ? true : undefined}
        style={{
          flex: 1,
          border: '1px solid var(--border-color, #e2e8f0)',
          borderRadius: 'var(--rounded-lg, 8px)',
          minHeight: '700px',
          width: '100%',
          background: 'var(--bg-primary, #fff)',
        }}
      />
    </div>
  );
}
