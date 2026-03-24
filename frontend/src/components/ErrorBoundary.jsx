/* eslint-disable react-refresh/only-export-components */
import { Component } from 'react';
import { useTranslation } from '../i18n';

function ErrorContent({ error, onReload }) {
  const { t } = useTranslation();
  return (
    <div className="error-boundary">
      <div className="error-boundary-content">
        <h1>{t('pages.errorBoundary.title') || 'Etwas ist schiefgelaufen'}</h1>
        <p>{t('pages.errorBoundary.message') || 'Ein unerwarteter Fehler ist aufgetreten. Bitte laden Sie die Seite neu.'}</p>
        {error && (
          <details>
            <summary>{t('pages.errorBoundary.details') || 'Fehlerdetails'}</summary>
            <pre>{error.toString()}</pre>
          </details>
        )}
        <button className="btn btn-primary" onClick={onReload}>
          {t('pages.errorBoundary.reload') || 'Seite neu laden'}
        </button>
      </div>
    </div>
  );
}

export default class ErrorBoundary extends Component {
  constructor(props) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  static getDerivedStateFromError(error) {
    return { hasError: true, error };
  }

  componentDidCatch(error, errorInfo) {
    console.error('ErrorBoundary caught:', error, errorInfo);
  }

  render() {
    if (this.state.hasError) {
      return (
        <ErrorContent
          error={this.state.error}
          onReload={() => {
            this.setState({ hasError: false, error: null });
            window.location.reload();
          }}
        />
      );
    }
    return this.props.children;
  }
}
