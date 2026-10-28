#!/usr/bin/env python3
# Copyright (c) Qualcomm Technologies, Inc. and/or its subsidiaries.
# SPDX-License-Identifier: BSD-3-Clause
"""
lava-integration -- LAVA results -> MemorySnapshot adapter

Rebuilds skill-shaped snapshot.json files from a finished LAVA job that ran
the qcom-linux-testkit Performance/Memory_Snapshot suite.

The suite writes its own snapshot.json on the DUT, but LAVA does not bring
files back from the board. What LAVA does keep is every snapshot-* test case
(with its measurement) and the job log (with the suite's device and summary
prints). This script reads those and produces, for every Memory_Snapshot run
in the job, a snapshot.json whose "sources" have the same "parsed" shapes that
collect.py produces -- so compare_snapshots.py, analyze_kernel_diff.py,
analyze_userspace_diff.py and generate_report.py consume it unchanged.

What LAVA cannot carry is marked "available": false, exactly as collect.py
does for a source it could not read, and recorded in collection_errors:
  - per-cache slabinfo  (only the slabinfo total is published)
  - smaps               (per-mapping detail stays on the DUT)
  - DT reserved-memory  (only the node count is published)
  - procrank VSS/RSS    (the suite publishes PSS only)

Inputs (all as saved from the lava MCP tools or the LAVA REST API):
  --results  get_job_results output: {"results": [...]}, a bare list, or a
             spill file containing the JSON somewhere inside it
  --job      get_job output (optional; device / job metadata)
  --logs     get_job_logs output (optional; device identity, snapshot id,
             label, process-name casing). Either the {"result": "..."} wrapper
             or the raw YAML log text.

Usage:
    python lava_to_snapshot.py --results results.json [--job job.json]
                               [--logs logs.yaml] --output-dir lava_snapshots/

Output:
    <output-dir>/<label>/snapshot.json  (one per Memory_Snapshot run)
    <output-dir>/index.json             ([{definition, label, path}], in run order)
"""

import argparse
import json
import os
import re
import sys
import uuid

SUITE = "Memory_Snapshot"
PAGE_KB = 4  # the suite publishes CMA in pages; Qualcomm Linux uses 4K pages

# /proc/meminfo field names, keyed by the LAVA-safe case id fragment the suite
# derives from them (lower-cased, anything outside [a-z0-9_-] turned into '-').
MEMINFO_FIELDS = [
    "MemTotal", "MemFree", "MemAvailable", "Buffers", "Cached", "SwapCached",
    "Active", "Inactive", "Active(anon)", "Inactive(anon)", "Active(file)",
    "Inactive(file)", "Unevictable", "Mlocked", "SwapTotal", "SwapFree",
    "Zswap", "Zswapped", "Dirty", "Writeback", "AnonPages", "Mapped", "Shmem",
    "KReclaimable", "Slab", "SReclaimable", "SUnreclaim", "KernelStack",
    "ShadowCallStack", "PageTables", "SecPageTables", "NFS_Unstable", "Bounce",
    "WritebackTmp", "CommitLimit", "Committed_AS", "VmallocTotal",
    "VmallocUsed", "VmallocChunk", "Percpu", "HardwareCorrupted",
    "AnonHugePages", "ShmemHugePages", "ShmemPmdMapped", "FileHugePages",
    "FilePmdMapped", "CmaTotal", "CmaFree", "Unaccepted", "HugePages_Total",
    "HugePages_Free", "HugePages_Rsvd", "HugePages_Surp", "Hugepagesize",
    "Hugetlb", "DirectMap4k", "DirectMap2M", "DirectMap1G",
]


def sanitize_id(text: str) -> str:
    """Python twin of the suite's sanitize_id(), so names can be matched back."""
    s = re.sub(r"[^a-z0-9_-]", "-", text.lower())
    return re.sub(r"-+", "-", s).strip("-")


MEMINFO_BY_ID = {sanitize_id(f): f for f in MEMINFO_FIELDS}


# ---------------------------------------------------------------------------
# Input loading
# ---------------------------------------------------------------------------

def _read(path: str) -> str:
    with open(path, encoding="utf-8", errors="replace") as f:
        return f.read()


def load_results(path: str) -> list:
    """Load LAVA test-case records, tolerating the shapes the tools return."""
    text = _read(path)
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        # MCP tool output that overflowed into a file: take the JSON array.
        start, end = text.find("["), text.rfind("]")
        if start < 0 or end <= start:
            sys.exit(f"ERROR: no JSON results found in {path}")
        data = json.loads(text[start:end + 1])
    if isinstance(data, dict):
        data = data.get("results", [])
    return data


def load_job(path: str | None) -> dict:
    if not path:
        return {}
    return json.loads(_read(path))


