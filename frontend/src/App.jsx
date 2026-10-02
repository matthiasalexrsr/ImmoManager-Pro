import { useState, useEffect, lazy, Suspense } from 'react';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { isLoggedIn, api, watchSessionChange } from './api';
import Layout from './components/Layout';
import DevModeOverlay from './components/DevModeOverlay';
import LoadingSpinner from './components/LoadingSpinner';
import { useAuth } from './contexts/AuthContext';
import { useDevMode } from './contexts/DevModeContext';
import Login from './pages/Login';
import { useTranslation } from './i18n';

const Dashboard = lazy(() => import('./pages/Dashboard'));
const Portfolios = lazy(() => import('./pages/Portfolios'));
const Properties = lazy(() => import('./pages/Properties'));
const Units = lazy(() => import('./pages/Units'));
const UnitOverview = lazy(() => import('./pages/UnitOverview'));
const Tenants = lazy(() => import('./pages/Tenants'));
const Contracts = lazy(() => import('./pages/Contracts'));
const Accounts = lazy(() => import('./pages/Accounts'));
const Bookings = lazy(() => import('./pages/Bookings'));
const DatevExport = lazy(() => import('./pages/DatevExport'));
const AnnualTaxPage = lazy(() => import('./pages/AnnualTaxPage'));
const Outbox = lazy(() => import('./pages/Outbox'));
const Invoices = lazy(() => import('./pages/Invoices'));
const Maintenance = lazy(() => import('./pages/Maintenance'));
const Tasks = lazy(() => import('./pages/Tasks'));
const Documents = lazy(() => import('./pages/Documents'));
const RentOverview = lazy(() => import('./pages/RentOverview'));
const Meters = lazy(() => import('./pages/Meters'));
const Contacts = lazy(() => import('./pages/Contacts'));
const Statements = lazy(() => import('./pages/Statements'));
const Messages = lazy(() => import('./pages/Messages'));
const Settings = lazy(() => import('./pages/Settings'));
const PropertyDetail = lazy(() => import('./pages/PropertyDetail'));
const Categories = lazy(() => import('./pages/Categories'));
const Deposits = lazy(() => import('./pages/Deposits'));
const Insurances = lazy(() => import('./pages/Insurances'));
const Integrations = lazy(() => import('./pages/Integrations'));
const Calendar = lazy(() => import('./pages/Calendar'));
const Leads = lazy(() => import('./pages/Leads'));
const Listings = lazy(() => import('./pages/Listings'));
const Viewings = lazy(() => import('./pages/Viewings'));
const RentAdjustments = lazy(() => import('./pages/RentAdjustments'));
const Budgets = lazy(() => import('./pages/Budgets'));
const TaxRates = lazy(() => import('./pages/TaxRates'));
const ContractWizard = lazy(() => import('./pages/ContractWizard'));
const Receivables = lazy(() => import('./pages/Receivables'));
const RentCharges = lazy(() => import('./pages/RentCharges'));
const EscalationRules = lazy(() => import('./pages/EscalationRules'));
const NotificationTemplates = lazy(() => import('./pages/NotificationTemplates'));
const History = lazy(() => import('./pages/History'));
const AllocationKeys = lazy(() => import('./pages/AllocationKeys'));
const HandoverProtocols = lazy(() => import('./pages/HandoverProtocols'));
const TenancyWorkflows = lazy(() => import('./pages/TenancyWorkflows'));
const NotFound = lazy(() => import('./pages/NotFound'));

