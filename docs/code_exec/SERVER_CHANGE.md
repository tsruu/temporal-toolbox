# Local code_executor routing (prepared only; no deploy)

Baseline: toolbox `205f466`; implementation branch `code-exec-sandbox`.
Server configuration source: `analysis/deploy_runbook.md`. No SSH was used and no
server files were edited. There is no local copy of either host's
`toolbox_setup/tools.yaml` or `mcp_server_local.json` in this workspace. The local
sibling `projects/verl` supplies the MCP configuration schema in
`verl/tools/utils/tool_registry.py` and
`examples/sglang_multiturn/config/tool_config/mcp_tool_config.yaml`; it is not a
copy of the running `verl-temporal` configuration. Consequently the edit below
is exact by key/tool selection, rather than a fabricated line-number diff.

## Required tools.yaml change on BOTH hosts

File: `~/Trishan/verl-temporal/toolbox_setup/tools.yaml` (optimus absolute path:
`/home2/ashutosh/Trishan/verl-temporal/toolbox_setup/tools.yaml`).

In the MCP entry whose `mcp.tool_selected_list` contains `code_executor`, change:

```diff
 mcp:
-  mcp_servers_config_path: toolbox_setup/mcp_server_temporal.json
+  mcp_servers_config_path: toolbox_setup/mcp_server_local.json
   tool_selected_list:
     - code_executor
```

Preserve the existing path prefix if the actual value is absolute or starts
with `./`. Preserve `class_name`, `config.type`, timeout, rate limit and other
settings. Lookup/translation entries already use the local JSON and require no
routing changes. The separate code-only entry may stay separate; the important
change is its JSON configuration path. If combining it with the lookup entry,
select `code_executor` exactly once and remove the now-empty Azure entry.

The effective JSON URL in `toolbox_setup/mcp_server_local.json` must be:

| Host | Required local SSE URL |
| --- | --- |
| optimus | `http://127.0.0.1:8010/sse` |
| sentinel | `http://127.0.0.1:47810/sse` |

Within the existing `mcpServers` object keep the current server key and change
only its `url` if it differs. For example (the key is illustrative):

```json
{"mcpServers": {"toolbox-local": {"url": "http://127.0.0.1:8010/sse"}}}
```

Use `47810` in that example on sentinel. The runbook says those URLs already
have the correct ports, so normally **no JSON edit is needed**. Keep
`mcp_server_temporal.json` and `tools_remote.yaml` available for explicitly
remote consumers; do not overwrite the Azure URL to achieve local routing.

This routing change is for future training jobs after restarting their MCP
clients. No datasets/parquets or tables need changing. Do not change the
live toolbox underneath an existing training run.

## Container execution identity and host prerequisites

The Dockerfile creates the `code-exec` user/group at uid/gid `20001`, with no
home directory or login shell. The toolbox server keeps its existing identity;
its child launcher clears supplementary groups and drops to that account
before executing submitted code. No capabilities are added to the container.

On **optimus Docker**, preserve the current server command (root inside the
container). Its ordinary setuid/setgid privileges permit a different child uid;
there is no reason to use privileged mode. A container launched with `--user`
non-root cannot switch uid and will fail closed unless the rootless opt-in
below is deliberately used. Keep translator credentials/proxies on the server
only; the child receives a fresh allowlisted environment.

On **sentinel udocker**, simulated container root does not confer host setuid
privileges. A different host uid is not achievable without privileged help.
The explicit bounded fallback is the server environment setting:

```text
CODE_EXEC_ALLOW_SAME_UID=1
```

Add `--env=CODE_EXEC_ALLOW_SAME_UID=1` to the existing `udocker run` options
when a future deployment is approved. It acknowledges that the child has the
same host uid as the toolbox. It does NOT disable the required Linux kernel
filesystem or syscall policies. If udocker reports a fake root uid and cannot
actually drop to uid 20001, launch the container process as its ordinary host
user (consult its installed udocker user-mapping support); do not emulate a
successful uid change. Identity setup failures return `ERROR:`.

Round 2 supports **Landlock ABI 1, 2 and 3+**. The supplied server facts are
optimus Linux 5.19 with Landlock ABI 2 at most, and sentinel Linux 6.8 with
ABI >= 3. No remote runtime validation was performed for this change. The
launcher queries the running kernel, handles filesystem rights available up to
ABI 3, and records both the available ABI and applied policy ABI. Landlock
syscalls 444–446 and unprivileged seccomp on x86_64/aarch64 may be restricted by
the outer runtime, so validate inside the actual container.

`PR_SET_NO_NEW_PRIVS` and the non-root identity remain required. If only one of
Landlock/seccomp installs, that policy stays active and the missing policy and
error are recorded in `metadata.protections` and the toolbox log. Execution
fails closed if neither policy installs. This fallback follows PLAN_code_exec_r2:
seccomp alone does not confine filesystem access; Landlock alone does not block
network/process/exec syscalls. On ABI 1/2 without seccomp, path truncation is not
fully mediated. The self-test reports containment failures in these modes.

## Child restrictions and practical limits

* Five-second hard wall timeout (including launcher startup), CPU hard/soft
  limit five seconds; the parent sends SIGKILL to the entire process group on
  timeout, output overflow and on normal completion. Internal callers can
  shorten the timeout but cannot increase it.
