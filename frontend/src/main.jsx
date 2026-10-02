import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import './components/AppShell.css'
import App from './App.jsx'
import ErrorBoundary from './components/ErrorBoundary.jsx'
import { ToastProvider } from './components/Toast.jsx'
import { ConfirmProvider } from './components/ConfirmDialog.jsx'
import { I18nProvider } from './i18n.jsx'
import { PreferencesProvider } from './contexts/PreferencesContext.jsx'
import { DevModeProvider } from './contexts/DevModeContext.jsx'
import { DataStoreProvider } from './contexts/DataStoreContext.jsx'
import { AuthProvider } from './contexts/AuthContext.jsx'

createRoot(document.getElementById('root')).render(
  <StrictMode>
    <ErrorBoundary>
      <I18nProvider>
        <AuthProvider>
          <PreferencesProvider>
            <DataStoreProvider>
              <DevModeProvider>
                <ToastProvider>
                  <ConfirmProvider>
                    <App />
                  </ConfirmProvider>
                </ToastProvider>
              </DevModeProvider>
            </DataStoreProvider>
          </PreferencesProvider>
        </AuthProvider>
      </I18nProvider>
    </ErrorBoundary>
  </StrictMode>,
)
