#!/usr/bin/env python3
# Copyright (c) Qualcomm Technologies, Inc. and/or its subsidiaries.
# SPDX-License-Identifier: BSD-3-Clause
"""
memory-analysis -- LAVA job helper (Mode 5)

Builds the LAVA job that runs the qcom-linux-testkit Memory_Snapshot suite --
the same test definition entry lava-test-plans uses in
testcases/performance.yaml -- and, for CI without an agent, fetches a finished
job's results over the LAVA REST API.

Inside an agent session the job is submitted and fetched with the lava MCP
tools (validate_job / submit_job / get_job / get_job_results / get_job_logs);
see SKILL.md, Mode 5. This script only has to produce the YAML they take.

Usage:
    # Snapshot: flash, boot, one Memory_Snapshot
    python lava_job.py render --device-type lemans-evk -o job.yaml

    # Workload impact: baseline snapshot, start workload, active snapshot, stop
    python lava_job.py render --device-type lemans-evk --workload camera_h264_encoding -o job.yaml
    python lava_job.py render --device-type lemans-evk \\
        --command "gst-launch-1.0 videotestsrc ! fakesink" --workload-name vts -o job.yaml

    # Fetch a finished job without the MCP server (public jobs need no token;
    # set LAVA_TOKEN for private ones)
    python lava_job.py fetch --job-id 516300 --output-dir results/lava_516300/lava

    # Then: python run.py --lava-results results/lava_516300/lava
"""

import argparse
import json
import os
import shlex
import sys
import urllib.request
from pathlib import Path

SKILL_DIR    = Path(__file__).resolve().parents[1]
TEMPLATE_DIR = SKILL_DIR / "lava" / "boot-templates"
PRESETS_FILE = SKILL_DIR / "usecases" / "presets.json"

DEFAULT_LAVA_URL     = "https://lava.infra.foundries.io"
# Memory_Snapshot lives in this fork until it is merged upstream.
DEFAULT_TESTKIT_REPO = "https://github.com/saks-singh/qcom-linux-testkit"
DEFAULT_TESTKIT_REF  = "1ad25425ec2695a2559e1d7f336e9b3f34cf703a"
SUITE_PATH = "Runner/suites/Performance/Memory_Snapshot/memory-snapshot.yaml"

TAG = "[memory-analysis]"


# ---------------------------------------------------------------------------
# YAML (PyYAML is only needed to render; fetch is stdlib-only)
# ---------------------------------------------------------------------------

def _yaml():
    try:
        import yaml
    except ImportError:
        print(f"{TAG} ERROR: rendering a LAVA job needs PyYAML (pip install pyyaml)")
        sys.exit(1)
    return yaml


# ---------------------------------------------------------------------------
# render
# ---------------------------------------------------------------------------

def testkit_tarball(repo: str, ref: str) -> str:
    return f"{repo.rstrip('/')}/archive/{ref}.tar.gz"


def snapshot_definition(repo_url: str, name: str, label: str,
                        out_dir: str, settle: int) -> dict:
    """The Memory_Snapshot entry, in the form lava-test-plans renders it."""
    return {
        "from": "url",
        "name": name,
        "path": SUITE_PATH,
        "repository": repo_url,
        "strip-components": 1,
        "parameters": {
            "LABEL": label,
            "OUT_DIR": out_dir,
            "SETTLE_SECS": str(settle),
        },
    }


def inline_definition(name: str, description: str, steps: list) -> dict:
    return {
        "from": "inline",
        "name": name,
        "path": f"inline/{name}.yaml",
        "repository": {
            "metadata": {
                "format": "Lava-Test Test Definition 1.0",
                "name": name,
                "description": description,
            },
            "run": {"steps": steps},
        },
    }


