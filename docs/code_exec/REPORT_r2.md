# Code executor round-2 implementation report

Implemented locally from toolbox `282d3fd` on `code-exec-sandbox`. Applied and
reviewed stash `code_exec r2 partial (killed 2026-10-09)` as the starting point;
the stash remains intact. `main` remains at
`205f46654569ada83b4b261d0c4ef464df7bfa43`. No push, deploy, SSH, container
changes, Azure calls, training changes, table edits or dependency-pin changes.

## Result

* Calls queue on a bounded semaphore for up to ten seconds. Saturation returns
  an error with `executor busy`, rather than rejecting a third call immediately.
  Slots default to `min(16, max(2, (os.cpu_count() or 1) // 4))`, or positive
  integer `CODE_EXEC_SLOTS`. Supplied CPU counts imply 10 optimus / 16 sentinel
  slots when those counts are visible in the container. The five-second child
  timeout starts after admission. Queue wait milliseconds are response metadata.
* Landlock queries the available ABI, applying ABI-1 filesystem rights, REFER
  on ABI >= 2 and TRUNCATE on ABI >= 3. ABI 2 is accepted. Newer kernels apply
  this ABI-3 filesystem policy; metadata distinguishes available ABI from
  applied policy ABI. The allowlist still restricts reads to temp and runtime
  libraries/files and mutations to temp when Landlock installs.
* Landlock and seccomp are attempted independently. Either successful policy
  permits execution; neither available fails closed. Missing-policy errors and
  active protections are transmitted over a trusted, separate pipe, closed
  before submitted code runs. Metadata is included in direct/MCP output and
  propagated into REST response metadata; the parent logs protections/status.
  Validation, queue and setup errors report no active protections.
* Seccomp permits CLONE_THREAD but denies process-creating clone, fork/vfork,
  sockets/network, subsequent execve/execveat, signals to other processes,
  session/group escape, ptrace/process_vm, pidfd signalling and io_uring.
  clone3 returns ENOSYS for glibc's clone fallback. Architecture checks reject
  alternate ABIs, including x32 on x86_64. Filters cover x86_64 and aarch64.
* Older Landlock ABIs do not mediate all truncation. Seccomp also denies
  path-based truncate, O_RDONLY|O_TRUNC and openat2 (ENOSYS; use openat), while
  ordinary writable opens/ftruncate remain usable in temp. Runtime probes
  explicitly cover these older-ABI bypasses against synthetic writable files.
* The launcher evaluates code in the already-started isolated interpreter, with
  normal script argv/__file__/__main__ semantics, after policy setup. This
  permits blocking all later exec calls without breaking interpreter startup.
  Exceptions retain stderr tracebacks and nonzero status.
* Non-root identity, rootless opt-in, group clearing for root-launched children,
  isolated Python mode, scrubbed environment, stdin closure, process groups,
  wall/CPU/memory/file/NPROC/descriptor/core limits, input/output caps and temp
  cleanup remain. Child BLAS/OMP/MKL/NumExpr thread defaults are set to one to
  keep optional scientific imports within the existing resource budgets.

## Operator entry points

Inside each actual Linux test container:

```sh
python -m app.tools.code_selftest
python -m app.tools.code_replay /path/to/replay_cases.jsonl --report /tmp/code_replay_report.json
```

The self-test is shipped in `app/`, already copied by the Dockerfile. It prints
a 15-row PASS/FAIL table, details, timings and active protections, and exits
nonzero on failures. Its matrix includes normal print, required stdlib modules
and script semantics, exceptions, infinite-loop timeout, finite fork-bomb probe,
memory hog, huge output, outside write/truncate/read-only-truncate attempts,
sockets, /proc environment secret scrubbing, later exec denial, threads,
NumPy/pandas imports when installed, and twenty simultaneous calls queued
through two temporary self-test slots. Optional absent packages are identified
as “not installed”; installed packages must import and compute successfully.
Run the self-test separately from the serving process.

