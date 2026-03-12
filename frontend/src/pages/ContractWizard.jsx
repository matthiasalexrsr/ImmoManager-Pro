import { useEffect, useRef, useState } from 'react';
import { useTranslation } from '../i18n';

const WIZARD_URL = '/mietvertrag/';

export default function ContractWizard() {
  const { t } = useTranslation();
  const iframeRef = useRef(null);
  const [iframeSrc, setIframeSrc] = useState(WIZARD_URL);
  const [isLoading, setIsLoading] = useState(true);
  const [loadError, setLoadError] = useState('');

  const label = t('navigation.main.contractWizard');
  const title = label === 'navigation.main.contractWizard' ? 'Mietvertrag-Wizard' : label;

  useEffect(() => {
    const iframe = iframeRef.current;
    if (!iframe) return;

    const timeoutId = window.setTimeout(() => {
      setLoadError('Der Mietvertrag-Wizard benötigt ungewöhnlich lange zum Laden.');
      setIsLoading(false);
    }, 12000);

    const onLoad = () => {
      window.clearTimeout(timeoutId);
      setIsLoading(false);
      setLoadError('');

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
        // Cross-origin: cannot modify iframe content.
      }
    };

    const onError = () => {
      window.clearTimeout(timeoutId);
      setIsLoading(false);
      setLoadError('Der Mietvertrag-Wizard konnte nicht geladen werden.');
    };

    iframe.addEventListener('load', onLoad);
    iframe.addEventListener('error', onError);
    return () => {
      window.clearTimeout(timeoutId);
      iframe.removeEventListener('load', onLoad);
      iframe.removeEventListener('error', onError);
    };
  }, [iframeSrc]);

  const handleReload = () => {
    setLoadError('');
    setIsLoading(true);
    setIframeSrc(`${WIZARD_URL}?retry=${Date.now()}`);
  };

  return (
    <div className="page" style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
      <h2 style={{ margin: '0 0 12px 0' }}>{title}</h2>
      <p className="text-muted" style={{ margin: '0 0 16px 0' }}>
        {t('contractWizard.description') !== 'contractWizard.description'
          ? t('contractWizard.description')
          : 'Erstellen Sie Schritt für Schritt einen rechtssicheren Mietvertrag.'}
      </p>

      <div style={{ display: 'flex', gap: '8px', marginBottom: '12px' }}>
        <button type="button" className="btn btn-sm btn-outline-primary" onClick={handleReload}>
          Wizard neu laden
        </button>
        <a className="btn btn-sm btn-outline-secondary" href={WIZARD_URL} target="_blank" rel="noreferrer">
          In neuem Tab öffnen
        </a>
      </div>

      {isLoading && !loadError && (
        <div className="alert alert-info" role="status" style={{ marginBottom: '12px' }}>
          Mietvertrag-Wizard wird geladen…
        </div>
      )}

      {loadError && (
        <div className="alert alert-warning" role="alert" style={{ marginBottom: '12px' }}>
          {loadError}
        </div>
      )}

      <iframe
        ref={iframeRef}
        src={iframeSrc}
        title={title}
        loading="eager"
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
