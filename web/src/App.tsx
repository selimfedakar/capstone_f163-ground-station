import { useEffect, useState } from 'react'
import { HashRouter, NavLink, Navigate, Route, Routes } from 'react-router-dom'
import { Flag } from './components/bits'
import { Hint } from './components/Hint'
import { getTrack } from './lib/api'
import { theme } from './lib/theme'
import { DEFAULT_TRACK, buildTrack, type Track } from './lib/track'
import { TrackContext } from './lib/trackContext'
import { useConnection } from './lib/useConnection'
import { DashboardView } from './views/DashboardView'
import { DriveView } from './views/DriveView'
import { LiveView } from './views/LiveView'

export default function App() {
  const [track, setTrack] = useState<Track>(DEFAULT_TRACK)
  // Single shared connection powers both Drive and Live views.
  const conn = useConnection(track)

  // The server owns the track definition. Ask for it whenever the connection
  // (re)opens, so a server restarted with a different track is picked up.
  const online = conn.status === 'open' && !conn.mock
  useEffect(() => {
    if (!online) return
    let alive = true
    getTrack()
      .then((spec) => {
        if (alive && spec.centerline.length >= 3) setTrack(buildTrack(spec))
      })
      .catch(() => {
        // An older server has no /api/track: keep the built-in stadium.
      })
    return () => {
      alive = false
    }
  }, [online])

  const link = conn.mock
    ? { color: theme.yellow, text: 'Demo data' }
    : conn.status === 'open'
      ? { color: theme.green, text: 'Connected' }
      : conn.status === 'connecting'
        ? { color: theme.yellow, text: 'Connecting' }
        : { color: theme.kerb, text: 'No server' }
  const rtt = conn.latencyMs
  const rttClass = rtt == null ? '' : rtt < 50 ? 'good' : rtt <= 100 ? 'fair' : 'poor'

  return (
    <TrackContext.Provider value={track}>
      <HashRouter>
        <div className="app">
          <header className="masthead">
            <div className="masthead-row">
              <p className="brand">
                <strong>F163</strong> ground station
              </p>
              <nav className="tabs" aria-label="Views">
                <NavLink to="/drive">Drive</NavLink>
                <NavLink to="/live">Live</NavLink>
                <NavLink to="/dashboard">Dashboard</NavLink>
              </nav>
              <div className="status">
                {conn.race && <span className="status-item racing">Race on: {conn.race.name}</span>}
                <span className="status-item">
                  <Flag color={link.color} />
                  {link.text}
                  <Hint k="link" />
                </span>
                <span className="status-item">
                  Server delay
                  <b className={`num ${rttClass}`}>{rtt == null ? '–' : rtt}</b> ms
                  <Hint k="rtt" />
                </span>
              </div>
            </div>
            <div className="kerb" aria-hidden="true" />
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
    </TrackContext.Provider>
  )
}
