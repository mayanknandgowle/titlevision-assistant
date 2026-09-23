# Development

## Supported build target

Windows x64, CPython 3.13, installed Microsoft Edge for offline browser tests. Tests intercept all browser fixture requests; do not substitute production credentials into fixtures. Chrome is a runtime fallback.

Install `requirements-build.lock` with `pip install --require-hashes`. The lock records direct and transitive wheel hashes for this platform. When changing dependencies, update `requirements-build.in`, download matching wheels with `pip download --only-binary=:all: --no-deps -r requirements-build.in --dest <wheel-directory>`, regenerate using `python scripts/lock_wheels.py <wheel-directory>`, and test on a clean environment. Updating a package alone is not sufficient; review its transitive dependencies too.

Dependabot updates GitHub Actions. Python dependency updates are reviewed and regenerated on Windows: the stock pip updater does not resolve this custom Windows-wheel hash lock correctly. Do not accept an automated version edit without regenerating and testing the lock. Review upstream security notices and GitHub dependency alerts regularly.

## Commands

```powershell
python scripts/check_repository.py
python -m compileall -q source tests scripts
python -m unittest discover -s tests -v
python source/app.py --demo
python scripts/build_release.py bundle
python scripts/build_release.py installer
python scripts/build_release.py package
```

The installer stage needs Inno Setup 6. Use `--iscc PATH` if it is not in the standard location. Bundle and package stages do not need Inno Setup. Output is under ignored `release/`.

Use a complete Python installation that includes Tcl/Tk. If your local Python is split across directories, correct the installation; `TCL_LIBRARY`/`TK_LIBRARY` can diagnose runtime discovery but are not required by the clean CI image. The `.spec` file is version-controlled and includes Windows version metadata.

## Local overrides

`TITLEVISION_DATA_DIR` isolates the journal during development. `TITLEVISION_PROFILE_DIR` isolates browser profiles. Never point test code at production profiles. Updates go to the fixed public repository in `source/appmeta.py`; no GitHub secret is distributed with the app.

## Conventions

Keep rules separate from DOM selectors. Test a concrete failure mode rather than mirroring the implementation. Require read-only preview and revalidation for new write workflows. Use synthetic names/IDs in tests and documentation. UI and browser work must stay on their owning threads.
