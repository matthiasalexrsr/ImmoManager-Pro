/* eslint-disable react-refresh/only-export-components */
import { Component } from 'react';
import { useTranslation } from '../i18n';

function ErrorContent({ error, onReload }) {
  const { t } = useTranslation();
  // The root boundary also catches failures before the lazy application and
  // its translation provider have loaded. In that case t returns the key.
  const label = (key, fallback) => {
    const translated = t(key);
    return typeof translated === 'string' && translated && translated !== key ? translated : fallback;
  };
  return (
    <div className="error-boundary">
      <div className="error-boundary-content">
        <h1>{label('pages.errorBoundary.title', 'Etwas ist schiefgelaufen')}</h1>
        <p>{label('pages.errorBoundary.message', 'Ein unerwarteter Fehler ist aufgetreten. Bitte laden Sie die Seite neu.')}</p>
        {error && (
          <details>
            <summary>{label('pages.errorBoundary.details', 'Fehlerdetails')}</summary>
            <pre>{error.toString()}</pre>
          </details>
        )}
        <button className="btn btn-primary" onClick={onReload}>
          {label('pages.errorBoundary.reload', 'Seite neu laden')}
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
