"""Distribute run folders as portable .zip bundles.

A reviewer-friendly packager: select run folders, group them, and
emit one .zip per group containing `<runname>/view.html` +
`<runname>/results.jsonl`. Original run folders are NEVER modified.

The v2 review UI fetches `results.jsonl` next to itself when opened
directly, so the layout is extraction-safe — unzip anywhere and
double-click view.html to start reviewing.

CLI:
    python scripts/distribute.py \\
        --root output \\
        --out dist \\
        --group "H-surnames=ha,ho,he,hu,hi,h-rest" \\
        --group "G-surnames=g-all"

Or via groups file (one group per line, blank/# lines ignored):
    python scripts/distribute.py \\
        --root output \\
        --out dist \\
        --groups-file groups.txt

Exit codes:
    0   success (or dry-run)
    1   invalid input (bad group name, missing run, missing file)
"""
from __future__ import annotations

import argparse
import re
import sys
import zipfile
from dataclasses import dataclass
from pathlib import Path


_SLUG_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9 _.-]*[A-Za-z0-9])?$")


# ============================================================
# Group parsing
# ============================================================
@dataclass(frozen=True)
class Group:
    """One bundle: group_name → [run_name, ...]."""
    name: str
    run_names: tuple[str, ...]

    @classmethod
    def parse(cls, raw: str) -> "Group":
        """Parse 'NAME=run1,run2' from a CLI arg or file line."""
        if "=" not in raw:
            raise ValueError(
                f"invalid group spec {raw!r}: expected NAME=run1,run2"
            )
        name, _, runs_part = raw.partition("=")
        name = name.strip()
        if not _SLUG_RE.match(name):
            raise ValueError(
                f"invalid group name {name!r}: must contain only letters, "
                f"digits, spaces, hyphens, underscores, dots; no leading/"
                f"trailing separator"
            )
        run_names = tuple(r.strip() for r in runs_part.split(",") if r.strip())
        if not run_names:
            raise ValueError(
                f"group {name!r} has no run names"
            )
        return cls(name=name, run_names=run_names)

    @classmethod
    def parse_file(cls, path: Path) -> list["Group"]:
        """Parse one group per non-blank, non-comment line."""
        groups: list[Group] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            groups.append(cls.parse(stripped))
        return groups


# ============================================================
# Build
# ============================================================
def build_zip(
    group: Group,
    root: Path,
    out_dir: Path,
    *,
    include_view: bool = True,
    include_results: bool = True,
    dry_run: bool = False,
    log: "logging.Logger | None" = None,
) -> Path:
    """Build dist/<group_name>.zip from the named runs.

    Validates that each run folder exists and contains the required
    files. Original folders are not modified.

    Returns the zip path. Does NOT include the zip in any output
    during dry_run.
    """
    if log is None:
        import logging
        log = logging.getLogger("distribute")

    # Validate everything before writing anything.
    sources: list[tuple[Path, Path]] = []  # (absolute_src, archive_name)
    for run_name in group.run_names:
        run_dir = root / run_name
        if not run_dir.is_dir():
            raise FileNotFoundError(
                f"run {run_name!r}: directory not found at {run_dir}"
            )
        if include_view:
            src = run_dir / "view.html"
            if not src.is_file():
                raise FileNotFoundError(
                    f"run {run_name!r}: missing view.html in {run_dir}"
                )
            sources.append((src, Path(run_name) / "view.html"))
        if include_results:
            src = run_dir / "results.jsonl"
            if not src.is_file():
                raise FileNotFoundError(
                    f"run {run_name!r}: missing results.jsonl in {run_dir}"
                )
            sources.append((src, Path(run_name) / "results.jsonl"))

    out_dir.mkdir(parents=True, exist_ok=True)
    zip_path = out_dir / f"{group.name}.zip"

    if dry_run:
        log.info(
            "[dry-run] would build %s with %d files (%d runs)",
            zip_path, len(sources), len(group.run_names),
        )
        return zip_path

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for src, arcname in sources:
            zf.write(src, arcname.as_posix())
    log.info(
        "wrote %s (%d files, %d runs)",
        zip_path, len(sources), len(group.run_names),
    )
    return zip_path


# ============================================================
# CLI
# ============================================================
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Pack run folders into portable .zip bundles for sharing."
    )
    p.add_argument(
        "--root", type=Path, default=Path("output"),
        help="Root directory containing run folders (default: output/)",
    )
    p.add_argument(
        "--out", type=Path, default=Path("dist"),
        help="Output directory for .zip files (default: dist/)",
    )
    p.add_argument(
        "--group", action="append", default=[], metavar="NAME=runs",
        help="Group spec: NAME=run1,run2,... Repeatable.",
    )
    p.add_argument(
        "--groups-file", type=Path, default=None,
        help="Path to a file with one NAME=runs line per group.",
    )
    p.add_argument(
        "--skip-view-html", action="store_true",
        help="Exclude view.html from the zip.",
    )
    p.add_argument(
        "--skip-results", action="store_true",
        help="Exclude results.jsonl from the zip.",
    )
    p.add_argument(
        "--dry-run", action="store_true",
        help="Validate inputs and report what would be built; do not write.",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    import logging
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    log = logging.getLogger("distribute")

    args = build_parser().parse_args(argv)

    groups: list[Group] = []
    for raw in args.group:
        if not raw:
            continue
        try:
            groups.append(Group.parse(raw))
        except ValueError as e:
            log.error("%s", e)
            return 1
    if args.groups_file is not None:
        try:
            groups.extend(Group.parse_file(args.groups_file))
        except (FileNotFoundError, ValueError) as e:
            log.error("%s", e)
            return 1
    if not groups:
        log.error("no groups specified (use --group NAME=runs or --groups-file)")
        return 1

    failed = False
    for group in groups:
        try:
            build_zip(
                group,
                root=args.root,
                out_dir=args.out,
                include_view=not args.skip_view_html,
                include_results=not args.skip_results,
                dry_run=args.dry_run,
                log=log,
            )
        except FileNotFoundError as e:
            log.error("%s", e)
            failed = True
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())