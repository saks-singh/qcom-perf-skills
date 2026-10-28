---
name: memory-analysis
description: >
  Use this skill for all memory analysis tasks on Qualcomm Linux devices.
  Supports five modes auto-detected from the parameters provided:
  (1) Snapshot: single memory snapshot from a connected device;
  (2) Workload: measure memory impact of a workload or application —
      2A Preset: use a named preset; 2B Custom: provide a shell command;
      2C User-Launched: user launches the workload manually, skill collects before/after;
  (3) Regression: compare a live device against a pre-collected reference snapshot;
  (4) Comparison: compare two pre-collected snapshots offline (no device needed);
  (5) LAVA: schedule the qcom-linux-testkit Memory_Snapshot suite on a LAVA
      board through the lava MCP server, then report on the finished job.
  Generates a unified HTML report with memory breakdown, process ranking,
  kernel/userspace diffs, and root cause analysis.
license: BSD 3-Clause License
compatibility: >
  Requires Python 3.10+. pip install -r requirements.txt.
  ADB transport: adb in PATH, Qualcomm Linux device with adbd enabled.
  SSH transport: pip install paramiko, any Linux device reachable over network.
  Host OS: Windows or Linux.
metadata:
  author: "Jagadeesh Pagadala"
  version: "0.0.1"
  platform: "Qualcomm Linux"
  category: "Memory Analysis"
  internal-dependencies: "data-collection,snapshot-comparison,kernel-diff,userspace-diff,anomaly-rca,report-generation,lava-integration"
  entry-point: "skills/memory-analysis/scripts/run.py"
  presets: "skills/memory-analysis/usecases/presets.json"
---

Unified memory analysis skill for Qualcomm Linux devices.
One skill, five modes — auto-detected from the parameters you provide.

---

## Standard Prompts (for AI agents)

Use these prompts when talking to an AI agent (Cline, Cursor, etc.):

### Snapshot — Current memory state
```
"Give me a memory report for the connected device"
"What is the memory usage on this board?"
"Show me the memory breakdown for device 0426df75"
"Memory report for device at 192.168.1.100, user=root"
```

### Workload (Preset/Custom) — Measure memory impact
```
"How much memory does the camera use?"
"Measure memory impact of camera_h264_encoding"
"Run the camera and tell me the memory impact"
"Measure memory impact of: gst-launch-1.0 qtiqmmfsrc ..."
```

### Workload (User-Launched) — Measure user-launched use-case
```
"I want to measure memory of a use-case I'll launch manually"
"Collect baseline, then I'll launch my app, then collect active"
"Help me measure memory impact of my custom workload"
"I have a GStreamer command I want to run — measure its memory usage"
"Baseline first, then I'll start the camera, then active snapshot"
"Measure memory of my use-case — reboot first for a clean baseline"
```

### Regression — Compare device against reference
```
"Is this device using more memory than the reference?"
"Compare device 0426df75 against the golden baseline in results/golden/"
"Regression test: collect from device and compare with results/build_v1/"
"Has memory changed since the last build?"
```

### Comparison — Compare two pre-collected snapshots
```
"Compare results/build_v2/ against results/build_v1/"
"Offline comparison: current=results/camera_active/ reference=results/baseline/"
"Compare two snapshots: A=data/device_A/ B=data/device_B/"
"I have two snapshot folders — compare them"
```

### LAVA — Run on a lab board (lava MCP server)
```
"Give me a memory report for a lemans-evk in LAVA"
"Flash lemans-evk with this build in LAVA and report its memory"
"Measure memory impact of camera_h264_encoding on a LAVA lemans-evk"
"Make the memory report for LAVA job 516300"
```

---

## Mode Selection Guide

