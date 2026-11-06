# Agent instructions

## Channels and branches

- **Current state:** edge and stable are identical, both built from the `source-commit` pinned in `snap/snapcraft.yaml` (`grade: stable`).
- **Planned split:** `main` = edge (`source-branch: master`, `grade: devel`, builds upstream HEAD; a non-applying patch fails the build), `stable` branch = pinned `source-commit`. Upstream releases are rare (v0.12.0 is 2023) and the patches target current master, so stable is a promoted known-good master commit, not a tag.
- `patches/patches.yaml` records origin, status and tested base of every patch. Update it whenever patches change.

## Scripted helper

`scripts/openocd_snap.py` does the mechanical parts:

    scripts/openocd_snap.py status              # base, distance from HEAD, upstream changes in patched files
    scripts/openocd_snap.py check [REF]         # apply the series to REF in a scratch worktree
    scripts/openocd_snap.py pin REF [--stable]  # check, then pin source-commit (use on the stable branch)

`check` prints OK / UPSTREAM (patch already in upstream: remove it from patches/ and patches.yaml) / FAIL (re-port by hand, see step 3).
Everything else (re-porting, importing new vendor work, build verification) follows the steps below.
Promote edge to stable: on the `stable` branch run `scripts/openocd_snap.py pin <tested-sha> --stable`, run `snapcraft pack`, update `tested_base` in `patches/patches.yaml`.

## Updating the snap against upstream

Use this runbook when asked to track/bump upstream, refresh vendor patches, or check what STM/Renesas changes are still missing upstream.

This repo packages upstream OpenOCD plus a small vendor delta. It holds no OpenOCD source:

- `snap/snapcraft.yaml`: part `openocd` has `source` (upstream URL) plus `source-branch: master` (edge) or `source-commit` (stable pin).
- `patches/stm/*.patch`: from STMicroelectronics `openocd-cubeide-*` branches.
- `patches/renesas/*.patch`: from `renesas-rz/rzg_openocd` (a patch series, not a fork).
- Patches are applied in order (stm, then renesas) with `git apply --index` in `override-pull`.
- Vendor scripts are split into snap components (`stm32`, `renesas`) via `organize:` globs.

Work in a scratch directory inside the project (e.g. `./tmp`, delete it at the end). Never modify the vendor repos. Run each step before moving on and report results briefly.

## Inputs (ask only if not discoverable)

- `UPSTREAM`: URL from `source:` in snapcraft.yaml.
- `PIN`: current `source-commit` (empty on edge; use `scripts/openocd_snap.py status`).
- `STM_REPO`, `STM_BRANCH`: local clone and newest `openocd-cubeide-rN` branch (`git branch -r | sort -V`).
- `RZ_REPO`: local clone of rzg_openocd (`git pull`, then check whether patch files changed).

## 1. Check for new upstream commits

```sh
mkdir -p tmp && cd tmp
git clone --filter=blob:none "$UPSTREAM" up && cd up
git log --oneline $PIN..origin/master | wc -l      # how far behind
git log --format='%h %ad %s' --date=short $PIN..origin/master -- \
  src/flash/nor src/target tcl/target contrib/loaders | head -50   # relevant changes
```

Summarize: commit count, newest date, and anything touching files our patches touch:

```sh
grep -h '^diff --git' ../../patches/*/*.patch | awk '{print $3}' | sed 's#^a/##' | sort -u > ../touched.txt
git diff --name-only $PIN origin/master | grep -Fxf ../touched.txt
```

If nothing is new, stop and report.

## 2. Pick the new pin

Default: `origin/master` HEAD. Use a tagged release instead if the user asks. Record the full 40-char hash (`git rev-parse`). Never invent a hash; always take it from `git rev-parse`.

## 3. Test existing patches against the new pin

```sh
git checkout -q -b try NEWPIN && git config user.email t@t && git config user.name t
for p in ../../patches/stm/*.patch ../../patches/renesas/*.patch; do
  git am --3way "$p" >/dev/null 2>&1 && echo "OK   $p" || { echo "FAIL $p"; git am --abort; }
done
```

