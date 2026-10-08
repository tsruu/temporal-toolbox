"""Trusted single-threaded pre-exec launcher, called with python -I.

No user code is evaluated until limits and Linux kernel restrictions are in
place. This process becomes the submitted Python interpreter via os.execv.
"""
import ctypes
import errno
import json
import os
import platform
import resource
import sys


def _limit(kind, value):
    _, hard = resource.getrlimit(kind)
    value = value if hard == resource.RLIM_INFINITY else min(value, hard)
    resource.setrlimit(kind, (value, value))


def _linux_sandbox(tmpdir):
    libc = ctypes.CDLL(None, use_errno=True)
    libc.syscall.restype = ctypes.c_long

    def check(result, name):
        if result < 0:
            raise OSError(ctypes.get_errno(), f'{name}: {os.strerror(ctypes.get_errno())}')
        return result

    # No elevated privilege or container namespace is needed for either API.
    check(libc.prctl(38, 1, 0, 0, 0), 'PR_SET_NO_NEW_PRIVS')

    # Landlock restricts mutation to this execution's directory, and reads to
    # the interpreter/system libraries and a few non-secret runtime files.
    # ABI 1 handles writes/create/remove, ABI 2 cross-directory rename/link,
    # ABI 3 truncate. In particular, /app, /home and /proc are not readable.
    abi = check(libc.syscall(444, 0, 0, 1), 'Landlock ABI query')
    if abi < 3:
        raise RuntimeError('Landlock ABI >= 3 required for write/truncate confinement')
    read_access = (1 << 2) | (1 << 3)
    handled = (1 << 1) | read_access | sum(1 << bit for bit in range(4, 15))

    class Ruleset(ctypes.Structure):
        _fields_ = [('handled_access_fs', ctypes.c_uint64)]

    class PathBeneath(ctypes.Structure):
        _pack_ = 1
        _fields_ = [('allowed_access', ctypes.c_uint64), ('parent_fd', ctypes.c_int32)]

    ruleset = Ruleset(handled)
    ruleset_fd = check(libc.syscall(444, ctypes.byref(ruleset), ctypes.sizeof(ruleset), 0),
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
                check(libc.syscall(445, ruleset_fd, 1, ctypes.byref(rule), 0),
                      'Landlock path rule')
            finally:
                os.close(path_fd)
        check(libc.syscall(446, ruleset_fd, 0), 'Landlock restrict_self')
    finally:
        os.close(ruleset_fd)

    # Deny sockets (including Unix sockets), process/thread creation,
    # process-group/session escape and ptrace. NPROC remains a second limit.
    # Preventing forks also avoids orphan zombie accumulation under uvicorn PID1.
    machine = platform.machine().lower()
    if machine in ('x86_64', 'amd64'):
        audit_arch = 0xC000003E
        denied = [41, 42, 43, 49, 50, 53, 56, 57, 58, 62, 101, 109, 112,
                  129, 200, 234, 288, 297, 310, 311, 424, 435, 438]
    elif machine in ('aarch64', 'arm64'):
        audit_arch = 0xC00000B7
        denied = [117, 129, 130, 131, 138, 154, 157, 198, 199, 200, 201,
                  202, 203, 220, 240, 242, 270, 271, 424, 435, 438]
    else:
        raise RuntimeError(f'Unsupported seccomp architecture: {machine}')

    class Filter(ctypes.Structure):
        _fields_ = [('code', ctypes.c_ushort), ('jt', ctypes.c_ubyte),
                    ('jf', ctypes.c_ubyte), ('k', ctypes.c_uint32)]

    class Program(ctypes.Structure):
        _fields_ = [('len', ctypes.c_ushort), ('filter', ctypes.POINTER(Filter))]

    # Validate arch; kill alternate ABI attempts, including x32 on x86_64.
    instructions = [(0x20, 0, 0, 4), (0x15, 1, 0, audit_arch),
                    (0x06, 0, 0, 0x80000000), (0x20, 0, 0, 0)]
    if machine in ('x86_64', 'amd64'):
        instructions += [(0x45, 0, 1, 0x40000000), (0x06, 0, 0, 0x80000000)]
    for number in denied:
        instructions += [(0x15, 0, 1, number), (0x06, 0, 0, 0x00050000 | errno.EPERM)]
    instructions.append((0x06, 0, 0, 0x7FFF0000))
    filters = (Filter * len(instructions))(*(Filter(*values) for values in instructions))
    program = Program(len(filters), filters)
    check(libc.prctl(22, 2, ctypes.byref(program), 0, 0), 'Seccomp filter')


def main():
    if sys.platform != 'linux':
        raise RuntimeError('Code execution requires the Linux kernel sandbox')
    script, uid, gid, serialized_limits = sys.argv[1:]
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
    _limit(resource.RLIMIT_NPROC, limits['processes'])
    _limit(resource.RLIMIT_NOFILE, limits['open_files'])
    _limit(resource.RLIMIT_CORE, 0)
    _linux_sandbox(os.getcwd())
    os.execv(sys.executable, [sys.executable, '-I', script])


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print(f'Execution sandbox setup failed: {exc}', file=sys.stderr)
        sys.exit(1)
