# Project instructions

## Versioning

- Increment the patch version once per completed batch of changes to any project
  file, including code, tests, documentation, configuration, and instructions.
- Keep `project.version` in [pyproject.toml](../pyproject.toml) and `__version__` in
  [src/local_monitoring/__init__.py](../src/local_monitoring/__init__.py) identical.
  The shared page header displays `__version__`; do not hardcode a separate UI version.
- Include the version bump in the same change set before final validation. Fixes
  and validation iterations within that batch do not require additional bumps.
  Read-only tasks do not require a bump.
