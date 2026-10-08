# Local code_executor implementation report

2026-10-08. Implemented locally on toolbox branch `code-exec-sandbox` from
`205f466`. No push, deploy, SSH, Azure calls, table edits, dataset edits, server
configuration edits or training restarts were performed. `main` stays at
`205f466`. Runtime validation is incomplete for the reasons below; this branch
is not yet established as runnable on optimus/sentinel.

## Before and after

Previously `app/tools/code.py` ran `[sys.executable, script.py]` through
`subprocess.run(capture_output=True, timeout=5)` in a temporary directory. It
inherited server uid, environment, stdin, and ordinary filesystem/network
permissions, buffered unbounded output, and had no resource/concurrency caps.
Timeout killed the direct process only. C1 in `dispatcher.py` and `main.py`
already turned non-success code results into `ERROR:` responses.

Now the parent starts a fresh process group and a trusted single-threaded
launcher using the same interpreter with `-I`. The launcher applies limits and
kernel policies before replacing itself with submitted Python. This achieves
the requested pre-execution limits without Python `preexec_fn`, which can
deadlock in a multithreaded FastMCP server. The returned stdout/stderr/status
contract, indentation normalization and five-second maximum remain. CPU
termination may surface as signal `ERROR:` slightly before the wall timeout.

Implemented:

* Dedicated non-root Docker child account uid/gid 20001, cleared supplementary
  groups, mode-077 working files, temporary directory cleanup. Server identity
  and translation/lookup networking remain available.
* Five-second hard wall timeout including launcher startup; process-group
  SIGKILL on timeout, output overflow and completion; stdin closed.
* RLIMIT_CPU, AS (1 GiB), FSIZE (8 MiB/file), NPROC (32), NOFILE (64), CORE (0).
* Minimal environment with fresh HOME/TMPDIR; no inherited AZURE_* credentials,
  proxies, PYTHONPATH or arbitrary environment secrets. Python isolated mode.
* Streaming bounded stdout/stderr (64 KiB each in UTF-8), output overflow error,
  input limit 256 KiB, immediate concurrency rejection beyond two active calls
  per toolbox process; released slots on errors.
* Unprivileged Landlock ABI >= 3 restricts reads to temporary work and runtime
  libraries/files, and filesystem mutation to work. Seccomp blocks sockets,
  all fork/clone/thread creation, group/session escape, ptrace, process_vm and
  signalling other processes. No root network namespace/unshare is required.
  Unsupported kernels/architectures/policy setup fail closed.
* Non-Linux hosts fail closed before any submitted-code subprocess is launched.
* REST dispatch now uses Starlette's threadpool so slow execution/translation
  does not synchronously block the event loop or health requests.
* Linux containment and REST/MCP regression suite, host-safe mocked unit suite,
  and a recorded rollout replay script. Dependency pins are unchanged.

Rootless sentinel cannot obtain a separate host uid. Its documented
`CODE_EXEC_ALLOW_SAME_UID=1` opt-in still requires the Linux kernel policies.
Landlock/seccomp compatibility under the installed udocker runtime and both
host kernels remains unverified. No automatic weakening fallback is provided.
Seccomp deliberately rejects threaded/multiprocess code; normal standard
library date/math calculations are the compatibility target. RLIMIT_FSIZE is
per file, not an aggregate disk quota. This is practical hardening, not a VM,
cgroup or complete defense against every kernel vulnerability/DoS path.

## Verified here

Final command (executed successfully in the managed sandbox):

```sh
cd toolbox
zsh -ic 'export TMPDIR="$PWD/../analysis/code_exec/tmp"; /usr/bin/python3 -m unittest -v tests_code_exec_unit tests_code_exec.SandboxTests > ../analysis/code_exec/unit_tests.log 2>&1'
```

Result: **16 host-safe tests passed, 14 Linux runtime tests skipped**, 30 total.
No submitted code or real child resource limits are run by the passing suite.
It verifies input/error validation, concurrency saturation, semaphore release,
identity/rootless/non-Linux failure rules, environment allowlist, limit setup
ordering, x86_64/aarch64 filter generation, Landlock minimum ABI/failure rules,
stdout/stderr/error/signal capture and UTF-8 output caps using mocks. These
checks do not prove kernel policy enforcement.

AST parsing passed for all modified/new Python files. `git diff --check`
passed. Git diff against `205f466` confirms no changes to temporal.py,
language.py, CSV tables, requirements.txt or constraints.txt.

## Blocked runtime verification and exact failures

