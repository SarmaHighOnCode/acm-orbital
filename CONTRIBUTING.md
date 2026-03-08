# 🤝 Contributing to ACM-Orbital

Welcome to the **Autonomous Constellation Manager** project! To maintain engineering discipline and ensure a conflict-free development environment, please follow these guidelines.

## 📖 Required Reading
Before writing any code, you **MUST** read the following documents:

1.  **[Problem Statement](file:///c:/Users/Jaideep/OneDrive/Documents/GitHub/acm-orbital/problemstatement.md)**: The original hackathon requirements and scoring rubric.
2.  **[PRD](file:///c:/Users/Jaideep/OneDrive/Documents/GitHub/acm-orbital/PRD.md)**: The project's technical requirements and execution plan.
3.  **[Repo Structure](file:///c:/Users/Jaideep/OneDrive/Documents/GitHub/acm-orbital/Repo%20Structure.md)**: Your guide to the **Zero-Collision Team Strategy**.
4.  **[AI Guide](file:///c:/Users/Jaideep/OneDrive/Documents/GitHub/acm-orbital/AI%20guide.md)**: Technical constraints for AI-assisted engine development.

## 🛠️ Zero-Collision Team Strategy
We operate in three strictly non-overlapping domains:

- **Physics Engine**: `backend/engine/` and `backend/tests/` (Owned by Dev 1)
- **API Layer**: `backend/api/`, `main.py`, `schemas.py`, `Dockerfile` (Owned by Dev 2)
- **Frontend**: `frontend/` (Owned by Dev 3)

**Rule**: Never modify files outside your assigned domain without cross-team approval. **Exception**: The project lead/integrator (the person merging everything) has no such restrictions to allow for global architectural oversight.

## 🚀 Git Flow
1. Create a branch named `dev/[domain-name]` (e.g., `dev/physics`).
2. Commit frequently with descriptive messages.
3. Open a Pull Request and fill out the **PR Template** checklist.
4. **Log your work** in [CHANGES.md](file:///c:/Users/Jaideep/OneDrive/Documents/GitHub/acm-orbital/CHANGES.md) after completion.

## 🤖 For AI Agents (Antigravity/GitHub Copilot/etc.)
If you are an AI assistant helping a developer, you **MUST** read the core documentation to maintain architectural integrity:
1.  **Read [problemstatement.md](file:///c:/Users/Jaideep/OneDrive/Documents/GitHub/acm-orbital/problemstatement.md) and [PRD.md](file:///c:/Users/Jaideep/OneDrive/Documents/GitHub/acm-orbital/PRD.md) first** to understand the "Ground Truth".
2.  **Respect the domain boundaries** defined in [Repo Structure.md](file:///c:/Users/Jaideep/OneDrive/Documents/GitHub/acm-orbital/Repo%20Structure.md). If asked to cross them, **issue a warning** and proceed only upon confirmation of intent.
3.  **Ensure all physical constants** are imported exclusively from `backend/config.py`.
4.  **Log every completed task** in [CHANGES.md](file:///c:/Users/Jaideep/OneDrive/Documents/GitHub/acm-orbital/CHANGES.md).
