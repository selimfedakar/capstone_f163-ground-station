import { HashRouter, NavLink, Navigate, Route, Routes } from 'react-router-dom'
import './App.css'
import { ConnectionBadge, LatencyBadge } from './components/StatusBar'
import { useConnection } from './lib/useConnection'
import { DashboardView } from './views/DashboardView'
import { DriveView } from './views/DriveView'
import { LiveView } from './views/LiveView'

export default function App() {
  // Single shared connection powers both Drive and Live views.
  const conn = useConnection()

  return (
    <HashRouter>
      <div className="app">
        <header className="topbar">
          <span className="brand">
            F163<span className="brand-sub">Ground Station</span>
          </span>
          <nav className="nav">
            <NavLink to="/drive">Drive</NavLink>
            <NavLink to="/live">Live</NavLink>
            <NavLink to="/dashboard">Dashboard</NavLink>
          </nav>
          <span className="topbar-spacer" />
          <LatencyBadge latencyMs={conn.latencyMs} />
          <ConnectionBadge status={conn.status} mock={conn.mock} />
        </header>

        <main className="content">
          <Routes>
            <Route path="/" element={<Navigate to="/drive" replace />} />
            <Route path="/drive" element={<DriveView conn={conn} />} />
            <Route path="/live" element={<LiveView conn={conn} />} />
            <Route path="/dashboard" element={<DashboardView />} />
            <Route path="*" element={<Navigate to="/drive" replace />} />
          </Routes>
        </main>
      </div>
    </HashRouter>
  )
}
