"""Trusted isolated interpreter: apply limits/policies, then evaluate the script.

Keeping the already-started interpreter lets seccomp deny *all* later execs.
No submitted code runs before identity, limits, mandatory seccomp and audit policy.
"""
import ctypes
import errno
import json
import os
import platform
import resource
import sys
import traceback


def _limit(kind, value):
    _, hard = resource.getrlimit(kind)
    value = value if hard == resource.RLIM_INFINITY else min(value, hard)
    resource.setrlimit(kind, (value, value))


def _check(result, name):
    if result < 0:
        error = ctypes.get_errno()
        raise OSError(error, f'{name}: {os.strerror(error)}')
    return result


class SandboxUnavailable(RuntimeError):
    def __init__(self, protections):
        self.protections = protections
        super().__init__('Code execution refused: mandatory seccomp network ban unavailable: '
                         + protections.get('seccomp_error', 'socket filter not installed'))


def _landlock(libc, tmpdir):
    # ABI 1: reads/writes/create/remove; ABI 2: REFER; ABI 3: TRUNCATE.
    # Newer kernels support this ABI-3 filesystem policy as well.
    abi = _check(libc.syscall(444, 0, 0, 1), 'Landlock ABI query')
    if abi < 1:
        raise RuntimeError('Landlock unavailable')
    read_access = (1 << 2) | (1 << 3)
    handled = sum(1 << bit for bit in range(1, 13))
    if abi >= 2:
        handled |= 1 << 13
    if abi >= 3:
        handled |= 1 << 14

    class Ruleset(ctypes.Structure):
        _fields_ = [('handled_access_fs', ctypes.c_uint64)]

    class PathBeneath(ctypes.Structure):
        _pack_ = 1
        _fields_ = [('allowed_access', ctypes.c_uint64), ('parent_fd', ctypes.c_int32)]

    ruleset = Ruleset(handled)
    ruleset_fd = _check(libc.syscall(444, ctypes.byref(ruleset), ctypes.sizeof(ruleset), 0),
                        'Landlock ruleset')
    try:
        paths = [(tmpdir, handled)]
        paths += [(path, read_access) for path in
                  (os.path.join(sys.base_prefix, 'lib'), '/usr/lib', '/lib', '/lib64')]
        paths += [(path, 1 << 2) for path in
                  (sys.executable, '/etc/ld.so.cache', '/etc/localtime', '/dev/null', '/dev/urandom')]
        seen = set()
        for path, access in paths:
            path = os.path.realpath(path)
            if path in seen or not os.path.exists(path):
                continue
            seen.add(path)
            path_fd = os.open(path, os.O_PATH | os.O_CLOEXEC)
            try:
                rule = PathBeneath(access, path_fd)
                _check(libc.syscall(445, ruleset_fd, 1, ctypes.byref(rule), 0),
                       'Landlock path rule')
            finally:
                os.close(path_fd)
        _check(libc.syscall(446, ruleset_fd, 0), 'Landlock restrict_self')
    finally:
        os.close(ruleset_fd)
    return abi


def _seccomp_instructions(machine):
    if machine in ('x86_64', 'amd64'):
        audit_arch, clone = 0xC000003E, 56
        open_calls = [(2, 24), (257, 32)]
        # sockets/network, fork/vfork, execve/execveat, signals/ptrace,
        # session escape, process_vm, pidfds, io_uring (can bypass syscall checks).
        denied = [41, 42, 43, 44, 45, 46, 47, 49, 50, 51, 52, 53, 54, 55,
                  57, 58, 59, 62, 76, 101, 109, 112, 129, 200, 234, 288, 297,
                  299, 307, 310, 311, 322, 424, 425, 426, 427, 438]
    elif machine in ('aarch64', 'arm64'):
        audit_arch, clone = 0xC00000B7, 220
        open_calls = [(56, 32)]
        denied = [45, 117, 129, 130, 131, 138, 154, 157, 198, 199, 200, 201,
                  202, 203, 204, 205, 206, 207, 208, 209, 210, 211, 212,
                  221, 240, 242, 243, 269, 270, 271, 281, 424, 425, 426, 427, 438]
    else:
        raise RuntimeError(f'Unsupported seccomp architecture: {machine}')
    deny = 0x00050000 | errno.EPERM
    allow = 0x7FFF0000
    instructions = [(0x20, 0, 0, 4), (0x15, 1, 0, audit_arch),
                    (0x06, 0, 0, 0x80000000), (0x20, 0, 0, 0)]
    if machine in ('x86_64', 'amd64'):
        instructions += [(0x45, 0, 1, 0x40000000), (0x06, 0, 0, 0x80000000)]
    for number in denied:
        instructions += [(0x15, 0, 1, number), (0x06, 0, 0, deny)]
    # Path-based truncate is not mediated by Landlock ABI 1/2. Deny it on
    # every ABI; ordinary open-for-write and ftruncate in the workdir still work.
    # openat2's pointed-to flags are inaccessible to classic BPF; callers can
    # fall back to openat. Deny read-only O_TRUNC, another old-ABI write bypass.
    instructions += [(0x15, 0, 1, 437), (0x06, 0, 0, 0x00050000 | errno.ENOSYS)]
    for number, flags_offset in open_calls:
        instructions += [(0x15, 0, 5, number), (0x20, 0, 0, flags_offset),
                         (0x45, 0, 2, os.O_TRUNC), (0x45, 1, 0, os.O_WRONLY | os.O_RDWR),
                         (0x06, 0, 0, deny), (0x06, 0, 0, allow)]
    # glibc falls back to clone when clone3 returns ENOSYS. Its flags live in
    # pointed-to memory which classic BPF cannot inspect safely.
    instructions += [(0x15, 0, 1, 435), (0x06, 0, 0, 0x00050000 | errno.ENOSYS)]
    # clone args[0] at offset 16: permit CLONE_THREAD only. Linux also requires
    # CLONE_SIGHAND/CLONE_VM for a thread, so this cannot create a new process.
    instructions += [(0x15, 0, 4, clone), (0x20, 0, 0, 16),
                     (0x45, 1, 0, 0x00010000), (0x06, 0, 0, deny),
                     (0x06, 0, 0, allow), (0x06, 0, 0, allow)]
    return instructions


