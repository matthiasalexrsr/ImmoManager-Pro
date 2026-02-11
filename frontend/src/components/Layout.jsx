import { NavLink, Outlet, useNavigate } from 'react-router-dom';
import { logout } from '../api';

const NAV = [
  { to: '/', label: 'Dashboard', icon: '📊' },
  { to: '/portfolios', label: 'Portfolios', icon: '🏢' },
  { to: '/properties', label: 'Immobilien', icon: '🏠' },
  { to: '/units', label: 'Einheiten', icon: '🚪' },
  { to: '/tenants', label: 'Mieter', icon: '👤' },
  { to: '/contracts', label: 'Verträge', icon: '📄' },
  { to: '/accounts', label: 'Konten', icon: '🏦' },
  { to: '/bookings', label: 'Buchungen', icon: '💶' },
  { to: '/invoices', label: 'Rechnungen', icon: '🧾' },
  { to: '/maintenance', label: 'Wartung', icon: '🔧' },
  { to: '/tasks', label: 'Aufgaben', icon: '✅' },
  { to: '/documents', label: 'Dokumente', icon: '📁' },
];

export default function Layout() {
  const navigate = useNavigate();

  return (
    <div className="app-layout">
      <aside className="sidebar">
        <div className="sidebar-header">
          <h1>ImmoManager</h1>
          <span className="subtitle">Pro</span>
        </div>
        <nav>
          {NAV.map(({ to, label, icon }) => (
            <NavLink key={to} to={to} className={({ isActive }) => isActive ? 'nav-link active' : 'nav-link'}>
              <span className="nav-icon">{icon}</span>
              {label}
            </NavLink>
          ))}
        </nav>
        <div className="sidebar-footer">
          <button onClick={() => { logout(); navigate('/login'); }} className="btn-logout">
            Abmelden
          </button>
        </div>
      </aside>
      <main className="main-content">
        <Outlet />
      </main>
    </div>
  );
}
