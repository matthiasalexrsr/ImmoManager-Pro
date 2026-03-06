import { useEffect, useRef } from 'react';
import { useTranslation } from '../i18n';

export default function ContractWizard() {
  const { t } = useTranslation();
  const iframeRef = useRef(null);
  const label = t('navigation.main.contractWizard');
  const title = label === 'navigation.main.contractWizard' ? 'Mietvertrag-Wizard' : label;

  useEffect(() => {
    const iframe = iframeRef.current;
    if (!iframe) return;

    const onLoad = () => {
      try {
        const doc = iframe.contentDocument || iframe.contentWindow?.document;
        if (!doc) return;

        // Remove the wizard's own header to avoid duplication with SPA layout
        const header = doc.querySelector('header');
        if (header) header.style.display = 'none';

        // Inject styles to make the wizard blend with the SPA theme
        const style = doc.createElement('style');
        style.textContent = `
          body { background: transparent !important; margin: 0; padding: 0; }
          .container { max-width: 100% !important; padding: 0 !important; margin: 0 !important; }
        `;
        doc.head.appendChild(style);
      } catch (e) {
        // Cross-origin: cannot modify iframe content
      }
    };

    iframe.addEventListener('load', onLoad);
    return () => iframe.removeEventListener('load', onLoad);
  }, []);

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
