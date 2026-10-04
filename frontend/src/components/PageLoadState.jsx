import { useTranslation } from '../i18n';

export default function PageLoadState({ loading, error, onRetry }) {
  const { t } = useTranslation();
  if (loading) return <div className="page-loading" role="status">{t('ui.table.loading')}</div>;
  if (!error) return null;
  const message = error?.message || String(error);
  return (
    <div className="page">
      <div className="alert alert-error" role="alert">{message}</div>
      <button className="btn btn-secondary" onClick={onRetry}>{t('ui.buttons.retry')}</button>
    </div>
  );
}