Classify each failing patch:

- **Upstreamed:** the feature or file now exists upstream (`git log --oneline $PIN..NEWPIN --grep=<keyword>`, `git grep -i <chip or symbol> NEWPIN -- src tcl`). Drop the patch.
- **Context drift:** the change is still missing upstream but hunks moved. Re-port by hand (resolve the conflict, `git am --continue`) and keep the commit message.
- **Superseded:** upstream implemented the same thing differently. Drop it and note why.

For patches that applied, still check they are not now redundant (`git cherry NEWPIN try`: `-` lines are already upstream).

## 4. Pull new vendor work

STM (new commits since the last imported release):

```sh
git fetch "$STM_REPO" "$STM_BRANCH:stm"
mb=$(git merge-base NEWPIN stm)
git log --no-merges --reverse --format='%h %s' --cherry-pick --right-only NEWPIN...stm
```

- Candidates are STM-only commits. Ignore branding/docs commits (README, cover page, fork link), cortex_a, watchpoint, cache and target-core refactors (they conflict deeply and are intentionally not carried) unless the user asks.
- Valuable sets: new flash drivers (`stm32h5x`, `stldr`), new device support in `stm32l4x`/`stm32h7x`/`bluenrg-x`, new `tcl/target` and `tcl/board` configs.
- Do not rebase commit by commit (skips cascade). Use `git merge --no-commit stm`, resolve per file:
  - Files upstream already supports well: keep upstream.
  - STM driver files that are supersets (`stm32l4x`, `stm32h7x`, `bluenrg-x`): take STM's whole file (`git checkout stm -- <file>`). Per-hunk merges give files that do not compile.
  - Register new drivers in `src/flash/nor/drivers.c` and `driver.h` (check for duplicates).
- Commit as a few topical commits (tcl, doc, flash) on top of NEWPIN, then `git format-patch -N`.

Renesas: `diff -r` the repo's `*.patch` against `patches/renesas`. Use only the series referenced by its `build_openocd.sh`; ignore stale duplicates. Apply new ones with `git am --3way` as in step 3.

## 5. Build and smoke test the scratch tree

```sh
./bootstrap && ./configure --enable-internal-jimtcl --enable-stlink --disable-werror
make -j"$(nproc)" 2>&1 | grep -E 'error:|\*\*\*'
./src/openocd --version
strings src/openocd | grep -c -E 'stm32h5x|stldr'
```

If jimtcl is not populated in a scratch clone, copy it from a checkout that has the submodule. Fix compile errors before going further.

## 6. Write the results into the repo

1. Replace the contents of `patches/stm/` and `patches/renesas/` with the regenerated series (`git format-patch -N`, numbered from 0001, one directory per vendor).
2. Stable: `scripts/openocd_snap.py pin <sha> --stable`; edge needs no pin. Also update `tested_base` in `patches/patches.yaml`.
3. If new vendor scripts appeared, make sure the `organize:` globs cover them (e.g. new `stm32*`, `renesas_*` files) and that no vendor file stays in the base snap.
4. Update `README.md` if patch contents or the carried/not-carried list changed.

## 7. Verify with the real build

```sh
snapcraft pack
unsquashfs -l openocd+stm32.comp | grep -c scripts/       # expect > 0
unsquashfs -l openocd_*.snap | grep -cE 'scripts/target/(stm32|renesas)'   # expect 0
```

Optionally extract the snap and run `snap/local/openocd-wrapper` with `SNAP`, `SNAP_COMPONENTS` and `LD_LIBRARY_PATH` pointing at the extracted trees to confirm a component's config is found only when present.

## 8. Report

Give a short summary: old pin and new pin (with commit count and date range), per-patch status (kept / re-ported / dropped and why), vendor commits imported or deliberately skipped, build result. Remove `tmp/`, `*.snap` and `*.comp` before finishing. Do not commit unless asked.
