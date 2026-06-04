#!/usr/bin/env python3
"""Generate the ``install_requires`` list for a Python script or package.

This walks the source with the ``ast`` module, collects every imported
top-level module, drops the standard library and any first-party modules that
live alongside the source, then maps the remaining import names to their real
PyPI distribution names (e.g. ``cv2`` -> ``opencv-python``, ``PIL`` ->
``Pillow``, ``bs4`` -> ``beautifulsoup4``).

It is intentionally dependency-free (stdlib only) so it can run anywhere.

Usage
-----
    # Print a ready-to-paste install_requires list for a single script
    python gen_install_requires.py myscript.py

    # Scan a whole package/source tree
    python gen_install_requires.py src/

    # Pin versions from the current environment
    python gen_install_requires.py src/ --pin

    # Write a requirements.txt instead of the python-list form
    python gen_install_requires.py src/ --format requirements -o requirements.txt
"""
from __future__ import annotations

import argparse
import ast
import os
import sys
from importlib import metadata

# Import-name -> PyPI-distribution-name fallbacks for packages that are not
# installed (so importlib can't tell us the mapping) or that map ambiguously.
KNOWN_ALIASES = {
    "cv2": "opencv-python",
    "PIL": "Pillow",
    "bs4": "beautifulsoup4",
    "yaml": "PyYAML",
    "sklearn": "scikit-learn",
    "skimage": "scikit-image",
    "dotenv": "python-dotenv",
    "dateutil": "python-dateutil",
    "OpenSSL": "pyOpenSSL",
    "Crypto": "pycryptodome",
    "google": "google-api-python-client",
    "jwt": "PyJWT",
    "serial": "pyserial",
    "usb": "pyusb",
    "Xlib": "python-xlib",
    "win32api": "pywin32",
    "psycopg2": "psycopg2-binary",
    "fitz": "PyMuPDF",
    "magic": "python-magic",
    "docx": "python-docx",
    "pptx": "python-pptx",
    "attr": "attrs",
    "lxml": "lxml",
    "PyQt5": "PyQt5",
}


def stdlib_names() -> frozenset[str]:
    """Top-level standard-library module names for the running interpreter."""
    names = set(getattr(sys, "stdlib_module_names", ()))  # 3.10+
    names.update(sys.builtin_module_names)
    return frozenset(names)


def iter_python_files(path: str):
    """Yield .py files for a single file or recursively for a directory."""
    if os.path.isfile(path):
        yield path
        return
    skip = {".git", "__pycache__", ".venv", "venv", "env",
            "build", "dist", ".tox", ".mypy_cache", "node_modules"}
    for root, dirs, files in os.walk(path):
        dirs[:] = [d for d in dirs if d not in skip and not d.endswith(".egg-info")]
        for name in files:
            if name.endswith(".py"):
                yield os.path.join(root, name)


def local_module_names(paths: list[str]) -> set[str]:
    """First-party top-level names: sibling .py files and package dirs."""
    local: set[str] = set()
    for path in paths:
        base = path if os.path.isdir(path) else os.path.dirname(path) or "."
        try:
            for entry in os.listdir(base):
                full = os.path.join(base, entry)
                if entry.endswith(".py"):
                    local.add(entry[:-3])
                elif os.path.isdir(full) and os.path.exists(
                    os.path.join(full, "__init__.py")
                ):
                    local.add(entry)
        except OSError:
            pass
        # the scanned file itself is first-party
        if os.path.isfile(path):
            local.add(os.path.splitext(os.path.basename(path))[0])
    return local


def collect_imports(files) -> set[str]:
    """Return the set of top-level imported module names across all files."""
    found: set[str] = set()
    for file in files:
        try:
            with open(file, "r", encoding="utf-8") as fh:
                tree = ast.parse(fh.read(), filename=file)
        except (SyntaxError, UnicodeDecodeError, OSError) as exc:
            print(f"warning: skipping {file}: {exc}", file=sys.stderr)
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    found.add(alias.name.split(".")[0])
            elif isinstance(node, ast.ImportFrom):
                # level > 0 means a relative import -> always first-party
                if node.level == 0 and node.module:
                    found.add(node.module.split(".")[0])
    return found


def build_dist_index() -> dict[str, str]:
    """Map every importable top-level name to its installed distribution."""
    index: dict[str, str] = {}
    # packages_distributions(): top_level_name -> [distribution names]
    mapping = getattr(metadata, "packages_distributions", lambda: {})()
    for top, dists in mapping.items():
        if dists:
            index[top] = dists[0]
    return index


def resolve(imports, stdlib, local, dist_index, pin):
    """Turn raw import names into (requirement_string, unresolved) outputs."""
    requirements: dict[str, str] = {}
    unresolved: set[str] = set()
    for name in sorted(imports):
        if name in stdlib or name in local or name.startswith("_"):
            continue
        dist = dist_index.get(name) or KNOWN_ALIASES.get(name)
        if dist is None:
            # Not installed and no known alias: best guess is the import name.
            unresolved.add(name)
            requirements[name] = name
            continue
        spec = dist
        if pin:
            try:
                spec = f"{dist}=={metadata.version(dist)}"
            except metadata.PackageNotFoundError:
                pass
        requirements[dist] = spec
    return requirements, unresolved


def render(requirements, fmt) -> str:
    items = sorted(requirements.values(), key=str.lower)
    if fmt == "requirements":
        return "\n".join(items) + ("\n" if items else "")
    if fmt == "list":
        return "[" + ", ".join(repr(i) for i in items) + "]"
    # setup.py snippet
    body = ",".join(f"'{i}'" for i in items)
    return f"install_requires=[{body}]"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("path", help="Python file or directory to scan")
    parser.add_argument("--pin", action="store_true",
                        help="Pin to installed versions (dist==x.y.z)")
    parser.add_argument("--format", choices=["setup", "list", "requirements"],
                        default="setup", help="Output format (default: setup)")
    parser.add_argument("-o", "--output",
                        help="Write to this file instead of stdout")
    args = parser.parse_args(argv)

    if not os.path.exists(args.path):
        print(f"error: no such path: {args.path}", file=sys.stderr)
        return 2

    files = list(iter_python_files(args.path))
    if not files:
        print("error: no .py files found", file=sys.stderr)
        return 2

    imports = collect_imports(files)
    stdlib = stdlib_names()
    local = local_module_names([args.path])
    dist_index = build_dist_index()

    requirements, unresolved = resolve(imports, stdlib, local, dist_index, args.pin)
    output = render(requirements, args.format)

    if args.output:
        with open(args.output, "w", encoding="utf-8") as fh:
            fh.write(output + "\n")
        print(f"wrote {len(requirements)} requirement(s) to {args.output}",
              file=sys.stderr)
    else:
        print(output)

    if unresolved:
        print(
            "\nnote: these imports are not installed here, so the name is a "
            "guess — verify the PyPI name:\n  " + ", ".join(sorted(unresolved)),
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
