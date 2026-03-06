import { Link } from 'react-router-dom';
import { useTranslation } from '../i18n';

export default function NotFound() {
  const { t } = useTranslation();
  return (
    <div className="page" style={{ textAlign: 'center', paddingTop: '4rem' }}>
      <h1 style={{ fontSize: '3rem', marginBottom: '1rem' }}>404</h1>
      <p className="text-muted" style={{ fontSize: '1.1rem', marginBottom: '2rem' }}>
        {t('pages.notFound.message')}
      </p>
      <Link to="/" className="btn btn-primary">{t('pages.notFound.back')}</Link>
    </div>
  );
}