def _seccomp(libc):
    class Filter(ctypes.Structure):
        _fields_ = [('code', ctypes.c_ushort), ('jt', ctypes.c_ubyte),
                    ('jf', ctypes.c_ubyte), ('k', ctypes.c_uint32)]

    class Program(ctypes.Structure):
        _fields_ = [('len', ctypes.c_ushort), ('filter', ctypes.POINTER(Filter))]

    instructions = _seccomp_instructions(platform.machine().lower())
    filters = (Filter * len(instructions))(*(Filter(*values) for values in instructions))
    program = Program(len(filters), filters)
    _check(libc.prctl(22, 2, ctypes.byref(program), 0, 0), 'Seccomp filter')


def _linux_sandbox(tmpdir):
    libc = ctypes.CDLL(None, use_errno=True)
    libc.syscall.restype = ctypes.c_long
    _check(libc.prctl(38, 1, 0, 0, 0), 'PR_SET_NO_NEW_PRIVS')
    protections = {'landlock_abi': 0, 'seccomp': False}
    try:
        protections['landlock_abi'] = _landlock(libc, tmpdir)
        protections['landlock_policy_abi'] = min(3, protections['landlock_abi'])
    except (OSError, RuntimeError) as exc:
        protections['landlock_error'] = str(exc)
    try:
        _seccomp(libc)
        protections['seccomp'] = True
    except (OSError, RuntimeError) as exc:
        protections['seccomp_error'] = str(exc)
    if not protections['seccomp']:
        raise SandboxUnavailable(protections)
    return protections


def _audit_policy(event, args):
    # Audit hooks are defense in depth, not a replacement for kernel enforcement.
    # Deny whole event families so new stdlib network APIs inherit the policy.
    if (event.startswith(('socket.', 'smtplib.', 'os.exec', 'os.spawn',
                          'os.posix_spawn', 'os.fork')) or
            event in ('urllib.Request', 'http.client.connect', 'ftplib.connect',
                      'subprocess.Popen', 'os.system', 'ctypes.dlopen')):
        raise PermissionError(f'Code execution policy blocked: {event}')


def _install_audit_policy():
    # libc was loaded by trusted sandbox setup. No later dynamic ctypes loads
    # (including CDLL(None)) are needed by the supported math/date stdlib.
    sys.addaudithook(_audit_policy)


def _write_metadata(metadata_fd, protections):
    try:
        os.write(metadata_fd, json.dumps(protections).encode('utf-8'))
    finally:
        os.close(metadata_fd)


def _execute_script(script):
    # Use normal script semantics, including __main__ imports, without execve.
    with open(script, 'rb') as stream:
        source = compile(stream.read(), script, 'exec')
    import types
    module = types.ModuleType('__main__')
    module.__file__ = script
    module.__builtins__ = __builtins__
    sys.modules['__main__'] = module
    exec(source, module.__dict__)


def main():
    if sys.platform != 'linux':
        raise RuntimeError('Code execution requires the Linux kernel sandbox')
    script, uid, gid, serialized_limits, metadata_fd = sys.argv[1:]
    limits = json.loads(serialized_limits)
    os.umask(0o077)
    if os.geteuid() == 0:
        os.setgroups([])
        os.setgid(int(gid))
        os.setuid(int(uid))
    if os.geteuid() == 0:
        raise RuntimeError('Refusing to execute submitted code as root')
    _limit(resource.RLIMIT_CPU, limits['cpu'])
    _limit(resource.RLIMIT_AS, limits['memory'])
    _limit(resource.RLIMIT_FSIZE, limits['file'])
    _limit(resource.RLIMIT_NOFILE, limits['open_files'])
    _limit(resource.RLIMIT_CORE, 0)
    try:
        protections = _linux_sandbox(os.getcwd())
    except SandboxUnavailable as exc:
        _write_metadata(int(metadata_fd), exc.protections)
        raise
    # Seccomp blocks process creation without exhausting the rootless uid's threads.
    _install_audit_policy()
    _write_metadata(int(metadata_fd), protections)
    sys.argv = [script]
    # No launcher argv or metadata descriptor is exposed to the script.
    _execute_script(script)


def _print_user_traceback(exc):
    # Hide the launcher's own frames so stderr looks like `python script.py`
    # (and does not expose sandbox internals to the model).
    tb = exc.__traceback__
    while tb is not None and os.path.abspath(tb.tb_frame.f_code.co_filename) == os.path.abspath(__file__):
        tb = tb.tb_next
    if tb is None:  # e.g. SyntaxError raised by compile(): no user frame
        sys.stderr.write(''.join(traceback.format_exception_only(type(exc), exc)))
    else:
        sys.stderr.write(''.join(traceback.format_exception(type(exc), exc, tb)))


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        _print_user_traceback(exc)
        sys.exit(1)
