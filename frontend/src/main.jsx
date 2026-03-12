import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.jsx'
import ErrorBoundary from './components/ErrorBoundary.jsx'
import { ToastProvider } from './components/Toast.jsx'
import { I18nProvider } from './i18n.jsx'
import { PreferencesProvider } from './contexts/PreferencesContext.jsx'
import { DevModeProvider } from './contexts/DevModeContext.jsx'
import { DataStoreProvider } from './contexts/DataStoreContext.jsx'

createRoot(document.getElementById('root')).render(
  <StrictMode>
    <ErrorBoundary>
      <I18nProvider>
        <PreferencesProvider>
          <DataStoreProvider>
            <DevModeProvider>
              <ToastProvider>
                <App />
              </ToastProvider>
            </DevModeProvider>
          </DataStoreProvider>
        </PreferencesProvider>
      </I18nProvider>
    </ErrorBoundary>
  </StrictMode>,
)