export function ProtectedRoute({ children }) {
  const [status, setStatus] = useState(isLoggedIn() ? 'validating' : 'unauthenticated');
  const [error, setError] = useState('');
  const [attempt, setAttempt] = useState(0);
  const { t } = useTranslation();
  const auth = useAuth();
  const updateUser = auth?.updateUser;
  const clearUser = auth?.clearUser;

  useEffect(() => watchSessionChange((failed) => {
    clearUser?.();
    // A full navigation drops all preceding-actor caches and private dialog
    // state. Ordinary rotation within the same family does not trigger this.
    if (failed || !isLoggedIn()) window.location.replace('/login');
    else window.location.reload();
  }), [clearUser]);

  useEffect(() => {
    if (!isLoggedIn()) {
      setStatus('unauthenticated');
      clearUser?.();
      return;
    }
    const controller = new AbortController();
    let active = true;
    setStatus('validating');
    setError('');
    // Validate the session against the backend before rendering
    api.get('/auth/me', { signal: controller.signal })
      .then((userData) => {
        if (!active || controller.signal.aborted) return;
        if (!isLoggedIn()) { clearUser?.(); setStatus('unauthenticated'); return; }
        updateUser?.(userData);
        setStatus('authenticated');
      })
      .catch((failure) => {
        if (!active || controller.signal.aborted || failure.name === 'AbortError') return;
        if (failure.code === 'AUTH_SESSION_CHANGED') { setAttempt(value => value + 1); return; }
        // The API invalidates only the attempted current pair. Transient errors
        // and late failures from an older session must not delete a new login.
        if (!isLoggedIn()) {
          clearUser?.(); setStatus('unauthenticated');
        } else {
          setError(failure.message); setStatus('error');
        }
      });
    return () => { active = false; controller.abort(); };
  }, [attempt, updateUser, clearUser]);

  if (status === 'validating') {
    return (
      <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', height: '100vh' }}>
        <div className="spinner" />
      </div>
    );
  }
  if (status === 'unauthenticated') {
    return <Navigate to="/login" />;
  }
  if (status === 'error') {
    return <div className="empty-state" role="alert">
      <p>{error}</p>
      <button type="button" className="btn btn-primary" onClick={() => setAttempt(value => value + 1)}>{t('ui.buttons.retry')}</button>
      <a className="btn btn-secondary" href="/login">{t('auth.login.submit')}</a>
    </div>;
  }
  return children;
}

function DevModeWrapper({ children }) {
  const devMode = useDevMode();
  return (
    <div className={devMode?.enabled ? 'dev-mode-active' : ''}>
      {children}
      <DevModeOverlay />
    </div>
  );
}

export default function App() {
  return (
    <BrowserRouter>
      <DevModeWrapper>
      <Suspense fallback={<LoadingSpinner />}>
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route path="/" element={<ProtectedRoute><Layout /></ProtectedRoute>}>
          <Route index element={<Dashboard />} />
          <Route path="portfolios" element={<Portfolios />} />
          <Route path="properties" element={<Properties />} />
          <Route path="properties/:id" element={<PropertyDetail />} />
          <Route path="units" element={<Units />} />
          <Route path="units/:id" element={<UnitOverview />} />
          <Route path="tenants" element={<Tenants />} />
          <Route path="contracts" element={<Contracts />} />
          <Route path="accounts" element={<Accounts />} />
          <Route path="bookings" element={<Bookings />} />
          <Route path="datev" element={<DatevExport />} />
          <Route path="annual-tax" element={<AnnualTaxPage />} />
          <Route path="invoices" element={<Invoices />} />
          <Route path="maintenance" element={<Maintenance />} />
          <Route path="tasks" element={<Tasks />} />
          <Route path="documents" element={<Documents />} />
          <Route path="rent-overview" element={<RentOverview />} />
          <Route path="meters" element={<Meters />} />
          <Route path="contacts" element={<Contacts />} />
          <Route path="statements" element={<Statements />} />
          <Route path="messages" element={<Messages />} />
          <Route path="outbox" element={<Outbox />} />
          <Route path="categories" element={<Categories />} />
          <Route path="deposits" element={<Deposits />} />
          <Route path="insurances" element={<Insurances />} />
          <Route path="integrations" element={<Integrations />} />
          <Route path="calendar" element={<Calendar />} />
          <Route path="leads" element={<Leads />} />
          <Route path="listings" element={<Listings />} />
          <Route path="viewings" element={<Viewings />} />
          <Route path="rent-adjustments" element={<RentAdjustments />} />
          <Route path="budgets" element={<Budgets />} />
          <Route path="tax-rates" element={<TaxRates />} />
          <Route path="contract-wizard" element={<ContractWizard />} />
          <Route path="receivables" element={<Receivables />} />
          <Route path="rent-charges" element={<RentCharges />} />
          <Route path="escalation-rules" element={<EscalationRules />} />
          <Route path="notification-templates" element={<NotificationTemplates />} />
          <Route path="history" element={<History />} />
          <Route path="allocation-keys" element={<AllocationKeys />} />
          <Route path="handover-protocols" element={<HandoverProtocols />} />
          <Route path="tenancy-workflows" element={<TenancyWorkflows />} />
          <Route path="settings" element={<Settings />} />
          <Route path="*" element={<NotFound />} />
        </Route>
      </Routes>
      </Suspense>
      </DevModeWrapper>
    </BrowserRouter>
  );
}
