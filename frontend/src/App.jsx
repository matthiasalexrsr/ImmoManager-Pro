import { useState, useEffect } from 'react';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { isLoggedIn, api } from './api';
import Layout from './components/Layout';
import DevModeOverlay from './components/DevModeOverlay';
import { useDevMode } from './contexts/DevModeContext';
import Login from './pages/Login';
import Dashboard from './pages/Dashboard';
import Portfolios from './pages/Portfolios';
import Properties from './pages/Properties';
import PropertyOverview from './pages/PropertyOverview';
import Units from './pages/Units';
import UnitOverview from './pages/UnitOverview';
import Tenants from './pages/Tenants';
import Contracts from './pages/Contracts';
import Accounts from './pages/Accounts';
import Bookings from './pages/Bookings';
import Invoices from './pages/Invoices';
import Maintenance from './pages/Maintenance';
import Tasks from './pages/Tasks';
import Documents from './pages/Documents';
import RentOverview from './pages/RentOverview';
import Meters from './pages/Meters';
import Contacts from './pages/Contacts';
import Statements from './pages/Statements';
import Messages from './pages/Messages';
import Settings from './pages/Settings';
import PropertyDetail from './pages/PropertyDetail';
import Categories from './pages/Categories';
import Deposits from './pages/Deposits';
import Insurances from './pages/Insurances';
import Integrations from './pages/Integrations';
import Calendar from './pages/Calendar';
import Leads from './pages/Leads';
import Listings from './pages/Listings';
import Viewings from './pages/Viewings';
import RentAdjustments from './pages/RentAdjustments';
import Budgets from './pages/Budgets';
import TaxRates from './pages/TaxRates';
import ContractWizard from './pages/ContractWizard';
import Receivables from './pages/Receivables';
import RentCharges from './pages/RentCharges';
import EscalationRules from './pages/EscalationRules';
import NotificationTemplates from './pages/NotificationTemplates';
import History from './pages/History';
import AllocationKeys from './pages/AllocationKeys';
import HandoverProtocols from './pages/HandoverProtocols';
import NotFound from './pages/NotFound';

function ProtectedRoute({ children }) {
  const [status, setStatus] = useState(isLoggedIn() ? 'validating' : 'unauthenticated');

  useEffect(() => {
    if (!isLoggedIn()) {
      setStatus('unauthenticated');
      return;
    }
    // Validate the session against the backend before rendering
    api.get('/auth/me')
      .then(() => setStatus('authenticated'))
      .catch(() => {
        // Token is invalid/expired and refresh failed — clear tokens
        localStorage.removeItem('access_token');
        localStorage.removeItem('refresh_token');
        setStatus('unauthenticated');
      });
  }, []);

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
          <Route path="invoices" element={<Invoices />} />
          <Route path="maintenance" element={<Maintenance />} />
          <Route path="tasks" element={<Tasks />} />
          <Route path="documents" element={<Documents />} />
          <Route path="rent-overview" element={<RentOverview />} />
          <Route path="meters" element={<Meters />} />
          <Route path="contacts" element={<Contacts />} />
          <Route path="statements" element={<Statements />} />
          <Route path="messages" element={<Messages />} />
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
          <Route path="settings" element={<Settings />} />
          <Route path="*" element={<NotFound />} />
        </Route>
      </Routes>
      </DevModeWrapper>
    </BrowserRouter>
  );
}