1. Workspace root is not a Git repo (`git status --short && cat
   handoffs/plans/PLAN_code_exec.md` stopped at the first command); toolbox is
   the actual repository and all branch work was performed there.
2. `ps -o pid,etime,command -p 70382` was denied: `operation not permitted`.
   No retry/workaround was used. Local virtualenv imports also stalled reading
   files and were interrupted. `/usr/bin/python3` works for host-safe checks.
3. A sandboxed early temporary-directory smoke encountered `Operation not
   permitted` deleting its directory; Python 3.9's TemporaryDirectory cleanup
   then recursed. That blocked execution path was stopped; stale empty test
   directories may remain under `analysis/code_exec/tmp`.
4. Automatic approval review rejected this escalated command:

   ```sh
   zsh -ic 'export TMPDIR="$PWD/../analysis/code_exec/tmp"; venv/bin/python -m unittest -v tests_code_exec tests_apply_x tests_batch1 tests_batch1_r2 tests_temporal_alternatives > ../analysis/code_exec/toolbox_tests.log 2>&1'
   ```

   Reason: the then-present macOS development execution path skipped Linux
   confinement and ran submitted code as the developer's own user, risking
   local file access/modification. That command was not retried. The final
   implementation removes that path and fails closed outside Linux. The
   passing mock-only suite is a separate safe validation, not an indirect run
   of the rejected payloads.
5. `docker info --format '{{.ServerVersion}}'`: configured Docker socket
   `/Users/TRISHAN/.docker/run/docker.sock` does not exist. `colima status`
   confirmed Colima was not running.
6. An isolated local VM attempt, `colima start --profile code-exec-test --cpu 2
   --memory 3 --disk 20 --vm-type vz`, downloaded its disk but failed to boot.
   Its host-agent log reports `VZErrorDomain Code=2: Invalid virtual machine
   configuration. Virtualization is not available on this hardware.` No
   workaround or remote host was used.
7. Cleanup `colima delete --profile code-exec-test --force` failed removing
   `/Users/TRISHAN/.colima/_lima/colima-code-exec-test` with `operation not
   permitted`. No alternative deletion was attempted. A stopped/failed test
   profile and downloaded Colima disk/cache may remain; no VM is running.

Consequently the complete existing toolbox suite, actual Linux CPU/memory/
fork/output/filesystem/network/concurrency tests, and live REST/MCP execution
remain **not run to completion**. The plan's deployment-free implementation is
committed for review, with these verification gaps explicit.

## Recorded Azure behavior comparison

Collected 12 successful real calls from
`rollouts/current/Qwen3-8B/tools_outputs.jsonl` into
`analysis/code_exec/recorded_samples.json`. For example, adding 16 days to
25 May 2023 records stdout `Saturday, 10 June 2023\n`, empty stderr and status
success. `scripts/compare_code_exec_rollouts.py` selects eight distinct
standard-library calculation calls and compares full dictionaries exactly.
No Azure endpoint was called. **The actual local replay is pending**, because
submitted code requires Linux; no output parity claim is made.

To finish verification on an available Linux test runtime with this image's
code-exec account and dependencies (do not route training traffic first):

```sh
cd toolbox
mkdir -p ../analysis/code_exec/tmp
zsh -ic 'export TMPDIR="$PWD/../analysis/code_exec/tmp"; python -m unittest -v tests_code_exec_unit tests_code_exec tests_apply_x tests_batch1 tests_batch1_r2 tests_temporal_alternatives'
zsh -ic 'export TMPDIR="$PWD/../analysis/code_exec/tmp"; python scripts/compare_code_exec_rollouts.py --rollouts ../rollouts/current --limit 8 --output ../analysis/code_exec/rollout_comparison.json'
```

The mock suite passes on Python 3.9 here; the image still uses Python 3.10 and
needs its own runtime checks. Full Linux tests also check thread denial,
synthetic outside-file reads/writes and process-group/session denial.

## Deliverables

`analysis/code_exec/SERVER_CHANGE.md` gives the concrete tools.yaml MCP path
replacement and the optimus 8010/sentinel 47810 SSE URLs, with no invented
server snapshot. Matching tracked copies of SERVER_CHANGE and this report live
in `toolbox/docs/code_exec/` so the branch commit includes them. A local test
context was prepared under `analysis/code_exec/container-context/` (app, pinned
dependencies, tests, sample rollout only; no secrets/virtualenv). It was not
built or run. Local evidence remains under analysis/code_exec; no reports or
changes were pushed.
