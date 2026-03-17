import { useEffect, useRef, useState } from 'react';
import { useTranslation } from '../i18n';

export default function ContractWizard() {
  const { t } = useTranslation();
  const iframeRef = useRef(null);

  const [wizardStatus, setWizardStatus] = useState({
    loading: true,
    available: false,
    reason: null,
  });

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
          body { background: transparent !important; margin: 0; padding: 0; }
          .container { max-width: 100% !important; padding: 0 !important; margin: 0 !important; }
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
      <h2 style={{ margin: '0 0 12px 0' }}>{title}</h2>
      <p className="text-muted" style={{ margin: '0 0 16px 0' }}>
        {t('contractWizard.description') !== 'contractWizard.description'
          ? t('contractWizard.description')
          : 'Erstellen Sie Schritt für Schritt einen rechtssicheren Mietvertrag.'}
      </p>

      <iframe
        ref={iframeRef}
        src="/mietvertrag/"
        title={title}
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