```
What do you want to do?
│
├─ "I want a memory report for my device"
│  └─ Snapshot mode: python run.py [--serial <serial>]
│
├─ "I want to measure memory impact of a workload"
│  ├─ Variant A (Preset):  python run.py --workload <preset> [--serial <serial>]
│  ├─ Variant B (Custom):  python run.py --command "<cmd>" --workload-name "<label>" [--serial <serial>]
│  ├─ Variant C1 (User-Launched, Interactive — single command):
│  │    python run.py --user-launched --interactive [--reboot] --serial <serial>
│  └─ Variant C2 (User-Launched, Agent-Driven — multi-step):
│       python run.py --user-launched --label baseline [--reboot] --serial <serial> --output-dir results/my_session
│       # ... user launches use-case on device ...
│       python run.py --user-launched --label active --serial <serial> --output-dir results/my_session
│       python run.py --compare-snapshots results/my_session/baseline results/my_session/active
│
├─ "I want to check if my device uses more memory than a reference"
│  └─ Regression mode: python run.py --reference <path> [--serial <serial>]
│
├─ "I want to compare two pre-collected snapshots"
│  └─ Comparison mode: python run.py --current <path> --reference <path>
│
└─ "The board is in a LAVA lab" / "Report on LAVA job <id>"
   └─ LAVA mode: lava_job.py render → lava MCP submit/fetch → python run.py --lava-results <dir>
```

---

## Mode 1: Snapshot

**Use when:** You want the current memory state of a connected device.

**Command:**
```bash
python skills/memory-analysis/scripts/run.py [--serial <serial>]
```

**Examples:**
```bash
# Auto-detect connected device
python skills/memory-analysis/scripts/run.py

# Specific ADB device
python skills/memory-analysis/scripts/run.py --serial 0426df75

# SSH device
python skills/memory-analysis/scripts/run.py --host 192.168.1.100 --user root
```

**Output:** `results/snapshot_<timestamp>/reports/snapshot_report.html`

---

## Mode 2: Workload Impact

**Use when:** You want to measure how much memory a specific workload consumes.

**Command (preset):**
```bash
python skills/memory-analysis/scripts/run.py --workload <preset> [--serial <serial>]
```

**Command (custom):**
```bash
python skills/memory-analysis/scripts/run.py \
  --command "<shell_command>" \
  --workload-name "<label>" \
  [--serial <serial>] [--wait <seconds>]
```

**Examples:**
```bash
# Using a preset
python skills/memory-analysis/scripts/run.py --workload camera_h264_encoding

# Custom command
python skills/memory-analysis/scripts/run.py \
  --command "gst-launch-1.0 -e qtiqmmfsrc name=camsrc camera=0 ! fakesink" \
  --workload-name "camera_preview" \
  --serial 0426df75 \
  --wait 15

# Skip reboot (use current device state as baseline)
python skills/memory-analysis/scripts/run.py \
  --workload camera_h264_encoding \
  --skip-reboot
```

**Available Presets:**
See `usecases/presets.json` for the full list. Current presets:
- `camera_preview_vhdr` — Camera preview with vHDR at 2688x1512 @ 30fps
- `camera_h264_encoding` — Camera H.264 encoding to MP4 at 1280x720 @ 30fps
- `clip_snpe` — CLIP SNPE model inference on DSP
- `convnext_snpe` — ConvNeXt SNPE model inference on DSP

**Adding a New Preset:**
Edit `usecases/presets.json`:
```json
"my_workload": {
  "name": "My Workload",
  "description": "What this workload does",
  "setup": ["optional setup commands", "sleep 3"],
  "command": "the command to run on the device",
  "wait_sec": 15,
  "teardown": ["optional cleanup, e.g. pkill myapp"]
}
```

**Output:** `results/<preset>_<timestamp>/reports/workload_impact_report.html`

---

## Mode 2C: Workload Impact (User-Launched)

**Use when:** The user launches a use-case manually on the device and you want to measure its memory impact.
The skill collects a baseline snapshot before the workload starts, and an active snapshot while it is running.

> **Note:** Users interact through the AI agent only — not directly with scripts.
> The agent orchestrates the workflow based on natural language prompts.

---

### Variant C1: Interactive Mode (Recommended — Single Command)

The agent runs a single command that guides the user through the entire workflow.

```bash
# Without reboot (use current device state as baseline)
python skills/memory-analysis/scripts/run.py \
  --user-launched --interactive \
  --serial <serial>

# With reboot (clean baseline state)
python skills/memory-analysis/scripts/run.py \
  --user-launched --interactive --reboot \
  --serial <serial>
```

