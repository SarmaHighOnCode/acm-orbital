/**
 * ManeuverTimeline.jsx — Gantt Scheduler with Cooldown Blocks
 * Owner: Dev 3 (Frontend)
 *
 * Horizontal scrollable timeline showing:
 * - Burn blocks (blue)
 * - 600s cooldown periods (gray)
 * - Blackout zone overlaps (orange)
 * - Conflicts (red)
 */

import React from 'react';
import useStore from '../store';

export default function ManeuverTimeline() {
  const { maneuverQueueDepth } = useStore();

  return (
    <div className="w-full h-full flex flex-col">
      <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-2">
        Maneuver Timeline
      </h3>
      <div className="flex-1 overflow-x-auto">
        {maneuverQueueDepth > 0 ? (
          <div className="min-w-[600px] h-full">
            {/* TODO: Dev 3 — Render Gantt chart with burn/cooldown/blackout blocks */}
            <p className="text-gray-500 text-sm">{maneuverQueueDepth} maneuvers queued</p>
          </div>
        ) : (
          <div className="flex items-center justify-center h-full">
            <p className="text-gray-600 text-sm">No maneuvers scheduled</p>
          </div>
        )}
      </div>
    </div>
  );
}
