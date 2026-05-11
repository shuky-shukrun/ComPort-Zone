# ComPort Zone Copilot Instructions

Follow the root `AGENTS.md` file first. It is the canonical guide for agent behavior, commands, and guardrails.

## Project Context

ComPort Zone is a Windows-first Python 3.12+ desktop terminal application using PySide6 for the UI, pyserial for serial communication, and PyInstaller for Windows packaging.

Key docs:

- `docs/LLM_CHANGE_GUIDE.md` - first stop for ownership, safe edit recipes, and focused tests.
- `docs/ARCHITECTURE.md` - current refactor state and subsystem boundaries.
- `docs/DESIGN.md` - detailed design, data flows, and test strategy.

## Commands

Use the repo scripts:

```powershell
.\setup_dev.bat
.\run_tests.bat
.\scripts\run_tests.ps1 tests.test_quick_actions
.\launch_app.bat
.\build_exe.bat
git diff --check
```

Tests are `unittest`-based. Do not suggest pytest commands unless the repo actually migrates.

## Coding Guidance

- Keep pure domain/services free of Qt widget dependencies.
- Preserve settings JSON and quick action CSV compatibility unless explicitly asked to change them.
- Avoid editing generated or local output directories such as `.venv`, `build`, `dist`, `release`, and `__pycache__`.
- Do not assume physical COM hardware exists in automated tests.
- Use the ownership map in `docs/LLM_CHANGE_GUIDE.md` instead of duplicating it here.
