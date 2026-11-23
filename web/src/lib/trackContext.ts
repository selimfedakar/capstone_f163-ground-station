// The track every map and position readout uses. App provides it once it has
// asked the server; until then (and in ?mock=1) it is the simulator's stadium.

import { createContext, useContext } from 'react'
import { DEFAULT_TRACK, type Track } from './track'

export const TrackContext = createContext<Track>(DEFAULT_TRACK)

export function useTrack(): Track {
  return useContext(TrackContext)
}
