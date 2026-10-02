import { useTranslation } from '../i18n';

/** Do not render totals or editable reference selectors from incomplete data. */
export default function FinanceLoadState({ loading, error, onRetry }) {
  const { t } = useTranslation();
  if (loading) return <div className="page-loading" role="status">{t('ui.table.loading')}</div>;
  if (!error) return null;
  return (
    <div className="page">
      <div className="alert alert-error" role="alert">
        <p>{error.message}</p>
        {error.endpoint && <p className="text-muted">{error.endpoint}</p>}
      </div>
      <button className="btn btn-secondary" onClick={onRetry}>{t('ui.buttons.retry')}</button>
    </div>
  );
}
