# index-lantern

[![CI](https://github.com/KanadeK/index-lantern/actions/workflows/ci.yml/badge.svg)](https://github.com/KanadeK/index-lantern/actions/workflows/ci.yml)

Find raw file differences hidden behind Git's `assume-unchanged` and `skip-worktree`
index flags. Inspect before switching branches, retiring a worktree or handing a
checkout to someone else. The tool leaves the index, flags and worktree untouched.

Python 3.11+, Git 2.43+, no Python runtime dependencies. [中文](README.zh-CN.md)

Current version: **0.1.1**. Windows users should use this patch release or later
for junction detection on Python 3.11.

## Install and try

```sh
git clone https://github.com/KanadeK/index-lantern.git
cd index-lantern
python -m venv .venv
```

Activate the environment (`source .venv/bin/activate` on macOS/Linux,
`.venv\Scripts\Activate.ps1` in PowerShell), then:

```sh
python -m pip install .
python examples/demo.py
index-lantern /path/to/repository
index-lantern /path/to/repository --json
```

The demo creates a disposable Git fixture, changes an assumed-unchanged file,
checks the nonzero diagnostic, proves that the index bytes did not change, then
restores the original bytes and checks success. It does not push or use credentials.
Prebuilt wheels are also available in [Releases](https://github.com/KanadeK/index-lantern/releases).
There is no PyPI publication; use the checkout or release wheel.

## Interpret the evidence

`git ls-files -v` lists flags. index-lantern additionally streams each flagged file
through Git's blob hash framing, then compares that hash to its indexed object ID.
It never invokes a clean/smudge filter, textconv, a hook or a network command.

| State | Meaning |
|---|---|
| `raw-match` | Raw bytes hash to the indexed blob ID |
| `raw-different` | Raw bytes differ; Git checkout conversion may explain this |
| `missing-assumed` | An assumed-unchanged path is absent without skip-worktree |
| `absent-skipped` | A skipped path is absent, normal for sparse checkout |
| `type-changed` | A regular file became a symlink, directory or special file |
| `not-inspected` | Unsupported entry, unsafe parent, read failure, race or limit |

**Raw comparison is deliberately not `git diff`.** CRLF conversion, `ident`,
working-tree encoding and filters can produce a `raw-different` result without a
user edit. Review your attributes before acting. No file contents or worktree
hashes are printed; the report includes indexed IDs, names, flags and byte counts.
Symlink entries compare the link target text without following it. With
`core.symlinks=false`, a link represented by a plain file is compared as raw bytes.
Executable permission changes are outside this content-only check.

Exit codes:

- **0:** selected gate passed and every flagged entry was inspected.
- **1:** selected gate failed (default: raw divergence, missing assumed file or type change).
- **2:** incomplete inspection or invalid input, regardless of `--fail-on`.

```sh
index-lantern . --fail-on flags       # fail when any hidden flag exists
index-lantern . --fail-on none --json # inventory; incomplete inspections still exit 2
index-lantern . --max-bytes 134217728 --max-entries 200000
```

JSON schema version 1 includes `complete`, `flagged`, `counts`, `entries` and
`comparison`. With `--json`, runtime failures produce one JSON object with an
`error`; argparse usage errors use stderr. Text mode escapes unusual path names.

## Boundaries and cleanup

- Only flagged indexed paths are examined, not all changes, ignored/untracked
  files, committed history, reflogs or nested repository contents.
- Linked worktrees and SHA-1/SHA-256 repositories are supported; bare repositories
  have no worktree and are rejected. Gitlinks and unmerged flagged entries are
  reported as not inspected.
- Parent symlinks/junctions are refused. Files are streamed with a default 64 MiB
  per-file limit and 100,000 total index entries. Git commands time out after
  60 seconds. Git's listing is captured in memory before the entry limit check;
  this is not a hard process memory quota.
- Stop concurrent writers. The tool checks index stability and per-file metadata,
  but does not provide an atomic filesystem snapshot or a hostile-process sandbox.
- Global/system Git configuration and inherited `GIT_*` variables are excluded;
  repository discovery/config remain relevant. External filesystem monitoring is
  disabled. Git is a separately installed dependency.
- This is a diagnostic, not a backup or permission to delete data. Keep real
  backups. No command here clears flags or discards files automatically.

Uninstall: `python -m pip uninstall index-lantern`. Remove the dedicated venv and
checkout if no longer needed. No service or persistent cache is installed.

## Why this tool

Git [documents](https://git-scm.com/docs/git-update-index) that these flags do not
provide a reliable ignore mechanism for tracked files. A
[pre-commit report](https://github.com/pre-commit/pre-commit/issues/3027) illustrates
the consequences of hidden local edits. Editors such as
[Git Sweep](https://github.com/jellyedwards/gitsweep) help set flags; this command
provides repeatable, content-aware inspection without changing them. It does not
replace those editors or Git's status command. No third-party source was copied.

See [CONTRIBUTING](CONTRIBUTING.md), [SECURITY](SECURITY.md), and [MIT license](LICENSE).
