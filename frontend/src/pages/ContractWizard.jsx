import { useTranslation } from '../i18n';

export default function ContractWizard() {
  const { t } = useTranslation();
  const label = t('navigation.main.contractWizard');
  const title = label === 'navigation.main.contractWizard' ? 'Mietvertrag-Wizard' : label;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
      <h2 style={{ margin: '0 0 12px 0' }}>{title}</h2>
      <iframe
        src="/mietvertrag"
        title={title}
        style={{
          flex: 1,
          border: 'none',
          borderRadius: '8px',
          minHeight: '600px',
          width: '100%',
        }}
      />
    </div>
  );
}
