/**
 * BullseyePlot.jsx — Polar Conjunction Proximity Chart
 * Owner: Dev 3 (Frontend)
 *
 * Center = selected satellite. Radial axis = TCA.
 * Angular axis = approach direction.
 * Color: Green >5km, Yellow <5km, Red <1km.
 */

import React from 'react';
import useStore from '../store';

export default function BullseyePlot() {
  const { selectedSatellite, activeCdmCount } = useStore();

  return (
    <div className="w-full h-full flex flex-col">
      <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-2">
        Conjunction Bullseye
      </h3>
      <div className="flex-1 flex items-center justify-center">
        {selectedSatellite ? (
          <div className="text-center text-gray-500 text-sm">
            {/* TODO: Dev 3 — Render polar SVG chart */}
            <p>Bullseye for {selectedSatellite}</p>
            <p className="text-xs mt-1">{activeCdmCount} active CDMs</p>
          </div>
        ) : (
          <p className="text-gray-600 text-sm">Select a satellite to view conjunctions</p>
        )}
      </div>
    </div>
  );
}
