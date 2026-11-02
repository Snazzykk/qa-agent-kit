#!/usr/bin/env python3
"""Copy the small Python API blueprint without replacing existing files."""
from __future__ import annotations

import argparse
from pathlib import Path
import stat


ASSETS = Path(__file__).resolve().parents[1] / "assets" / "python-api"


def is_link_or_reparse(path: Path) -> bool:
    try:
        info = path.lstat()
    except FileNotFoundError:
        return False
    return stat.S_ISLNK(info.st_mode) or bool(
        getattr(info, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    )


def check_plain_ancestors(path: Path) -> None:
    for component in (path, *path.parents):
        if is_link_or_reparse(component):
            raise ValueError(f"Linked/reparse paths are preserved; no files written: {component}")


def create_skeleton(target: Path, dry_run: bool = False) -> list[Path]:
    original = target.expanduser().absolute()
    check_plain_ancestors(original)
    target = original.resolve()
    if target == ASSETS or ASSETS in target.parents:
        raise ValueError("Choose a QA project outside the bundled assets")
    if target.exists() and not target.is_dir():
        raise ValueError(f"Target is not a directory: {target}")
    check_plain_ancestors(ASSETS)
    files = []
    for path in sorted(ASSETS.rglob("*")):
        if is_link_or_reparse(path):
            raise ValueError(f"Bundled assets must contain ordinary files and directories: {path}")
        if path.is_dir():
            continue
        if not stat.S_ISREG(path.lstat().st_mode):
            raise ValueError(f"Bundled asset is not a regular file: {path}")
        if path.suffix not in {".pyc", ".pyo"} and not {"__pycache__", ".pytest_cache"}.intersection(
            path.relative_to(ASSETS).parts
        ):
            files.append(path)
    if not files:
        raise ValueError("Bundled Python API assets are missing")
    outputs = [target / path.relative_to(ASSETS) for path in files]
    conflicts = []
    for output in outputs:
        check_plain_ancestors(output)
        if output.exists() or output.is_symlink():
            conflicts.append(output.relative_to(target).as_posix())
        for parent in output.parents:
            if parent == target:
                break
            if parent.is_symlink() or (parent.exists() and not parent.is_dir()):
                conflicts.append(parent.relative_to(target).as_posix())
                break
    if conflicts:
        raise ValueError("Existing paths preserved; no files written: " + ", ".join(sorted(set(conflicts))))
    if not dry_run:
        for source, output in zip(files, outputs):
            check_plain_ancestors(output)
            output.parent.mkdir(parents=True, exist_ok=True)
            with output.open("xb") as stream:
                stream.write(source.read_bytes())
    return outputs


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("repo", type=Path, help="QA project directory")
    parser.add_argument("--dry-run", action="store_true", help="List outputs without writing")
    args = parser.parse_args()
    try:
        outputs = create_skeleton(args.repo, args.dry_run)
    except (OSError, ValueError) as error:
        parser.exit(2, f"{error}\n")
    for output in outputs:
        print(output)
    print(f"{'Would create' if args.dry_run else 'Created'} {len(outputs)} files; demo tests use no network.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
