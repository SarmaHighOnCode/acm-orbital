## Description
<!-- Brief summary of what this PR does -->

## Domain
<!-- Check the ONE domain this PR modifies -->
- [ ] Physics Engine (`backend/engine/` + `backend/tests/`)
- [ ] API Layer (`backend/api/`, `main.py`, `schemas.py`, `Dockerfile`)
- [ ] Frontend (`frontend/`)

## Changes
<!-- List specific files modified and what changed -->

## Testing
<!-- How was this tested? -->
- [ ] Unit tests pass (`pytest backend/tests/ -v`)
- [ ] Docker build succeeds (`docker build -t acm-orbital .`)
- [ ] Manual verification completed

## Checklist
- [ ] All constants imported from `config.py`.
- [ ] No O(N^2) loops in physics code.
- [ ] All physics functions have corresponding tests.
