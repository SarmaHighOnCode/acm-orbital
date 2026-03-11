/**
 * App.jsx — Root Layout (4-Panel Dashboard Grid)
 * Owner: Dev 3 (Frontend)
 */

import React, { useEffect } from 'react';
import Dashboard from './components/Dashboard';
import { startPolling } from './utils/api';

export default function App() {
  useEffect(() => {
    const stopPolling = startPolling(2000); // Poll every 2 seconds
    return () => stopPolling();
  }, []);

  return (
    <div className="w-full h-full">
      <Dashboard />
    </div>
  );
}
