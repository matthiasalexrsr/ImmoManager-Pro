import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { isLoggedIn } from './api';
import Layout from './components/Layout';
import Login from './pages/Login';
import Dashboard from './pages/Dashboard';
import Portfolios from './pages/Portfolios';
import Properties from './pages/Properties';
import Units from './pages/Units';
import Tenants from './pages/Tenants';
import Contracts from './pages/Contracts';
import Accounts from './pages/Accounts';
import Bookings from './pages/Bookings';
import Invoices from './pages/Invoices';
import Maintenance from './pages/Maintenance';
import Tasks from './pages/Tasks';
import Documents from './pages/Documents';

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
          <Route path="units" element={<Units />} />
          <Route path="tenants" element={<Tenants />} />
          <Route path="contracts" element={<Contracts />} />
          <Route path="accounts" element={<Accounts />} />
          <Route path="bookings" element={<Bookings />} />
          <Route path="invoices" element={<Invoices />} />
          <Route path="maintenance" element={<Maintenance />} />
          <Route path="tasks" element={<Tasks />} />
          <Route path="documents" element={<Documents />} />
        </Route>
      </Routes>
    </BrowserRouter>
  );
}
