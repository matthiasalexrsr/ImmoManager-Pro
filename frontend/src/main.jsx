import { StrictMode, lazy, Suspense } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import ErrorBoundary from './components/ErrorBoundary.jsx'

const InternalApp = lazy(() => import('./InternalApp.jsx'))
const PortalApp = lazy(() => import('./features/externalPortal/PortalApp.jsx'))
const externalPortal = /^\/portal(?:\/|$)/.test(window.location.pathname)

createRoot(document.getElementById('root')).render(
  <StrictMode>
    <ErrorBoundary>
      <Suspense fallback={<p role="status">Anwendung wird geladen …</p>}>
        {externalPortal ? <PortalApp /> : <InternalApp />}
      </Suspense>
    </ErrorBoundary>
  </StrictMode>,
)