**What happens:**
```
[memory-analysis] Mode: Workload Impact (User-Launched, Interactive)

── Step 1/4: Collecting baseline snapshot ──────────────
[memory-analysis] Collecting baseline snapshot...
[memory-analysis] Baseline snapshot saved.

── Step 2/4: Launch your use-case ──────────────────────
[memory-analysis] Please launch your use-case on the device now.
[memory-analysis] Wait for it to stabilize before pressing ENTER.
[memory-analysis] >>> Press ENTER when your use-case is running and stable:

── Step 3/4: Collecting active snapshot ────────────────
[memory-analysis] Collecting active snapshot...
[memory-analysis] Active snapshot saved.

── Step 4/4: Comparing snapshots ────────────────────────
[memory-analysis] Running snapshot comparison...
[memory-analysis] Running kernel memory diff...
[memory-analysis] Running userspace memory diff...
[memory-analysis] Generating workload impact report...

[memory-analysis] Done.
[memory-analysis] Report: results/user_launched_<timestamp>/reports/workload_impact_report.html
```

**Key points:**
- Single command — no multi-step workflow
- Agent pauses at Step 2 and waits for user to launch use-case
- Optional `--reboot` for clean baseline state
- Auto-manages session directory (no `--output-dir` needed)
- Generates the same `workload_impact_report.html` as Mode 2A/2B

**Output:** `results/user_launched_<timestamp>/reports/workload_impact_report.html`

---

### Variant C2: Agent-Driven Multi-Step Mode

For cases where the agent needs to orchestrate each step separately.
The skill prints exact next-step commands after each collection.

```bash
# Step 1: Collect baseline (optionally with reboot)
python skills/memory-analysis/scripts/run.py \
  --user-launched --label baseline \
  [--reboot] --serial <serial> \
  --output-dir results/my_session

# Step 2: User launches use-case on device
# (e.g., gst-launch-1.0 qtiqmmfsrc video_0::type=preview vhdr=1 ! fakesink)

# Step 3: Collect active snapshot (use-case running)
python skills/memory-analysis/scripts/run.py \
  --user-launched --label active \
  --serial <serial> \
  --output-dir results/my_session

# Step 4: Compare snapshots and generate report
python skills/memory-analysis/scripts/run.py \
  --compare-snapshots results/my_session/baseline results/my_session/active
```

**Key points:**
- Use the **same `--output-dir`** for both baseline and active collection steps
- The skill prints exact next-step commands after each collection step
- Optional `--reboot` on the baseline step for clean state
- Generates the same `workload_impact_report.html` as Mode 2A/2B

**Output:** `results/user_launched_<timestamp>/reports/workload_impact_report.html`

---

## Mode 3: Regression Test

**Use when:** You want to check if a connected device uses more memory than a reference.

**Command:**
```bash
python skills/memory-analysis/scripts/run.py \
  --reference <path> \
  [--serial <serial>]
```

**Examples:**
```bash
# Compare against golden baseline
python skills/memory-analysis/scripts/run.py \
  --reference results/golden_baseline/ \
  --serial 0426df75

# SSH device
python skills/memory-analysis/scripts/run.py \
  --reference results/build_v1/ \
  --host 192.168.1.100 --user root
```

**Output:** `results/regression_<timestamp>/reports/regression_report.html`

---

## Mode 4: Snapshot Comparison (Offline)

**Use when:** You want to compare two pre-collected snapshots. No device needed.

**Command:**
```bash
python skills/memory-analysis/scripts/run.py \
  --current <path> \
  --reference <path>
```

**Examples:**
```bash
# Compare two builds
python skills/memory-analysis/scripts/run.py \
  --current results/build_v2/ \
  --reference results/build_v1/

# Compare camera active vs idle
python skills/memory-analysis/scripts/run.py \
  --current results/camera_active/ \
  --reference results/baseline/ \
  --output-dir results/camera_comparison/
```

**Output:** `results/comparison_<timestamp>/reports/comparison_report.html`

---

## Mode 5: LAVA (lava MCP server)

**Use when:** The board is in a LAVA lab rather than on your desk, or you are
given a LAVA job id. Requires the `lava` MCP server (tools `mcp__lava__*`).

Collection runs on the board as the qcom-linux-testkit
`Runner/suites/Performance/Memory_Snapshot` suite, which is the same entry
lava-test-plans has in `testcases/performance.yaml`. LAVA keeps the suite's
`snapshot-*` measurements and its log. `run.py --lava-results` rebuilds
snapshot.json from them (`internal/lava-integration`) and then runs the Mode 1
or Mode 2C pipeline unchanged.