def load_log_messages(path: str | None) -> list:
    """Return the job log as a list of (level, message) in log order."""
    if not path:
        return []
    text = _read(path)
    try:
        wrapped = json.loads(text)
        if isinstance(wrapped, dict) and isinstance(wrapped.get("result"), str):
            text = wrapped["result"]
    except json.JSONDecodeError:
        pass
    out = []
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("- {"):
            continue
        try:
            rec = json.loads(line[2:])
        except json.JSONDecodeError:
            continue  # "results" records carry YAML tags; they are not needed
        msg = rec.get("msg")
        if isinstance(msg, str):
            out.append((rec.get("lvl", ""), msg))
    return out


# ---------------------------------------------------------------------------
# Grouping
# ---------------------------------------------------------------------------

def definition_of(rec: dict) -> str:
    m = re.search(r"^definition:\s*(\S+)", rec.get("metadata") or "", re.M)
    return m.group(1) if m else ""


def group_runs(results: list) -> dict:
    """{definition: [records]} for every test definition that ran the suite."""
    runs: dict = {}
    for rec in results:
        d = definition_of(rec)
        if d == "lava" or not d:
            continue
        runs.setdefault(d, []).append(rec)
    # A definition belongs to the suite if it emitted the suite's verdict or
    # its snapshot-* cases.
    return {
        d: recs for d, recs in runs.items()
        if any(r.get("name") == SUITE or str(r.get("name", "")).startswith("snapshot-")
               for r in recs)
    }


def run_index(definition: str) -> int:
    m = re.match(r"(\d+)_", definition)
    return int(m.group(1)) if m else 0


def split_log_by_run(messages: list) -> dict:
    """{definition: [target messages]} using the LAVA STARTRUN/ENDRUN signals."""
    out: dict = {}
    current = None
    for lvl, msg in messages:
        m = re.search(r"<LAVA_SIGNAL_STARTRUN (\S+) ", msg)
        if m:
            current = m.group(1)
            out.setdefault(current, [])
            continue
        if re.search(r"<LAVA_SIGNAL_ENDRUN ", msg):
            current = None
            continue
        if current and lvl == "target":
            out[current].append(msg)
    return out


# ---------------------------------------------------------------------------
# Log scraping (device identity and the suite's summary block)
# ---------------------------------------------------------------------------

KV_RE = re.compile(r"^([A-Za-z_][\w .()/-]*?)\s+:\s?(.*)$")


def scrape_log(lines: list) -> dict:
    info: dict = {"device": {}, "summary": {}, "top_names": []}
    in_top = False
    for msg in lines:
        if msg.startswith("# top processes"):
            in_top = True
            continue
        if in_top:
            m = re.match(r"^(\d+)\s+(.+)$", msg)
            if m:
                info["top_names"].append(m.group(2).strip())
                continue
            in_top = False
        m = re.search(r"SoC\.machine:\s*(\S+)", msg)
        if m:
            info["device"].setdefault("soc_name", m.group(1))
            continue
        m = KV_RE.match(msg)
        if not m:
            continue
        key, val = m.group(1).strip(), m.group(2).strip()
        if key in ("serial", "model", "kernel", "soc_id", "soc_family",
                   "soc_revision", "os", "android", "nproc"):
            info["device"].setdefault(key, val)
        elif key in ("label", "snapshot_id", "timestamp", "schema_version"):
            info["summary"].setdefault(key, val)
    return info


# ---------------------------------------------------------------------------
# Snapshot assembly
# ---------------------------------------------------------------------------

def _num(rec: dict):
    if rec.get("result") != "pass" or rec.get("measurement") in (None, ""):
        return None
    v = float(rec["measurement"])
    return int(v) if v.is_integer() else v