Extracted **200 distinct real code arguments and recorded outputs**, without
executing them, from `rollouts/current/Qwen3-8B/tools_outputs.jsonl`. The first
tool-bearing file contains enough cases to reach the cap. Each case retains
source-relative filename, line and group id. There are **163 recorded successes
and 37 errors**. Selection does not filter out errors, network imports or
malformed code. Some cases import requests/bs4 and two have indentation errors.
Replay compares stdout/stderr/status exactly, excluding the new metadata. The
JSON report retains both actual and recorded outputs and differing field names.

The requested local file is `analysis/code_exec/replay_cases.jsonl`; the identical
committed copy is `toolbox/docs/code_exec/replay_cases.jsonl`. SHA256:
`cab65b27e0121d9b9a97ca17a06b1bfdee104d55013be2a17b350ba20de9d92f`.
To reproduce extraction from toolbox:

```sh
python -m app.tools.code_replay ../analysis/code_exec/replay_cases.jsonl --extract ../rollouts/current --limit 200
```

## Local verification

Final host-safe command, successfully run from toolbox:

```sh
zsh -ic 'export TMPDIR="$PWD/../analysis/code_exec/tmp"; /usr/bin/python3 -m unittest -v tests_code_exec_unit tests_code_exec_tools_unit tests_code_exec > ../analysis/code_exec/unit_tests_r2_final.log 2>&1'
```

**29 host-safe checks passed; 16 Linux runtime checks skipped; 45 total.**
No submitted or recorded code, real child processes, real rlimits or kernel
policies ran in the passing checks. Mocks and synthetic BPF evaluation verify:
slot defaults/overrides and timeout, twenty-call queue/admission/release,
identity and non-Linux refusal, limit ordering, ABI 1/2/3/newer rights masks,
both single-policy fallbacks and total-policy failure, no-new-privs ordering,
seccomp decisions for both architectures (threads versus processes, exec,
network, clone3/openat2 and truncation), output/error/UTF-8 caps, trusted metadata
and descriptor cleanup, dispatcher metadata/status, extraction pairing and
deduplication, parity fields, non-Linux CLI refusal, self-test state restoration
and the committed fixture. AST parsing and `git diff --check` passed. Re-extraction
matched every case/provenance record, and both replay copies matched bytewise.

The initial test command used actual TemporaryDirectory fixtures:

```sh
zsh -ic 'export TMPDIR="$PWD/../analysis/code_exec/tmp"; /usr/bin/python3 -m unittest -v tests_code_exec_unit tests_code_exec_tools_unit tests_code_exec > ../analysis/code_exec/unit_tests_r2.log 2>&1'
```

After 21 passing checks it terminated with Python 3.9 TemporaryDirectory cleanup
recursion (`RecursionError: maximum recursion depth exceeded`) in this managed
host sandbox, consistent with the round-1 cleanup problem. That filesystem
fixture path was stopped; final host-safe tests mock fixture filesystem calls.
No permission escalation or alternative deletion was attempted. A test temp
directory may remain under analysis/code_exec/tmp. An ad-hoc import inventory
also encountered a recorded IndentationError; the revised read-only inventory
counted malformed source rather than expecting every real recorded call to parse.

## Verification limits and practical risks

Actual Linux containment, import compatibility in the pinned image, twenty-call
runtime behavior, and output parity are **pending the operator's container runs
on optimus and sentinel**. macOS refuses execution before launching submitted
code. No Docker/VM/SSH runtime was started for this task, and no actual output
parity is claimed. REST/MCP runtime checks and the broader dependency-heavy
toolbox suites were not run locally; dispatcher integration was checked with
dependency stubs. Historical round-1 runtime failures are documented in REPORT.md.

The plan's single-policy fallback reduces coverage: seccomp alone permits normal
filesystem access under the child uid; Landlock alone does not prevent network,
process creation or later exec, and ABI 1/2 alone cannot guard all truncation.
The self-test exposes these containment failures rather than treating the
fallback as equivalent to both protections. Prefer both policies on each host.

NPROC is a Linux uid-wide guard, including threads; a busy same-uid sentinel host
can still deny threads even with permissive seccomp. Slot budgets are per toolbox
process and multiply with server workers. Wall time excludes queue time. Files
are capped individually, without an aggregate disk/cgroup memory quota. Updated
SERVER_CHANGE.md documents these limits and operator commands; existing routing
instructions remain prepared only, with no deployment performed.