**Agent workflow:** one skill call. Do every step yourself without stopping:

1. **Render the job.** Fill the parameters in from the request:
   ```bash
   # Snapshot
   python skills/memory-analysis/scripts/lava_job.py render \
     --device-type lemans-evk [--image-url <qcomflash url>] -o results/lava_<ts>/job.yaml

   # Workload impact (baseline → start workload → active → stop)
   python skills/memory-analysis/scripts/lava_job.py render \
     --device-type lemans-evk --workload camera_h264_encoding -o results/lava_<ts>/job.yaml
   python skills/memory-analysis/scripts/lava_job.py render \
     --device-type lemans-evk --command "<cmd>" --workload-name "<label>" [--wait 15] \
     -o results/lava_<ts>/job.yaml
   ```
   The deploy and boot actions come from `lava/boot-templates/<device-type>.yaml`.
   If no template exists for the device type, call
   `mcp__lava__find_boot_template(artifact_url, device_type)`, save its deploy
   and boot actions as a new template, and pass `--boot-template`.
2. **Validate.** Call `mcp__lava__validate_job(definition=<job.yaml text>)`. If it is invalid, fix the job and validate again.
3. **Submit.** Call `mcp__lava__submit_job(definition=...)` and tell the user the job id.
4. **Wait.** Poll `mcp__lava__get_job(job_id)` until `state` is `Finished`. Expect flashing to take 20 to 40 minutes. Poll every few minutes; don't spin. If `health` is not `Complete`, read `get_job_logs` and report why the job failed. Still continue to step 5 if the job has `snapshot-*` results.
5. **Fetch.** Save the outputs to `results/lava_<id>/lava/`:
   - `mcp__lava__get_job_results(job_id, limit=500)` → `results.json`
   - `mcp__lava__get_job(job_id)` → `job.json`
   - `mcp__lava__get_job_logs(job_id)` → `logs.yaml`

   Write each tool result verbatim, or the JSON payload inside it. If a result spilled to a file, copy that file.

   Without the MCP server, use `python skills/memory-analysis/scripts/lava_job.py fetch --job-id <id> --output-dir results/lava_<id>/lava`. That is the REST API; set `LAVA_TOKEN` for private jobs.
6. **Report.**
   ```bash
   python skills/memory-analysis/scripts/run.py \
     --lava-results results/lava_<id>/lava --output-dir results/lava_<id>
   ```
   If the job has one Memory_Snapshot run, this writes `snapshot_report.html`. If it has two or more (first = reference, last = current), it writes `workload_impact_report.html`.

For an existing job id, start at step 5.

**What LAVA cannot carry:** LAVA does not bring files back from the board. So
the following are marked unavailable in the report:
- per-cache slab detail (only the slab total is kept)
- smaps
- DT reserved-memory sizes (NHLOS is derived from rounding RAM up to the next 1 GB)
- VSS/RSS (only PSS is kept)

**Output:** `results/lava_<id>/reports/snapshot_report.html` or `workload_impact_report.html`

---

## Parameters Reference

| Parameter | Mode(s) | Required | Default | Description |
|---|---|---|---|---|
| `--workload` | 2A | Yes* | -- | Preset name from `usecases/presets.json` |
| `--command` | 2B | Yes* | -- | Custom shell command to run on device |
| `--workload-name` | 2B | Yes** | -- | Label when using `--command` |
| `--wait` | 2A,2B | No | preset or 15 | Seconds to wait for workload to stabilize |
| `--skip-reboot` | 2A,2B | No | false | Skip device reboot before baseline collection |
| `--user-launched` | 2C | Yes | -- | Measure memory of a user-launched use-case |
| `--interactive` | 2C | No | false | Enable single-command interactive guided workflow (use with --user-launched) |
| `--reboot` | 2C | No | false | Reboot device before baseline collection (use with --user-launched) |
| `--compare-snapshots` | 2C | Yes*** | -- | Compare two snapshots: baseline and active dirs |
| `--reference` | 3,4 | Yes | -- | Reference snapshot directory |
| `--current` | 4 | Yes | -- | Current snapshot directory (offline comparison) |
| `--serial` | 1,2,3 | No | auto-detect | ADB device serial number |
| `--host` | 1,2,3 | No | -- | SSH hostname or IP address |
| `--user` | 1,2,3 | No | `root` | SSH username |
| `--output-dir` | all | No | `results/<mode>_<ts>/` | Output directory (use same dir for 2C collect steps) |
| `--label` | 1,3,2C | No | `snapshot` | Label for the collected snapshot (use `baseline` or `active` for 2C) |
| `--title` | 3,4,2C,5 | No | auto | Report title |
| `--lava-results` | 5 | Yes | -- | Dir with `results.json` [+ `job.json`, `logs.yaml`] from a finished LAVA job |

