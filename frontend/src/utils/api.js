/**
 * api.js — Fetch Wrapper for Snapshot Polling
 * Owner: Dev 3 (Frontend)
 *
 * THE ONLY place fetch('/api/...') appears in the frontend.
 * Components use the Zustand store, not direct fetch calls.
 *
 * Features:
 *  - Retry with exponential backoff on transient failures
 *  - Connection status tracking (connected / reconnecting)
 *  - Waits for backend readiness on first load (auto-seed may still be running)
 */

import useStore from '../store';

const API_BASE = '/api';
const MAX_RETRIES = 3;
const BASE_DELAY_MS = 500;

let consecutiveFailures = 0;

/**
 * Fetch the latest visualization snapshot from the backend.
 * Updates the Zustand store on success. On failure, retries up to
 * MAX_RETRIES with exponential backoff before surfacing the error.
 */
export async function fetchSnapshot() {
  const store = useStore.getState();

  for (let attempt = 0; attempt <= MAX_RETRIES; attempt++) {
    try {
      const res = await fetch(`${API_BASE}/visualization/snapshot`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();

      store.setSnapshot(data);
      store.setError(null);

      // Reset failure counter and mark connected
      if (consecutiveFailures > 0 || !store.connected) {
        consecutiveFailures = 0;
        store.setConnected(true);
      }
      return;
    } catch (err) {
      if (attempt < MAX_RETRIES) {
        // Exponential backoff: 500ms, 1s, 2s
        await new Promise((r) => setTimeout(r, BASE_DELAY_MS * 2 ** attempt));
        continue;
      }

      // All retries exhausted
      consecutiveFailures++;
      store.setError(err.message);

      if (consecutiveFailures >= 3) {
        store.setConnected(false);
      }
    }
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
