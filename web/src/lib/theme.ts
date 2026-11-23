// Colours shared between the stylesheet and the canvas drawings.
// Keep in sync with the custom properties at the top of index.css.

export const theme = {
  ground: '#e6e8e1',
  paper: '#f5f6f1',
  ink: '#1b1f22',
  muted: '#5e666b',
  rule: '#c9cec4',
  asphalt: '#2b3034',
  paint: '#f5f6f1',
  kerb: '#d5332a',
  green: '#1f8a4c',
  yellow: '#e8b31a',
  font: '"Archivo Variable", system-ui, sans-serif',
}

/** One livery colour per car, assigned by sorted car id. */
const LIVERIES = ['#0f6fde', '#f08a00', '#8a3fd1', '#0b8f7a', '#c2307e', '#5b6b12']

export function liveryFor(carId: string, allIds: string[]): string {
  const i = [...allIds].sort().indexOf(carId)
  return LIVERIES[(i < 0 ? 0 : i) % LIVERIES.length]
}