* One GiB address space, eight MiB per written file, 32 processes/threads per
  execution uid via RLIMIT_NPROC, 64 open descriptors, and no core dumps.
  Seccomp denies `fork`/`vfork` and `clone` without
  CLONE_THREAD, but allows threads. `clone3` returns ENOSYS so glibc can fall back
  to the inspectable `clone` syscall. BLAS/OMP/MKL/NumExpr thread defaults are
  pinned to one in the scrubbed child environment. NPROC remains a second guard,
  shared across the uid; an already heavily populated same-uid udocker host may
  still prevent thread creation. NumPy/pandas imports must be checked in the
  installed image. Submitted code runs in the already-started isolated Python
  interpreter, allowing seccomp to deny all later execve/execveat calls.
* Bounded slots **per server process**, configured by a positive integer
  `CODE_EXEC_SLOTS`, otherwise `min(16, max(2, (os.cpu_count() or 1) // 4))`.
  With the supplied CPU counts this means 10 on optimus and 16 on sentinel,
  unless the container reports a different count. Saturated calls wait up to
  ten seconds before returning `ERROR: ... executor busy`; their five-second
  execution timeout starts after admission. Queue wait milliseconds are in the
  response metadata. Multiple uvicorn workers multiply this budget.
* 256 KiB code input; 64 KiB per returned stdout/stderr stream (UTF-8 bytes),
  overflow terminates the execution and is an error. Stdin is `/dev/null`,
  descriptors close on exec, Python runs with `-I`, umask is 077, and each
  invocation gets a deleted temporary working directory.
* Landlock denies file reads outside the work directory, interpreter/system
  libraries and allowlisted runtime files. It denies filesystem mutation
  outside the work directory, including absolute paths and `..` traversal.
  `/app`, `/home`, `/proc`, and outside `/tmp` files are not readable through
  the policy. Python standard/system-installed libraries remain readable.
* Seccomp denies socket creation/connect/bind/listen/accept, Unix sockets,
  process-group/session escape, ptrace/process_vm operations, and signalling
  other processes. Seccomp denies later exec calls and io_uring setup/operations. On older
  Landlock ABIs it also denies path-based truncate, read-only O_TRUNC, and
  openat2 (ENOSYS); ordinary writable opens/ftruncate in temp still work. This does not depend on root
  network namespaces or `unshare`; parent lookup/translation networking stays
  enabled. Proxy variables and AZURE_* credentials are absent from the child.

Rootless udocker is not a VM or a separate kernel/user namespace. Landlock and
seccomp restrict the child but do not supply a complete security boundary
against kernel vulnerabilities or all denial-of-service paths (for example,
a process can create many individually small files until time expires).
RLIMIT_FSIZE is per file, not a total disk quota; no cgroup aggregate memory or
filesystem quota is introduced. Prefer a private size-bounded temp filesystem
in a future Docker run, and avoid mounting sensitive libraries/host directories
into the interpreter allowlist. The child can still read system libraries and
its own code. Non-Linux hosts (including macOS) refuse submitted code before launching any
subprocess; there is no unsandboxed development execution mode.

## Future verification before routing (not executed on servers)

Build this branch's image locally on the approved target runtime; retain
`requirements.txt` and `constraints.txt` unchanged. Verify the dedicated uid,
normal datetime output, `ERROR:` on exceptions, timeout/output/resource limits,
outside-write/read denial, socket/exec denial, and parallel queueing using
`tests_code_exec.py`. Test uncached translation separately to establish that
server credentials/proxy networking still work. Run REST `/tool` and MCP `/sse`
smokes at each host's port, then restart new training jobs with the edited
configuration. Keep the old image and tools.yaml for rollback. No Azure update,
Docker Hub push, SSH, container swap or training restart is authorized by this
implementation task.


## Round-2 operator commands (inside each Linux container)

The image copies `app/`, so the self-test is available without mounting the
unit-test files. It checks normal print, stdlib/script semantics, exception,
timeout, finite fork-bomb probe, memory/output limits, synthetic outside writes
and truncate bypasses, socket/exec denial, scrubbed /proc environment, threads,
NumPy/pandas if installed, and twenty parallel calls through two temporary
self-test slots. A missing optional package prints “not installed”; an installed
package that cannot import fails. It prints a PASS/FAIL table, active protections,
and exits nonzero on failure. Run it as a standalone operator command, separate
from the serving process.

```sh
python -m app.tools.code_selftest
python -m app.tools.code_replay /path/to/replay_cases.jsonl --report /tmp/code_replay_report.json
```

`docs/code_exec/replay_cases.jsonl` is the committed copy of
`analysis/code_exec/replay_cases.jsonl`. Copy/mount it readably into the test
container. The replay compares stdout, stderr and status exactly, excluding the
new metadata, prints one parity row per case and exits nonzero on differences.
Error tracebacks and blocked network calls can differ from recorded Azure
outputs; the report retains both values for review. It makes no live Azure
comparison calls. To regenerate the set locally without executing code:

```sh
python -m app.tools.code_replay ../analysis/code_exec/replay_cases.jsonl --extract ../rollouts/current --limit 200
```

No routing files, remote containers, tables, dependency pins, or training jobs
were changed by round 2. The earlier REPORT.md is historical; REPORT_r2.md
records the new implementation and validation limits.