def workload_steps(command: str, setup: list, wait_sec: int, unit: str) -> list:
    """Start the workload as a transient systemd unit, as run.py Mode 2 does."""
    q = shlex.quote
    steps = list(setup)
    steps += [
        f"systemd-run --unit={unit} --working-directory=/ sh -c {q(command)}",
        f"sleep {int(wait_sec)}",
        f"if systemctl is-active --quiet {unit}; then "
        f"lava-test-case workload-alive --result pass; else "
        f"lava-test-case workload-alive --result fail; "
        f"journalctl -u {unit} --no-pager -n 20 || true; fi",
    ]
    return steps


def teardown_steps(teardown: list, unit: str) -> list:
    return [f"systemctl stop {unit} 2>/dev/null || true"] + list(teardown) + [
        "lava-test-case workload-stopped --result pass"]


def load_preset(name: str) -> dict:
    with open(PRESETS_FILE, encoding="utf-8") as f:
        data = json.load(f)
    presets = data.get("presets", data)
    if name not in presets:
        available = ", ".join(k for k in presets if not k.startswith("_"))
        print(f"{TAG} ERROR: preset '{name}' not found. Available presets: {available}")
        sys.exit(1)
    return presets[name]


def render(args) -> int:
    yaml = _yaml()
    template = Path(args.boot_template) if args.boot_template else \
        TEMPLATE_DIR / f"{args.device_type}.yaml"
    if not template.is_file():
        have = ", ".join(sorted(p.stem for p in TEMPLATE_DIR.glob("*.yaml")))
        print(f"{TAG} ERROR: no boot template for '{args.device_type}' at {template}")
        print(f"  Available: {have or 'none'}. Pass --boot-template, built from a")
        print(f"  successful job's deploy+boot actions (lava MCP: find_boot_template).")
        return 1
    with open(template, encoding="utf-8") as f:
        job = yaml.safe_load(f)

    if args.image_url:
        for action in job["actions"]:
            for spec in action.get("deploy", {}).values():
                if isinstance(spec, dict) and "url" in spec:
                    spec["url"] = args.image_url

    repo = testkit_tarball(args.testkit_repo, args.testkit_ref)
    settle = args.settle

    if args.workload or args.command:
        if args.workload:
            preset   = load_preset(args.workload)
            command  = preset["command"]
            setup    = preset.get("setup", [])
            teardown = preset.get("teardown", [])
            wait_sec = args.wait or preset.get("wait_sec", 15)
            name     = args.workload
        else:
            if not args.workload_name:
                print(f"{TAG} ERROR: --workload-name is required with --command")
                return 1
            command, setup, teardown = args.command, [], []
            wait_sec = args.wait or 15
            name     = args.workload_name
        safe = "".join(c if c.isalnum() or c == "-" else "-" for c in name.lower())
        unit = f"mem-skill-{safe}"
        definitions = [
            snapshot_definition(repo, "Memory_Snapshot_baseline", "baseline",
                                "./logs_Memory_Snapshot_baseline", settle),
            inline_definition("workload_start", f"start {name} as {unit}",
                              workload_steps(command, setup, wait_sec, unit)),
            snapshot_definition(repo, "Memory_Snapshot_active", "active",
                                "./logs_Memory_Snapshot_active", 0),
            inline_definition("workload_stop", f"stop {unit}",
                              teardown_steps(teardown, unit)),
        ]
        job_name = f"{args.device_type} memory-analysis workload {name}"
        meta = {"workload": name, "workload_command": command}
    else:
        definitions = [snapshot_definition(repo, "Memory_Snapshot", args.label,
                                           "./logs_Memory_Snapshot", settle)]
        job_name = f"{args.device_type} memory-analysis snapshot"
        meta = {}

    out = {"job_name": args.job_name or job_name}
    out.update({k: v for k, v in job.items() if k != "actions"})
    out["device_type"] = args.device_type
    out["metadata"] = {
        "skill": "qcom-perf-skills/memory-analysis (Mode 5: LAVA)",
        "testkit": args.testkit_repo,
        "testkit_ref": args.testkit_ref,
        "suite": SUITE_PATH,
        **meta,
    }
    out["actions"] = list(job["actions"]) + [{
        "test": {"timeout": {"minutes": args.test_timeout}, "definitions": definitions}
    }]

    text = yaml.safe_dump(out, sort_keys=False, width=100)
    if args.output:
        with open(args.output, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
        print(f"{TAG} LAVA job written to {args.output}")
    else:
        sys.stdout.write(text)
    return 0


# ---------------------------------------------------------------------------
# fetch (REST fallback for the lava MCP tools)
# ---------------------------------------------------------------------------

def _get(url: str, token: str | None):
    req = urllib.request.Request(url)
    if token:
        req.add_header("Authorization", f"Token {token}")
    with urllib.request.urlopen(req, timeout=60) as resp:
        return resp.read().decode("utf-8", errors="replace")


def fetch(args) -> int:
    base  = args.lava_url.rstrip("/") + "/api/v0.3"
    token = os.environ.get("LAVA_TOKEN")
    out   = Path(args.output_dir)
    out.mkdir(parents=True, exist_ok=True)

    job = json.loads(_get(f"{base}/jobs/{args.job_id}/", token))
    if job.get("state") != "Finished":
        print(f"{TAG} ERROR: job {args.job_id} is {job.get('state')}, not Finished")
        return 1
    (out / "job.json").write_text(json.dumps(job, indent=2), encoding="utf-8")

    results, url = [], f"{base}/jobs/{args.job_id}/tests/?limit=500"
    while url:
        page = json.loads(_get(url, token))
        results += page.get("results", [])
        url = page.get("next")
    (out / "results.json").write_text(
        json.dumps({"count": len(results), "results": results}, indent=2), encoding="utf-8")

    (out / "logs.yaml").write_text(_get(f"{base}/jobs/{args.job_id}/logs/", token),
                                   encoding="utf-8")
    print(f"{TAG} Job {args.job_id} ({job.get('health')}): "
          f"{len(results)} results -> {out}")
    return 0


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(prog="lava_job",
                                     description="LAVA job helper for memory-analysis Mode 5.")
    sub = parser.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("render", help="Write the LAVA job YAML")
    r.add_argument("--device-type", required=True, help="LAVA device type, e.g. lemans-evk")
    r.add_argument("--boot-template", default=None,
                   help="YAML with the deploy+boot actions (default: lava/boot-templates/<device-type>.yaml)")
    r.add_argument("--image-url", default=None, help="Replace the deploy url in the template")
    r.add_argument("--testkit-repo", default=DEFAULT_TESTKIT_REPO,
                   help=f"qcom-linux-testkit repository (default: {DEFAULT_TESTKIT_REPO})")
    r.add_argument("--testkit-ref", default=DEFAULT_TESTKIT_REF,
                   help="Branch, tag or commit to fetch the suite from (pin a commit for reproducible runs)")
    r.add_argument("--label", default="snapshot", help="Snapshot label (snapshot mode)")
    r.add_argument("--settle", type=int, default=20,
                   help="Seconds the first snapshot waits after login (default: 20)")
    w = r.add_mutually_exclusive_group()
    w.add_argument("--workload", metavar="PRESET", help="Preset from usecases/presets.json")
    w.add_argument("--command", metavar="CMD", help="Custom workload command")
    r.add_argument("--workload-name", default=None, help="Label when using --command")
    r.add_argument("--wait", type=int, default=None, help="Seconds the workload runs before the active snapshot")
    r.add_argument("--job-name", default=None)
    r.add_argument("--test-timeout", type=int, default=20, help="Test action timeout, minutes")
    r.add_argument("-o", "--output", default=None, help="Output file (default: stdout)")

    fch = sub.add_parser("fetch", help="Save a finished job's results, definition and log")
    fch.add_argument("--job-id", type=int, required=True)
    fch.add_argument("--lava-url", default=DEFAULT_LAVA_URL)
    fch.add_argument("--output-dir", required=True)

    args = parser.parse_args()
    return render(args) if args.cmd == "render" else fetch(args)


if __name__ == "__main__":
    sys.exit(main())
