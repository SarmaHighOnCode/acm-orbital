/**
 * api.js — Fetch Wrapper for Snapshot Polling
 * Owner: Dev 3 (Frontend)
 *
 * THE ONLY place fetch('/api/...') appears in the frontend.
 * Components use the Zustand store, not direct fetch calls.
 */

import useStore from '../store';

const API_BASE = '/api';

/**
 * Fetch the latest visualization snapshot from the backend.
 * Updates the Zustand store on success.
 */
export async function fetchSnapshot() {
  try {
    useStore.getState().setLoading(true);
    const res = await fetch(`${API_BASE}/visualization/snapshot`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    useStore.getState().setSnapshot(data);
    useStore.getState().setError(null);
  } catch (err) {
    useStore.getState().setError(err.message);
  } finally {
    useStore.getState().setLoading(false);
  }
}

/**
 * Start polling the snapshot endpoint at the given interval.
 * Returns a cleanup function to stop polling.
 *
 * @param {number} intervalMs - Polling interval (default 2000ms)
 * @returns {() => void} Stop function
 */
export function startPolling(intervalMs = 2000) {
  fetchSnapshot(); // Initial fetch
  const id = setInterval(fetchSnapshot, intervalMs);
  return () => clearInterval(id);
}