`lava_job.py render` takes `--device-type`, `--boot-template`, `--image-url`,
`--testkit-repo`, `--testkit-ref`, `--label`, `--settle`, `--workload` or
`--command` with `--workload-name`, `--wait`, and `-o`.
`lava_job.py fetch` takes `--job-id`, `--lava-url` and `--output-dir`.

*Either `--workload` or `--command` required for Mode 2A/2B.
**Required when using `--command`.
***Required for Mode 2C comparison step.

---

## Outputs

| File | Mode(s) | Description |
|---|---|---|
| `reports/snapshot_report.html` | 1 | Memory breakdown, process ranking, carveout layout |
| `reports/workload_impact_report.html` | 2A,2B,2C | Baseline vs active comparison, memory delta, anomalies |
| `reports/regression_report.html` | 3 | Device vs reference comparison, regression findings |
| `reports/comparison_report.html` | 4 | Snapshot comparison, kernel/userspace diffs, anomalies |
| `baseline/snapshot.json` | 2A,2B,2C | Idle/pre-workload baseline snapshot |
| `active/snapshot.json` | 2A,2B,2C | Active workload snapshot |
| `snapshot/snapshot.json` | 1,3 | Collected device snapshot |
| `lava_snapshots/<label>/snapshot.json` | 5 | Snapshots rebuilt from the LAVA job |
| `reports/_intermediate/` | all | Intermediate JSON reports (for debugging) |

---

## Workflow Details

### Mode 1 (Snapshot)
```
Device → Collect snapshot → Snapshot analysis → snapshot_report.html
```

### Mode 2A/2B (Workload — Preset/Custom)
```
Device → Reboot → Collect baseline → Setup → Start workload
       → Wait 15s → Collect active → Stop workload → Teardown
       → Compare → Kernel diff → Userspace diff → workload_impact_report.html
```

### Mode 2C Variant C1 (Workload — User-Launched, Interactive)
```
(Optional Reboot) → Collect baseline → Prompt user to launch use-case
                 → User presses ENTER → Collect active
                 → Compare → Kernel diff → Userspace diff → workload_impact_report.html
```

### Mode 2C Variant C2 (Workload — User-Launched, Agent-Driven)
```
(Optional Reboot) → Collect baseline snapshot [agent prints next-step commands]
User launches use-case on device
Collect active snapshot [agent prints compare command]
Compare → Kernel diff → Userspace diff → workload_impact_report.html
```

### Mode 3 (Regression)
```
Device → Collect current → Compare vs reference
       → Kernel diff → Userspace diff → regression_report.html
```

### Mode 4 (Comparison)
```
current/snapshot.json + reference/snapshot.json
       → Compare → Kernel diff → Userspace diff → comparison_report.html
```

### Mode 5 (LAVA)
```
lava_job.py render → validate_job → submit_job → poll get_job
       → get_job_results / get_job / get_job_logs → run.py --lava-results
       → lava_to_snapshot → Mode 1 or Mode 2C pipeline → snapshot_report.html / workload_impact_report.html
```

---

## Error Handling

- **Device not connected:** Inform the user and stop. Run `adb devices` to verify.
- **Preset not found:** List available presets and stop.
- **Snapshot directory missing:** Inform the user and ask for the correct path.
- **Partial collection failure:** Continue with available data; note missing sources in report.
- **Workload stops early:** Collect snapshot anyway and note in report.
- **LAVA job Incomplete / no `snapshot-*` results:** Report the failing action from `get_job_logs`. Do not resubmit unless the user asks.
- See `TROUBLESHOOTING.md` for common ADB and SSH errors.