#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Track upstream OpenOCD against the vendor patch series in patches/.

  status                show pin, distance from upstream HEAD, upstream changes in patched files
  check [REF]           apply the series to REF (default origin/master); report each patch
  pin REF [--stable]    check REF, then set source-commit (and grade: stable)
  flows [--update]      compare boards/ flash flows with their ArduinoCore-zephyr originals

Patch states reported by `check`:
  OK        applies cleanly
  UPSTREAM  already in upstream (reverse-applies): should be removed
  PARTIAL   some files already upstream, the rest conflict: re-port
  FAIL      conflicts: re-port by hand (see AGENTS.md)
A hint is added when upstream history contains a commit with the patch's subject.
"""
import argparse
import re
import subprocess
import sys
import tempfile
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
YAML = ROOT / "snap" / "snapcraft.yaml"
CACHE = ROOT / ".cache" / "upstream"
VENDORS = ("stm", "renesas")  # application order
FLOWS_REPO = "https://raw.githubusercontent.com/arduino/ArduinoCore-zephyr"
VARIANT = "variants/arduino_ventuno_q_stm32h5f5xx"
# boards/ copy -> verbatim upstream file (the flows the Arduino tooling uses)
FLOWS = {
    "boards/arduino_ventuno_q_flash_bootloader.cfg": f"{VARIANT}/flash_bootloader.cfg",
    "boards/arduino_ventuno_q_flash_sketch.cfg": f"{VARIANT}/flash_sketch.cfg",
}


def git(*args, cwd=CACHE, check=True):
    return subprocess.run(["git", *args], cwd=cwd, text=True, capture_output=True, check=check)


def die(msg, code=2):
    print(msg, file=sys.stderr)
    sys.exit(code)


def upstream_url():
    m = re.search(r"^\s*source:\s*(https://\S*openocd\S*\.git)\s*$", YAML.read_text(), re.M)
    return m.group(1) if m else die(f"cannot find upstream url in {YAML}")


def current_pin():
    m = re.search(r"^\s*source-commit:\s*([0-9a-f]{40})", YAML.read_text(), re.M)
    return m.group(1) if m else None


def sync_upstream():
    if (CACHE / ".git").is_dir():
        git("fetch", "-q", "--tags", "origin", "+refs/heads/master:refs/remotes/origin/master")
    else:
        CACHE.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "clone", "-q", "--filter=blob:none", "--no-checkout",
                        upstream_url(), str(CACHE)], check=True)


def resolve(ref):
    r = git("rev-parse", "--verify", "-q", f"{ref}^{{commit}}", check=False)
    return r.stdout.strip() if r.returncode == 0 else die(f"unknown ref: {ref}")


def short(sha):
    return git("log", "-1", "--format=%h %ad %s", "--date=short", sha).stdout.strip()


def series():
    return [p for v in VENDORS for p in sorted((ROOT / "patches" / v).glob("*.patch"))]


@dataclass
class Patch:
    path: Path
    subject: str = ""
    files: list = field(default_factory=list)

    @classmethod
    def parse(cls, path):
        text = path.read_text(errors="replace")
        m = re.search(r"^Subject: (?:\[PATCH[^\]]*\]\s*)?(.*?)\n(?=\S)", text, re.M | re.S)
        subject = " ".join(m.group(1).split()) if m else path.stem
        files = list(dict.fromkeys(re.findall(r"^diff --git a/(\S+) b/", text, re.M)))
        return cls(path, subject, files)

    @property
    def name(self):
        return str(self.path.relative_to(ROOT))


def upstream_subject_hit(patch, pin, ref):
    """Short sha of an upstream commit (pin..ref) with the same subject, if any."""
    if not pin:
        return None
    r = git("log", "--format=%h", "--fixed-strings", f"--grep={patch.subject}",
            "-1", f"{pin}..{ref}", check=False)
    return r.stdout.strip() or None


def classify(wt, patch):
    """Apply patch in worktree wt; return state."""
    before = git("rev-parse", "HEAD", cwd=wt).stdout
    am = git("-c", "user.name=check", "-c", "user.email=check@localhost",
             "am", "--3way", "-q", str(patch.path), cwd=wt, check=False)
    if am.returncode == 0:
        # "No changes -- Patch already applied": am succeeds without creating a commit
        return "UPSTREAM" if git("rev-parse", "HEAD", cwd=wt).stdout == before else "OK"
    git("am", "--abort", cwd=wt, check=False)
    # the 3-way apply left nothing behind; test what is already in the tree
    done = [f for f in patch.files
            if git("apply", "--reverse", "--check", f"--include={f}", str(patch.path),
                   cwd=wt, check=False).returncode == 0]
    if len(done) == len(patch.files):
        return "UPSTREAM"
    return "PARTIAL" if done else "FAIL"


def run_check(ref):
    sync_upstream()
    sha = resolve(ref)
    pin = current_pin()
    print(f"base: {short(sha)}")
    results = []
    with tempfile.TemporaryDirectory() as tmp:
        wt = Path(tmp) / "wt"
        git("worktree", "add", "-q", "--detach", str(wt), sha)
        try:
            for p in map(Patch.parse, series()):
                state = classify(wt, p)
                hint = upstream_subject_hit(p, pin, sha) if state != "OK" or pin else None
                results.append((p, state, hint))
        finally:
            git("worktree", "remove", "--force", str(wt), check=False)
            git("worktree", "prune", check=False)
    notes = {"UPSTREAM": "already upstream: remove it",
             "PARTIAL": "partly upstream: re-port",
             "FAIL": "conflicts: re-port, or drop if superseded"}
    for p, state, hint in results:
        line = f"{state:<9} {p.name}"
        if state in notes:
            line += f"  ({notes[state]})"
        if hint and state != "UPSTREAM":
            line += f"  [upstream commit {hint} has the same subject]"
        print(line)
    return results


def report_upstreamed(results):
    upstreamed = [p for p, state, _ in results if state == "UPSTREAM"]
    if upstreamed:
        print("\nThese patches are already in upstream; remove them from patches/ "
              "(and patches/patches.yaml):")
        for p in upstreamed:
            print(f"  {p.name}")
    return upstreamed


def cmd_status(_):
    sync_upstream()
    pin, head = current_pin(), resolve("origin/master")
    tag = git("describe", "--tags", "--abbrev=0", "--match", "v[0-9]*", head).stdout.strip()
    print(f"upstream: {upstream_url()}")
    print(f"head:     {short(head)}")
    print(f"last tag: {tag}")
    if not pin:
        print("base:     source-branch (follows HEAD)")
        return 0
    print(f"base:     {short(pin)} (pinned)")
    print(f"behind:   {git('rev-list', '--count', f'{pin}..{head}').stdout.strip()} commits")
    touched = {f for p in map(Patch.parse, series()) for f in p.files}
    changed = git("diff", "--name-only", pin, head).stdout.split()
    hit = sorted(touched.intersection(changed))
    print("upstream changes in files our patches touch:" + ("" if hit else " none"))
    for f in hit:
        print(f"  {f}")
    return 0


def cmd_check(args):
    results = run_check(args.ref)
    report_upstreamed(results)
    return 0 if all(s == "OK" for _, s, _ in results) else 1


def cmd_pin(args):
    results = run_check(args.ref)
    if report_upstreamed(results) or any(s != "OK" for _, s, _ in results):
        die("patches need attention; fix patches/ first", 1)
    sha = resolve(args.ref)
    text = YAML.read_text()
    if re.search(r"^\s*source-commit:", text, re.M):
        text = re.sub(r"^(\s*source-commit:).*$", rf"\g<1> {sha}", text, flags=re.M)
    else:
        text = re.sub(r"^(\s*)source-branch:.*$", rf"\g<1>source-commit: {sha}", text, flags=re.M)
    if args.stable:
        text = re.sub(r"^grade:.*$", "grade: stable", text, flags=re.M)
    YAML.write_text(text)
    print(f"pinned {YAML.relative_to(ROOT)} to {sha}")
    return 0


def cmd_flows(args):
    drift = 0
    for local, remote in FLOWS.items():
        url = f"{FLOWS_REPO}/{args.ref}/{remote}"
        try:
            with urllib.request.urlopen(url, timeout=30) as r:
                upstream = r.read().decode()
        except OSError as e:
            die(f"cannot fetch {url}: {e}")
        path = ROOT / local
        have = path.read_text() if path.exists() else None
        if have == upstream:
            print(f"OK     {local}")
        elif args.update:
            path.write_text(upstream)
            print(f"UPDATED {local}")
        else:
            print(f"DRIFT  {local}  (differs from {remote}@{args.ref})")
            drift += 1
    return 1 if drift else 0


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd")
    sub.add_parser("status").set_defaults(fn=cmd_status)
    c = sub.add_parser("check")
    c.add_argument("ref", nargs="?", default="origin/master")
    c.set_defaults(fn=cmd_check)
    p = sub.add_parser("pin")
    p.add_argument("ref")
    p.add_argument("--stable", action="store_true")
    p.set_defaults(fn=cmd_pin)
    f = sub.add_parser("flows")
    f.add_argument("ref", nargs="?", default="main")
    f.add_argument("--update", action="store_true")
    f.set_defaults(fn=cmd_flows)
    args = ap.parse_args()
    sys.exit(args.fn(args) if args.cmd else ap.print_help() or 2)


if __name__ == "__main__":
    main()