def build_snapshot(definition: str, recs: list, log: dict, job: dict) -> dict:
    by_name = {r["name"]: r for r in recs}
    vals = {n: _num(r) for n, r in by_name.items()}
    has = {n for n, v in vals.items() if v is not None}
    src_tag = f"lava:{job.get('id', '')}/{definition}"
    errors: list = []
    sources: dict = {}

    def unavailable(key: str, why: str, holder: dict | None = None):
        (holder if holder is not None else sources)[key] = {"available": False}
        errors.append({"source": key, "error": why})

    # meminfo -------------------------------------------------------------
    meminfo = {}
    for n in has:
        if n.startswith("snapshot-meminfo-"):
            frag = n[len("snapshot-meminfo-"):]
            meminfo[MEMINFO_BY_ID.get(frag, frag)] = vals[n]
    if meminfo:
        sources["meminfo"] = {"available": True, "path": src_tag, "parsed": meminfo}
    else:
        unavailable("meminfo", "no snapshot-meminfo-* measurements in the LAVA results")

    # slabinfo: only the total survives the trip, as a single entry --------
    if "snapshot-slab-total" in has:
        sources["slabinfo"] = {
            "available": True, "path": src_tag,
            "parsed": [{"name": "(all caches)", "total_kb": vals["snapshot-slab-total"]}],
            "note": "per-cache detail is not published to LAVA; this is the slabinfo total",
        }
    else:
        unavailable("slabinfo", "snapshot-slab-total not in the LAVA results")

    # vmstat --------------------------------------------------------------
    vmstat = {n[len("snapshot-vmstat-"):]: vals[n] for n in has
              if n.startswith("snapshot-vmstat-")}
    if vmstat:
        sources["vmstat"] = {"available": True, "path": src_tag, "parsed": vmstat}
    else:
        unavailable("vmstat", "no snapshot-vmstat-* measurements in the LAVA results")

    # memblock -> also the System RAM total compute_summary_table() needs ---
    if "snapshot-memblock-memory-total" in has:
        ram_kb = vals["snapshot-memblock-memory-total"]
        sources["memblock"] = {"available": True, "path": src_tag,
                               "parsed": {"total_kb": ram_kb, "regions": []}}
        # Not a real /proc/iomem read: one range whose size is the memblock
        # memory total, which is what the summary table sums iomem ranges for.
        sources["iomem"] = {
            "available": True, "path": "",
            "parsed": {"system_ram_ranges": [
                {"start": "0x0", "end": hex(ram_kb * 1024 - 1)}]},
            "note": "synthesised from snapshot-memblock-memory-total",
        }
    else:
        unavailable("memblock", "snapshot-memblock-memory-total not in the LAVA results")
        unavailable("iomem", "System RAM unknown: no memblock total in the LAVA results")
    if "snapshot-memblock-reserved-total" in has:
        sources["memblock_reserved"] = {
            "available": True, "path": src_tag,
            "parsed": {"total_kb": vals["snapshot-memblock-reserved-total"], "regions": []}}

    unavailable("reserved_memory",
                "DT reserved-memory node sizes are not published to LAVA "
                f"(region count: {vals.get('snapshot-dt-reserved-region-count', 'n/a')})")
    sources["reserved_memory"]["nodes"] = []

    # zram ----------------------------------------------------------------
    if "snapshot-zram0-orig-data" in has:
        orig = vals["snapshot-zram0-orig-data"]
        used = vals.get("snapshot-zram0-mem-used-total") or 0
        sources["zramstat"] = {"available": True, "path": src_tag, "parsed": {
            "orig_data_kb": orig,
            "compr_data_kb": vals.get("snapshot-zram0-compressed-data") or 0,
            "mem_used_kb": used,
            "mem_limit_kb": 0,
            "savings_kb": max(0, orig - used),
        }}
    else:
        unavailable("zramstat", "no snapshot-zram0-* measurements in the LAVA results")

    # debugfs: dma-buf, CMA, KGSL ------------------------------------------
    debugfs: dict = {}
    if "snapshot-dmabuf-total" in has:
        debugfs["dmabuf"] = {"available": True, "path": src_tag, "parsed": {
            "total_kb": vals["snapshot-dmabuf-total"],
            "buffer_count": vals.get("snapshot-dmabuf-object-count") or 0,
            "by_allocator": {}, "by_exporter_detail": {},
        }}
    else:
        unavailable("dmabuf", "snapshot-dmabuf-total not in the LAVA results "
                    "(debugfs not mounted?)", debugfs)

    cma = []
    for n in sorted(has):
        m = re.match(r"snapshot-cma-(.+)-used$", n)
        if m:
            cma.append({"region": m.group(1), "used_kb": vals[n] * PAGE_KB})
    if cma:
        debugfs["cma"] = {"available": True, "path": src_tag, "parsed": cma}
    else:
        unavailable("cma", "no per-region CMA counters in the LAVA results "
                    "(CONFIG_CMA_DEBUGFS?)", debugfs)

    kgsl_kb = next((vals[n] for n in ("snapshot-kgsl-page_alloc", "snapshot-kgsl-page-alloc")
                    if n in has), None)
    if kgsl_kb is not None:
        debugfs["kgsl"] = {"available": True, "path": src_tag,
                           "parsed": {"total_kb": kgsl_kb, "by_process": []}}
    else:
        unavailable("kgsl", "no KGSL page_alloc counter in the LAVA results", debugfs)
    sources["debugfs"] = debugfs

    # process_stats (PSS only) ----------------------------------------------
    real_name = {sanitize_id(n): n for n in log.get("top_names", [])}
    procs = []
    for n in has:
        if n.startswith("snapshot-pss-") and n != "snapshot-pss-total":
            frag = n[len("snapshot-pss-"):]
            procs.append({"pid": 0, "name": real_name.get(frag, frag),
                          "vss_kb": 0, "rss_kb": 0,
                          "pss_kb": vals[n], "uss_kb": 0})
    procs.sort(key=lambda p: p["pss_kb"], reverse=True)
    if procs:
        sources["process_stats"] = {
            "available": True, "path": src_tag, "parsed": procs,
            "note": "PSS summed per process name from smaps_rollup; VSS/RSS not published",
        }
    else:
        unavailable("process_stats", "no snapshot-pss-<name> measurements in the LAVA results")

    unavailable("smaps", "per-mapping smaps detail stays on the DUT")
    sources["smaps"]["parsed"] = []

    # identity --------------------------------------------------------------
    summ = log.get("summary", {})
    dev_log = log.get("device", {})
    actual = job.get("actual_device", "")
    device = {
        "serial": dev_log.get("serial", ""),
        "network_address": "",
        "transport_type": "lava",
        "kernel_version": dev_log.get("kernel", ""),
        "model": dev_log.get("model") or job.get("requested_device_type", ""),
        "soc_name": dev_log.get("soc_name", ""),
        "soc_id": dev_log.get("soc_id", ""),
        "soc_family": dev_log.get("soc_family", ""),
        "soc_revision": dev_log.get("soc_revision", ""),
        "os_name": dev_log.get("os", ""),
        "os_version": "",
        "build_id": "",
        "lava_job_id": job.get("id", ""),
        "lava_device": actual,
        "lava_device_type": job.get("requested_device_type", ""),
    }
    if not device["serial"]:
        device["serial"] = actual

    # The DUT clock is often unset at boot, so prefer the time LAVA logged the
    # results; keep the device's own timestamp alongside.
    logged = min((r.get("logged") or "" for r in recs), default="") or job.get("end_time", "")

    return {
        "schema_version": summ.get("schema_version", "1.0.0"),
        "snapshot_id": summ.get("snapshot_id") or str(uuid.uuid4()),
        "timestamp": logged,
        "device_timestamp": summ.get("timestamp", ""),
        "label": summ.get("label") or definition.split("_", 1)[-1],
        "device": device,
        "dump_dir": src_tag,
        "sources": sources,
        "collection_errors": errors,
        "lava": {
            "job_id": job.get("id", ""),
            "definition": definition,
            "suite_result": by_name.get(SUITE, {}).get("result", ""),
            "cases": len(recs),
        },
    }


