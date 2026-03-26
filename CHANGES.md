# Changelog

All notable changes to the ACM-Orbital project will be documented in this file.

## [Production Release] - 2026-03-26

The following updates were developed and tested locally to refine the simulation stability, fix rendering inaccuracies, and eliminate technical debt. This represents our push to the main production branch.

### ?? Architecture & Infrastructure
- **Docker-First Stability**: Standardized the overarching environment structure. Enforced `ubuntu:22.04` consistently across the Docker build pipeline to guarantee that complex orbital propagation math and float precisions behave identically across all hardware.

### ?? Bug Fixes & Refactors
- **Bullseye Plot Mathematics**: Mathematically corrected the relative approach vector logic on the frontend. The dashboard's Bullseye plot now perfectly aligns and accurately projects relative trajectory collision angles between active satellites and debris.
- **Mitigated Backend Polling Pileup**: Diagnosed and repaired a critical frontend race condition that was choking the Uvicorn server. Replaced rigid `setInterval` loops with a resilient and cascading `setTimeout` chain, ensuring the UI waits for a telemetry response before requesting the next batch.

### ?? Code Cleanup & Technical Debt
- **Pruned Abandoned Web Worker**: Deleted the experimental `propagation.worker.js` thread. Moving forward, SGP4 spatial propagation remains strictly a backend responsibility to strictly enforce a single source of truth.
- **Removed Dead Coordinate Math**: Excised the unimplemented `eciToGeodetic` coordinate conversion function from `coordinates.js` along with its pending developer notes, relying entirely on the native Python engine to supply exact LLA coordinates.
- **Sanitized Repository**: Cleaned out obsolete localized planning files, historical tracking notes, and leftover dev branches to keep the codebase pristine for open-source deployment.

### ?? Documentation
- **Modernized SETUP.md**: Rewrote the entire setup guide to clearly promote the Docker Compose run path as Option 1. 
- **Auto-Seeding Clarity**: Added documentation for the `AUTO_SEED` routine and cleared out legacy directions that referenced absent standalone Python launch scripts.
