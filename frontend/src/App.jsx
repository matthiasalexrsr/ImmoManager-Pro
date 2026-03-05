import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { isLoggedIn } from './api';
import Layout from './components/Layout';
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
import Categories from './pages/Categories';
import Deposits from './pages/Deposits';
import Insurances from './pages/Insurances';
import Integrations from './pages/Integrations';
import NotFound from './pages/NotFound';

function ProtectedRoute({ children }) {
  return isLoggedIn() ? children : <Navigate to="/login" />;
}

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route path="/" element={<ProtectedRoute><Layout /></ProtectedRoute>}>
          <Route index element={<Dashboard />} />
          <Route path="portfolios" element={<Portfolios />} />
          <Route path="properties" element={<Properties />} />
          <Route path="properties/:id" element={<PropertyOverview />} />
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
          <Route path="settings" element={<Settings />} />
          <Route path="*" element={<NotFound />} />
        </Route>
      </Routes>
    </BrowserRouter>
  );
}
