# lava-integration

Internal component. Rebuilds MemorySnapshot JSON from a finished LAVA job that
ran the qcom-linux-testkit `Runner/suites/Performance/Memory_Snapshot` suite,
so the rest of the pipeline (snapshot-comparison, kernel-diff, userspace-diff,
report-generation) runs on lab boards unchanged. Used by `run.py --lava-results`
(Mode 5); the job itself is built by `skills/memory-analysis/scripts/lava_job.py`.

## How to Run

```bash
python internal/lava-integration/scripts/lava_to_snapshot.py \
    --results results.json \
    --job     job.json \
    --logs    logs.yaml \
    --output-dir lava_snapshots/
```

---

## Inputs

| Flag | Type | Required | Description |
|---|---|---|---|
| `--results` | path | Yes | `get_job_results` output (`{"results": [...]}`, a list, or a spill file). |
| `--job` | path | No | `get_job` output: job id, device type, board. |
| `--logs` | path | No | `get_job_logs` output: device identity, snapshot id, label, process names. |
| `--output-dir` | path | No | Output directory (default: `lava_snapshots`). |

---

## Outputs

| File | Description |
|---|---|
| `<label>/snapshot.json` | One MemorySnapshot per Memory_Snapshot run in the job. |
| `index.json` | `[{definition, label, path}]` in run order. |

---

## Source Mapping

| LAVA test case | Snapshot source |
|---|---|
| `snapshot-meminfo-<field>` | `meminfo.parsed` (field names restored) |
| `snapshot-vmstat-<key>` | `vmstat.parsed` |
| `snapshot-slab-total` | `slabinfo.parsed` (single `(all caches)` entry) |
| `snapshot-memblock-memory-total` | `memblock`, and `iomem.system_ram_ranges` (one range) |
| `snapshot-memblock-reserved-total` | `memblock_reserved` |
| `snapshot-zram0-*` | `zramstat` |
| `snapshot-dmabuf-total`, `-object-count` | `debugfs.dmabuf` |
| `snapshot-cma-<region>-used` (pages) | `debugfs.cma` (kB) |
| `snapshot-kgsl-page_alloc` | `debugfs.kgsl` |
| `snapshot-pss-<name>` | `process_stats` (PSS only) |

Not carried by LAVA, marked `available: false` and listed in
`collection_errors`: per-cache slab, smaps, DT reserved-memory sizes, VSS/RSS.
The snapshot `timestamp` is when LAVA logged the results (the board clock is
often unset); the board's own time is kept as `device_timestamp`.

---

## Dependencies

- Input: a LAVA job that ran Memory_Snapshot (qcom-linux-testkit)
- Output consumed by: snapshot-comparison, kernel-diff, userspace-diff, report-generation