def convert(results_path: str, job_path: str | None, logs_path: str | None,
            output_dir: str) -> list:
    results = load_results(results_path)
    job = load_job(job_path)
    log_runs = split_log_by_run(load_log_messages(logs_path))
    runs = group_runs(results)
    if not runs:
        sys.exit(f"ERROR: no {SUITE} results found in {results_path}")

    os.makedirs(output_dir, exist_ok=True)
    index, used = [], set()
    for definition in sorted(runs, key=run_index):
        log = scrape_log(log_runs.get(definition, []))
        snap = build_snapshot(definition, runs[definition], log, job)
        name = sanitize_id(snap["label"]) or definition
        if name in used:
            name = sanitize_id(definition)
        used.add(name)
        snap_dir = os.path.join(output_dir, name)
        os.makedirs(snap_dir, exist_ok=True)
        path = os.path.join(snap_dir, "snapshot.json")
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            json.dump(snap, f, indent=2)
        avail = sum(1 for k, v in snap["sources"].items()
                    if isinstance(v, dict) and v.get("available"))
        avail += sum(1 for v in snap["sources"].get("debugfs", {}).values() if v.get("available"))
        print(f"[lava-integration] {definition}: label={snap['label']} "
              f"cases={len(runs[definition])} sources={avail} -> {path}")
        index.append({"definition": definition, "label": snap["label"], "path": path})

    with open(os.path.join(output_dir, "index.json"), "w", encoding="utf-8", newline="\n") as f:
        json.dump(index, f, indent=2)
    return index


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Rebuild MemorySnapshot JSON from a LAVA Memory_Snapshot job.")
    parser.add_argument("--results", required=True,
                        help="get_job_results output (JSON)")
    parser.add_argument("--job", default=None, help="get_job output (JSON)")
    parser.add_argument("--logs", default=None, help="get_job_logs output")
    parser.add_argument("--output-dir", default="lava_snapshots",
                        help="Where to write <label>/snapshot.json (default: lava_snapshots)")
    args = parser.parse_args()
    convert(args.results, args.job, args.logs, args.output_dir)
    return 0


if __name__ == "__main__":
    sys.exit(main())
