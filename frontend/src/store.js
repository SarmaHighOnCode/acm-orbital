/**
 * store.js — Zustand Global State Store
 * Owner: Dev 3 (Frontend)
 *
 * Integrates naturally with R3F's render loop.
 * Holds the latest snapshot from the API.
 */

import { create } from 'zustand';

const useStore = create((set) => ({
  // Simulation state from API
  timestamp: null,
  satellites: [],
  debrisCloud: [],
  activeCdmCount: 0,
  maneuverQueueDepth: 0,

  // UI state
  selectedSatellite: null,
  isLoading: false,
  error: null,

  // Actions
  setSnapshot: (snapshot) =>
    set({
      timestamp: snapshot.timestamp,
      satellites: snapshot.satellites || [],
      debrisCloud: snapshot.debris_cloud || [],
      activeCdmCount: snapshot.active_cdm_count || 0,
      maneuverQueueDepth: snapshot.maneuver_queue_depth || 0,
    }),

  setSelectedSatellite: (id) => set({ selectedSatellite: id }),
  setLoading: (loading) => set({ isLoading: loading }),
  setError: (error) => set({ error }),
}));

export default useStore;
