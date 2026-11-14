// On-screen touch/pointer controls: a vertical throttle slider and a
// horizontal steering slider. Steering springs back to center on release.

import type { DriveControls } from '../lib/useDriveControls'

export function TouchControls({ controls }: { controls: DriveControls }) {
  const { throttle, steering, setThrottle, setSteering, zero } = controls

  return (
    <div className="controls">
      <div className="control-block">
        <span className="ctl-label">Throttle</span>
        <input
          className="throttle-slider"
          type="range"
          min={-1}
          max={1}
          step={0.05}
          value={throttle}
          onChange={(e) => setThrottle(Number(e.target.value))}
          aria-label="Throttle"
        />
        <span className="ctl-value mono">{throttle.toFixed(2)}</span>
      </div>

      <div className="control-block" style={{ justifyContent: 'center' }}>
        <span className="ctl-label">Steering</span>
        <input
          className="steering-slider"
          type="range"
          min={-1}
          max={1}
          step={0.05}
          value={steering}
          onChange={(e) => setSteering(Number(e.target.value))}
          // Spring steering back to center when the pointer is released.
          onPointerUp={() => setSteering(0)}
          onMouseUp={() => setSteering(0)}
          onTouchEnd={() => setSteering(0)}
          aria-label="Steering"
        />
        <span className="ctl-value mono">{steering.toFixed(2)}</span>
        <button type="button" onClick={zero} style={{ marginTop: '0.5rem' }}>
          Brake / Zero (Space)
        </button>
      </div>
    </div>
  )
}
