"""scripts._archive: zero-importer modules moved here for visibility.

T020 of the refactor. Modules in this package have NO production
importers in scripts/ (only test imports, which have been moved
alongside). They are kept (not deleted) because:

- view.html or external tools might still reference them
- Future work might revive them
- Deletion would erase history that the codebase still depends on

To revive a module: `git mv scripts/_archive/<name>.py scripts/`
and update any imports.

See ARCHIVED.md in this directory for the per-file audit trail.
"""