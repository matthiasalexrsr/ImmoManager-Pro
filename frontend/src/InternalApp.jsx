import App from './App.jsx';
import { ToastProvider } from './components/Toast.jsx';
import { ConfirmProvider } from './components/ConfirmDialog.jsx';
import { I18nProvider } from './i18n.jsx';
import { PreferencesProvider } from './contexts/PreferencesContext.jsx';
import { DevModeProvider } from './contexts/DevModeContext.jsx';
import { DataStoreProvider } from './contexts/DataStoreContext.jsx';
import { AuthProvider } from './contexts/AuthContext.jsx';

export default function InternalApp() {
  return <I18nProvider><AuthProvider><PreferencesProvider><DataStoreProvider><DevModeProvider>
    <ToastProvider><ConfirmProvider><App /></ConfirmProvider></ToastProvider>
  </DevModeProvider></DataStoreProvider></PreferencesProvider></AuthProvider></I18nProvider>;
}
