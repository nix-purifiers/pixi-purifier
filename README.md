# pixi-purifier

Locked, Nix-resolved dependencies for Pixi.

## Quickstart

In a project with `pixi.toml` or Pixi configuration in `pyproject.toml`:

```sh
nix shell 'github:nix-purifiers/pixi-purifier'
pixi-purifier lock
pixi-purifier prefetch
pixi run check
```

Use a task from your own project in place of `check`. Commit `pixi.lock`
and `pixi-purifier.lock.json`. Prefetch creates the locked environments
with Nix and connects them to Pixi's normal `.pixi/envs` directory. Tasks
run in your working tree. `pixi shell` activates the environment too.

The wrapper can be installed through your usual Nix configuration. With no
purifier lock, it warns and runs ordinary, impure Pixi. Invalid or stale
locks fail with a repair command.

## Development loop

After changing dependencies in the manifest:

```sh
nix shell 'github:nix-purifiers/pixi-purifier'
pixi-purifier lock
pixi-purifier prefetch
pixi run check
```

Relocking preserves the native resolution. To update everything or selected
packages through Pixi's solver:

```sh
pixi-purifier update
pixi-purifier update python
pixi-purifier prefetch
```

The wrapper runs tasks and shells offline against the prebuilt environment.
Dependency-changing native commands direct you to edit the manifest and
use `pixi-purifier lock` or `update`. The environment itself is read-only;
source files and task outputs remain in the project.

When adopting an existing project, prefetch retains its generated native
environments at `.pixi/purifier-native-envs`. Removing the purifier lock
makes the wrapper restore that directory before returning to ordinary
Pixi. Unrelated environment symlinks are never replaced automatically.

## Working offline

```sh
nix shell 'github:nix-purifiers/pixi-purifier'
pixi-purifier prefetch
pixi run check
pixi shell
```

Prefetch keeps GC roots for the environments, archives, CLI, toolchain and
Python editor worker beside the selected lock. It installs the environments
available for the current platform. Conda packages and locked PyPI wheels
are supplied from Nix store files, with their native hashes checked.
Normal task execution uses Pixi's `--no-install` and `--frozen` behavior.
No generated project Nix files or development shell are required.

## Editor

For a Python environment, select `.pixi/envs/default/bin/python` as the
editor's interpreter. For another environment, substitute its name.
Prefetch supplies `pyright` and `pyright-langserver` in the wrapper package;
start the editor from the same `nix shell` so those workers are available.
Language servers declared as environment dependencies are available through
`pixi shell` as well.

The editor check starts a real language server and verifies that its
definition lookup reaches the locked `idna` package in the environment.

## Troubleshooting

- **Manifest or native lock changed:** run `pixi-purifier lock`, then `prefetch`.
- **Missing or damaged companion lock:** `lock` regenerates it while retaining
  a valid native resolution.
- **Wrong Pixi version:** use the wrapper, or override the scope's `pixi`
  and regenerate the companion using that version.
- **Read-only environment:** change dependencies through the manifest and lock.
  Package managers cannot modify a Nix store environment in place.
- **Unrelated `.pixi/envs` symlink:** move it before adopting the project.
  Existing generated directories are retained as described above.
- **Environment backup already exists:** move the additional native environment
  directory aside before prefetching; the previous backup is preserved.

Native and companion locks can live outside the source:

```sh
pixi-purifier \
  --pixi-lock ../locks/pixi.lock \
  --lockfile ../locks/pixi.json lock
pixi-purifier \
  --pixi-lock ../locks/pixi.lock \
  --lockfile ../locks/pixi.json prefetch
```

Set `PIXI_PURIFIER_PIXI_LOCK` and `PIXI_PURIFIER_LOCKFILE` to the same paths
when using the wrapper. A missing external native lock starts from the
working tree's native lock. Both commands leave that working copy alone.
Use `--manifest PATH` / `PIXI_PURIFIER_MANIFEST` to select a manifest for
the CLI; the native wrapper also recognizes Pixi's `--manifest-path`.

## Supported language repositories

HTTP(S) Conda archives and locked PyPI wheels are supported with native Pixi
lock format 7. The flake targets x86_64 and ARM Linux. Git/path dependencies,
PyPI source builds, and Pixi source-build backends are not yet supported.
The native block YAML format is parsed during Nix evaluation without
import-from-derivation; unsupported YAML forms fail with a repair command.

Coordinates, platform selections and archive hashes remain in `pixi.lock`.
The companion records input fingerprints, its content hash, the Pixi version,
and SHA-256 hashes only where the native record lacks them. Downloads use
the shared fetcher interface and may be replaced through `fetchers`.

No native Pixi plugin repository is needed. GitHub Pages hosts these docs.

## Examples

[`examples/python`](examples/python) combines Conda Python and the PyPI
`idna` wheel, locked for both supported architectures:

```sh
nix shell 'github:nix-purifiers/pixi-purifier'
cd examples/python
pixi-purifier prefetch
pixi run check
```

The checks install and run that environment in the Nix sandbox, compare the
pure YAML parser with the native format, test editor imports, reject stale,
tampered, incomplete and malformed locks, and use external locks. Host tests
exercise named updates against a real local Conda channel, then shut the
server down before executing tasks and building a release.

### Optional Nix build

The overlay adds only the `pixi-purifier` scope:

```nix
let
  pkgs = import nixpkgs {
    inherit system;
    overlays = [ purifier.overlays.default ];
  };
  project = pkgs.pixi-purifier.buildPixiProject {
    src = ./.;
    pixiLock = ../locks/pixi.lock;
    lockFile = ../locks/pixi.json;
  };
in {
  packages.default = project.packages.environment;
  checks.default = project.tests;
}
```

`packages` contains each locked environment available on the current
platform; `packages.environment` selects `default` or the first available
environment. The result also exposes `tests`, `release` and `fetches`.
The builder accepts `manifestFile`, `fetchers` and `testCommand`, and named
`callPackage` dependencies support scope overrides. The default test runs
the project's `check` task; override `testCommand` for a different suite.

`release` is a deterministic source archive containing the selected locks.
To upload that Nix-built artifact to a GitHub release:

```sh
pixi-purifier publish \
  --repo OWNER/PROJECT --tag v1.0.0
```

`lib.pixi-purifier.readLock` exposes the shared in-memory lock shape. CI
checks environment and release reproducibility with `nix build --rebuild`.

## Credits

The purifier idea was inspired by nixcloud's
[cargo (libnix)](https://github.com/nixcloud/cargo).
