# Changelog

All notable changes to the ACM-Orbital project will be documented in this file.

## [Production Release] - 2026-03-26

The following updates were developed and tested locally to refine the simulation stability, fix rendering inaccuracies, implement the missing NASA-type dashboard features, and eliminate technical debt. This represents our push to the main production branch.

### 🎨 NASA-Type Dashboard Implementation
- **Terminator Line:** Added a dynamic shadow overlay representing the Terminator Line — the boundary between day and night — to indicate solar eclipse zones in GroundTrack.jsx.
- **90-min Trajectories:** Implemented a historical trailing path for the last 90 minutes of orbit, alongside a dashed predicted trajectory line for the next 90 minutes in GroundTrack.jsx.
- **Δv Cost Analysis Graph:** Added the spec-required visualization plotting Fuel Consumed vs Collisions Avoided to demonstrate evasion algorithm efficiency, fully integrated directly via DeltaVChart.jsx.
- **Bullseye Plot TCA & Approach Vector:** Rewrote the Bullseye radial axis to use Time to Closest Approach (TCA) for distance rather than arbitrary miss-distance rings. Modified the angle axis to properly represent the relative approach vector, matching Section 6.2 specifications perfectly.
- **Auto-Step Toggle Restored:** Restored the ability to pause and start Auto-Step directly from the dashboard metrics bar. It is no longer forced on by default.

### ⚙️ Architecture & Infrastructure
- **Docker-First Stability**: Standardized the overarching environment structure. Enforced ubuntu:22.04 consistently across the Docker build pipeline to guarantee that complex orbital propagation math and float precisions behave identically across all hardware.
- **Snapshot Debris Tuple Flattening**: Verified and ensured the debris_cloud array utilizes the flattened tuple structure [ID, Latitude, Longitude, Altitude], fully complying with Section 6.3 and resolving any massive payload parsing bottlenecks.

### 🐛 Bug Fixes & Refactors
- **Mitigated Backend Polling Pileup**: Diagnosed and repaired a critical frontend race condition that was choking the Uvicorn server. Replaced rigid setInterval loops with a resilient and cascading setTimeout chain, ensuring the UI waits for a telemetry response before requesting the next batch.

### 🛠️ Code Cleanup & Technical Debt
- **Pruned Abandoned Web Worker**: Deleted the experimental propagation.worker.js thread. Moving forward, SGP4 spatial propagation remains strictly a backend responsibility to strictly enforce a single source of truth.
- **Removed Dead Coordinate Math**: Excised the unimplemented eciToGeodetic coordinate conversion function from coordinates.js along with its pending developer notes, relying entirely on the native Python engine to supply exact LLA coordinates.
- **Sanitized Repository**: Cleaned out obsolete localized planning files, historical tracking notes, and leftover dev branches to keep the codebase pristine for open-source deployment.

### 📝 Documentation
- **Modernized SETUP.md**: Rewrote the entire setup guide to clearly promote the Docker Compose run path as Option 1.
- **Auto-Seeding Clarity**: Added documentation for the AUTO_SEED routine and cleared out legacy directions that referenced absent standalone Python launch scripts.
