/**
 * store.js — Zustand Global State Store
 * Owner: Dev 3 (Frontend)
 *
 * Holds the full snapshot from GET /api/visualization/snapshot
 * including CDMs, maneuver_log, and collision_count needed
 * for BullseyePlot, ManeuverTimeline, and FuelHeatmap.
 *
 * Also maintains a rolling 90-minute position history per satellite
 * for the Ground Track historical trail.
 */

import { create } from 'zustand';

const HISTORY_MAX_ENTRIES = 54; // ~90 min at 100s polling ≈ 54 samples

const useStore = create((set, get) => ({
  // Simulation state from API
  timestamp: null,
  satellites: [],
  debrisCloud: [],
  activeCdmCount: 0,
  maneuverQueueDepth: 0,

  // Extended data from backend
  cdms: [],
  maneuverLog: [],
  collisionCount: 0,

  // Rolling satellite position history (for ground track trails)
  // { [satId]: [{ lat, lon, t }, ...] }
  satHistory: {},

  // UI state
  selectedSatellite: null,
  isLoading: false,
  error: null,
  connected: true,

  // Actions
  setSnapshot: (snapshot) =>
    set((state) => {
      // Build updated history — append current positions, trim to 90 min
      const newHistory = { ...state.satHistory };
      const sats = snapshot.satellites || [];
      for (const sat of sats) {
        if (!newHistory[sat.id]) newHistory[sat.id] = [];
        newHistory[sat.id].push({
          lat: sat.lat,
          lon: sat.lon,
          t: snapshot.timestamp,
        });
        // Keep only last HISTORY_MAX_ENTRIES
        if (newHistory[sat.id].length > HISTORY_MAX_ENTRIES) {
          newHistory[sat.id] = newHistory[sat.id].slice(-HISTORY_MAX_ENTRIES);
        }
      }

      return {
        timestamp: snapshot.timestamp,
        satellites: sats,
        debrisCloud: snapshot.debris_cloud || [],
        activeCdmCount: snapshot.active_cdm_count || 0,
        maneuverQueueDepth: snapshot.maneuver_queue_depth || 0,
        cdms: snapshot.cdms || [],
        maneuverLog: snapshot.maneuver_log || [],
        collisionCount: snapshot.collision_count || 0,
        satHistory: newHistory,
        // Auto-select first satellite if none selected
        selectedSatellite:
          state.selectedSatellite ||
          (sats.length > 0 ? sats[0].id : null),
      };
    }),

  setSelectedSatellite: (id) => set({ selectedSatellite: id }),
  setLoading: (loading) => set({ isLoading: loading }),
  setError: (error) => set({ error }),
  setConnected: (val) => set({ connected: val }),
}));

export default useStore;
