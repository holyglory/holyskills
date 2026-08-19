"""Cross-platform process identity for deferred installation.

The installer normally invokes a reviewed runtime's native lifecycle command.
On Linux only, a reviewed legacy Codex transition may request graceful SIGTERM
through a pidfd after transient clients exit; it never signals a bare PID and
never escalates to SIGKILL.
A PID is useful only together with a kernel creation marker and executable
identity, so PID reuse cannot be mistaken for the process that the caller
reviewed.
"""

from __future__ import annotations

from dataclasses import dataclass
import ctypes
import os
from pathlib import Path
import signal
import stat
import sys
from typing import Any, Dict, Iterable, List, Sequence, Tuple


class ProcessIdentityError(RuntimeError):
    """A requested process identity cannot be established safely."""


class ProcessNotFound(ProcessIdentityError):
    """The requested process no longer exists."""


@dataclass(frozen=True)
class ProcessIdentity:
    pid: int
    creation: str
    owner: str
    executable_path: str
    executable_file_id: str

    def private_value(self) -> Dict[str, Any]:
        return {
            "pid": self.pid,
            "creation": self.creation,
            "owner": self.owner,
            "executable_path": self.executable_path,
            "executable_file_id": self.executable_file_id,
        }

    @classmethod
    def from_private_value(cls, value: Any) -> "ProcessIdentity":
        if not isinstance(value, dict) or set(value) != {
            "pid",
            "creation",
            "owner",
            "executable_path",
            "executable_file_id",
        }:
            raise ProcessIdentityError("process identity shape is invalid")
        pid = value.get("pid")
        fields = [
            value.get("creation"),
            value.get("owner"),
            value.get("executable_path"),
            value.get("executable_file_id"),
        ]
        if (
            not isinstance(pid, int)
            or isinstance(pid, bool)
            or pid <= 0
            or any(not isinstance(item, str) or not item or len(item) > 4096 for item in fields)
        ):
            raise ProcessIdentityError("process identity value is invalid")
        return cls(pid, fields[0], fields[1], fields[2], fields[3])

    def same_process(self, other: "ProcessIdentity") -> bool:
        return (
            self.pid == other.pid
            and self.creation == other.creation
            and self.owner == other.owner
        )

    def same_image(self, other: "ProcessIdentity") -> bool:
        return self.owner == other.owner and (
            self.executable_path == other.executable_path
            or self.executable_file_id == other.executable_file_id
        )


def _file_identity_from_metadata(metadata: os.stat_result) -> str:
    if not stat.S_ISREG(metadata.st_mode):
        raise ProcessIdentityError("process executable is not a regular file")
    return "{}:{}".format(int(metadata.st_dev), int(metadata.st_ino))


def _file_identity(path: str) -> str:
    try:
        metadata = os.stat(path)
    except OSError as error:
        raise ProcessIdentityError("process executable identity is unavailable") from error
    return _file_identity_from_metadata(metadata)


def _normalize_executable(path: str) -> str:
    if not path or not os.path.isabs(path):
        raise ProcessIdentityError("process executable path is not absolute")
    return os.path.normcase(os.path.realpath(path))


def _normalize_linux_executable_link(path: str) -> str:
    """Normalize procfs link text without restating the executable inode."""

    deleted_suffix = " (deleted)"
    if path.endswith(deleted_suffix):
        path = path[: -len(deleted_suffix)]
    if not path or not os.path.isabs(path):
        raise ProcessIdentityError("process executable path is not absolute")
    return os.path.normcase(os.path.normpath(path))


class ProcessInspector:
    """Capture and compare exact process incarnations on the current host."""

    def __init__(self) -> None:
        if os.name == "nt":
            self._backend: Any = _WindowsBackend()
        elif sys.platform == "darwin":
            self._backend = _DarwinBackend()
        elif sys.platform.startswith("linux"):
            self._backend = _LinuxBackend()
        else:
            raise ProcessIdentityError("process identity is unsupported on this operating system")
        self.owner = self._backend.current_owner()

    def capture(self, pid: int) -> ProcessIdentity:
        if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0:
            raise ProcessIdentityError("target PID is invalid")
        identity = self._backend.capture(pid)
        if identity.owner != self.owner:
            raise ProcessIdentityError("target process belongs to another user")
        return identity

    def capture_many(self, pids: Sequence[int]) -> List[ProcessIdentity]:
        if not pids or len(pids) > 128 or len(set(pids)) != len(pids):
            raise ProcessIdentityError("target PID set is empty, duplicated, or exceeds its bound")
        return [self.capture(pid) for pid in pids]

    def bind_reviewed_pid_namespaces(
        self, targets: Sequence[ProcessIdentity]
    ) -> None:
        """Bind Linux namespace evidence while every reviewed target is exact."""

        binder = getattr(self._backend, "bind_reviewed_pid_namespaces", None)
        if binder is not None:
            binder(targets)

    def is_alive(self, identity: ProcessIdentity) -> bool:
        try:
            current = self._backend.capture(identity.pid)
        except ProcessNotFound:
            return False
        return identity.same_process(current)

    def is_exact(self, identity: ProcessIdentity) -> bool:
        """Return true only while the complete reviewed process image is unchanged."""

        try:
            current = self._backend.capture(identity.pid)
        except ProcessNotFound:
            return False
        return identity == current

    def executable_path_matches(self, identity: ProcessIdentity) -> bool:
        """Recheck that the executable pathname still resolves to the reviewed file."""

        if identity.owner != self.owner:
            raise ProcessIdentityError("process executable belongs to another user")
        try:
            current_file_id = _file_identity(identity.executable_path)
        except ProcessIdentityError:
            return False
        return current_file_id == identity.executable_file_id

    @staticmethod
    def supports_exact_graceful_termination() -> bool:
        """Return whether the host exposes a process-incarnation-bound SIGTERM."""

        return (
            sys.platform.startswith("linux")
            and hasattr(os, "pidfd_open")
            and hasattr(signal, "pidfd_send_signal")
        )

    def terminate_exact_gracefully(self, identity: ProcessIdentity) -> None:
        """Gracefully terminate one exact Linux process through a pidfd."""

        if not self.supports_exact_graceful_termination():
            raise ProcessIdentityError(
                "exact graceful process termination is unsupported on this host"
            )
        if identity.owner != self.owner or not self.executable_path_matches(identity):
            raise ProcessIdentityError("process termination target is not exact")
        try:
            descriptor = os.pidfd_open(identity.pid, 0)
        except ProcessLookupError as error:
            raise ProcessNotFound("process no longer exists") from error
        except OSError as error:
            raise ProcessIdentityError("process pidfd is unavailable") from error
        try:
            current = self._backend.capture(identity.pid)
            if current != identity:
                raise ProcessIdentityError("process changed before termination")
            try:
                signal.pidfd_send_signal(descriptor, signal.SIGTERM)
            except ProcessLookupError:
                return
            except OSError as error:
                raise ProcessIdentityError(
                    "exact graceful process termination failed"
                ) from error
        finally:
            os.close(descriptor)

    @staticmethod
    def _hint_could_match(hint: str, targets: Sequence[ProcessIdentity]) -> bool:
        normalized = os.path.normcase(hint)
        for target in targets:
            basename = os.path.normcase(os.path.basename(target.executable_path))
            if normalized == basename:
                return True
            if len(normalized) in {15, 31} and basename.startswith(normalized):
                return True
        return False

    def list_processes(
        self, targets: Sequence[ProcessIdentity] = ()
    ) -> List[ProcessIdentity]:
        result: List[ProcessIdentity] = []
        for pid in self._backend.list_pids():
            try:
                owner = self._backend.owner(pid)
            except ProcessNotFound:
                continue
            if owner != self.owner:
                continue
            try:
                identity = self._backend.capture(pid)
            except ProcessNotFound:
                continue
            except ProcessIdentityError:
                hints = self._backend.image_hints(pid)
                if targets and hints and not any(
                    self._hint_could_match(hint, targets) for hint in hints
                ):
                    # The kernel-provided executable names prove this live
                    # process cannot be one of the reviewed target images.
                    continue
                proves_separate = getattr(
                    self._backend, "proves_separate_pid_namespace", None
                )
                if targets and proves_separate is not None and proves_separate(
                    pid, targets
                ):
                    continue
                raise
            if identity.owner != owner:
                raise ProcessIdentityError(
                    "process owner changed while inventory was captured"
                )
            result.append(identity)
        return result

    def baseline_image_peers(
        self, targets: Sequence[ProcessIdentity], *, maximum: int = 1024
    ) -> List[ProcessIdentity]:
        peers = [
            item
            for item in self.list_processes(targets)
            if any(item.same_image(target) for target in targets)
            and not any(item.same_process(target) for target in targets)
        ]
        if len(peers) > maximum:
            raise ProcessIdentityError("same-image process peer set exceeds its safe bound")
        return peers

    def detected_relaunches(
        self,
        targets: Sequence[ProcessIdentity],
        baseline_peers: Sequence[ProcessIdentity],
    ) -> List[ProcessIdentity]:
        known = tuple(targets) + tuple(baseline_peers)
        return [
            item
            for item in self.list_processes(targets)
            if any(item.same_image(target) for target in targets)
            and not any(item.same_process(previous) for previous in known)
        ]


class _LinuxBackend:
    def __init__(self) -> None:
        try:
            self._boot_id = Path("/proc/sys/kernel/random/boot_id").read_text(
                encoding="ascii"
            ).strip()
        except OSError as error:
            raise ProcessIdentityError("Linux boot identity is unavailable") from error
        if not self._boot_id or len(self._boot_id) > 128:
            raise ProcessIdentityError("Linux boot identity is invalid")
        self._reviewed_pid_namespace_depths: Dict[ProcessIdentity, int] = {}

    def current_owner(self) -> str:
        return "uid:{}".format(os.geteuid())

    def owner(self, pid: int) -> str:
        try:
            return "uid:{}".format(Path("/proc/{}".format(pid)).stat().st_uid)
        except FileNotFoundError as error:
            raise ProcessNotFound("process no longer exists") from error
        except PermissionError as error:
            raise ProcessIdentityError("Linux process owner is not readable") from error
        except OSError as error:
            raise ProcessIdentityError("Linux process owner is unavailable") from error

    def image_hints(self, pid: int) -> Tuple[str, ...]:
        try:
            raw = Path("/proc/{}/comm".format(pid)).read_bytes()
        except FileNotFoundError as error:
            raise ProcessNotFound("process no longer exists") from error
        except OSError as error:
            raise ProcessIdentityError("Linux process image hint is unavailable") from error
        try:
            hint = raw.rstrip(b"\n").decode("utf-8")
        except UnicodeDecodeError as error:
            raise ProcessIdentityError("Linux process image hint is invalid") from error
        return (hint,) if hint else ()

    def _start_time(self, pid: int) -> str:
        try:
            raw = Path("/proc/{}/stat".format(pid)).read_bytes()
        except FileNotFoundError as error:
            raise ProcessNotFound("process no longer exists") from error
        except OSError as error:
            raise ProcessIdentityError("Linux process start identity is unavailable") from error
        closing = raw.rfind(b")")
        if closing < 0:
            raise ProcessIdentityError("Linux process stat record is malformed")
        fields = raw[closing + 1 :].split()
        if len(fields) <= 19 or not fields[19].isdigit():
            raise ProcessIdentityError("Linux process start identity is malformed")
        return "{}:{}".format(self._boot_id, fields[19].decode("ascii"))

    def capture(self, pid: int) -> ProcessIdentity:
        first = self._start_time(pid)
        root = Path("/proc/{}".format(pid))
        try:
            owner = self.owner(pid)
            executable_link = root / "exe"
            executable = _normalize_linux_executable_link(
                os.readlink(str(executable_link))
            )
            # Stat procfs directly: its link still names the running inode when
            # the pathname was replaced or the executable has been deleted.
            executable_id = _file_identity_from_metadata(os.stat(str(executable_link)))
        except FileNotFoundError as error:
            raise ProcessNotFound("process no longer exists") from error
        except PermissionError as error:
            raise ProcessIdentityError("Linux process identity is not readable") from error
        second = self._start_time(pid)
        if first != second:
            raise ProcessNotFound("process changed while its identity was captured")
        return ProcessIdentity(pid, first, owner, executable, executable_id)

    def _pid_namespace_depth(self, pid: int) -> int:
        try:
            raw = Path("/proc/{}/status".format(pid)).read_bytes()
        except FileNotFoundError as error:
            raise ProcessNotFound("process no longer exists") from error
        except OSError as error:
            raise ProcessIdentityError(
                "Linux PID namespace evidence is unavailable"
            ) from error
        for line in raw.splitlines():
            if not line.startswith(b"NSpid:"):
                continue
            values = line.split()[1:]
            if (
                not values
                or any(not value.isdigit() for value in values)
                or int(values[0]) != pid
            ):
                break
            return len(values)
        raise ProcessIdentityError("Linux PID namespace evidence is invalid")

    def bind_reviewed_pid_namespaces(
        self, targets: Sequence[ProcessIdentity]
    ) -> None:
        """Capture every exact reviewed target's namespace depth before waiting."""

        depths: Dict[ProcessIdentity, int] = {}
        for target in targets:
            if self.capture(target.pid) != target:
                raise ProcessIdentityError(
                    "reviewed process changed before namespace binding"
                )
            depths[target] = self._pid_namespace_depth(target.pid)
        if len(depths) != len(targets):
            raise ProcessIdentityError("reviewed PID namespace binding is incomplete")
        self._reviewed_pid_namespace_depths = depths

    def proves_separate_pid_namespace(
        self, pid: int, targets: Sequence[ProcessIdentity]
    ) -> bool:
        """Prove an unreadable process is outside every reviewed PID namespace."""

        try:
            candidate_depth = self._pid_namespace_depth(pid)
            bound = getattr(self, "_reviewed_pid_namespace_depths", {})
            if bound:
                if any(target not in bound for target in targets):
                    return False
                target_depths = {bound[target] for target in targets}
            else:
                target_depths = {
                    self._pid_namespace_depth(target.pid) for target in targets
                }
        except ProcessIdentityError:
            return False
        return bool(target_depths) and candidate_depth not in target_depths

    def list_pids(self) -> Iterable[int]:
        try:
            names = os.listdir("/proc")
        except OSError as error:
            raise ProcessIdentityError("Linux process inventory is unavailable") from error
        return (int(name) for name in names if name.isdigit())


class _DarwinProcBsdInfo(ctypes.Structure):
    _fields_ = [
        ("pbi_flags", ctypes.c_uint32),
        ("pbi_status", ctypes.c_uint32),
        ("pbi_xstatus", ctypes.c_uint32),
        ("pbi_pid", ctypes.c_uint32),
        ("pbi_ppid", ctypes.c_uint32),
        ("pbi_uid", ctypes.c_uint32),
        ("pbi_gid", ctypes.c_uint32),
        ("pbi_ruid", ctypes.c_uint32),
        ("pbi_rgid", ctypes.c_uint32),
        ("pbi_svuid", ctypes.c_uint32),
        ("pbi_svgid", ctypes.c_uint32),
        ("rfu_1", ctypes.c_uint32),
        ("pbi_comm", ctypes.c_char * 16),
        ("pbi_name", ctypes.c_char * 32),
        ("pbi_nfiles", ctypes.c_uint32),
        ("pbi_pgid", ctypes.c_uint32),
        ("pbi_pjobc", ctypes.c_uint32),
        ("e_tdev", ctypes.c_uint32),
        ("e_tpgid", ctypes.c_uint32),
        ("pbi_nice", ctypes.c_int32),
        ("pbi_start_tvsec", ctypes.c_uint64),
        ("pbi_start_tvusec", ctypes.c_uint64),
    ]


class _DarwinBackend:
    _PROC_ALL_PIDS = 1
    _PROC_PIDTBSDINFO = 3
    _PROC_PIDPATHINFO_MAXSIZE = 4096

    def __init__(self) -> None:
        try:
            self._libproc = ctypes.CDLL("libproc.dylib", use_errno=True)
        except OSError as error:
            raise ProcessIdentityError("macOS process API is unavailable") from error
        self._libproc.proc_pidinfo.argtypes = [
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_uint64,
            ctypes.c_void_p,
            ctypes.c_int,
        ]
        self._libproc.proc_pidinfo.restype = ctypes.c_int
        self._libproc.proc_pidpath.argtypes = [ctypes.c_int, ctypes.c_void_p, ctypes.c_uint32]
        self._libproc.proc_pidpath.restype = ctypes.c_int
        self._libproc.proc_listpids.argtypes = [
            ctypes.c_uint32,
            ctypes.c_uint32,
            ctypes.c_void_p,
            ctypes.c_int,
        ]
        self._libproc.proc_listpids.restype = ctypes.c_int

    def current_owner(self) -> str:
        return "uid:{}".format(os.geteuid())

    def owner(self, pid: int) -> str:
        return "uid:{}".format(int(self._info(pid).pbi_uid))

    def image_hints(self, pid: int) -> Tuple[str, ...]:
        info = self._info(pid)
        result: List[str] = []
        for raw in (bytes(info.pbi_comm), bytes(info.pbi_name)):
            try:
                value = raw.split(b"\0", 1)[0].decode("utf-8")
            except UnicodeDecodeError as error:
                raise ProcessIdentityError("macOS process image hint is invalid") from error
            if value and value not in result:
                result.append(value)
        return tuple(result)

    def _info(self, pid: int) -> _DarwinProcBsdInfo:
        value = _DarwinProcBsdInfo()
        size = self._libproc.proc_pidinfo(
            pid,
            self._PROC_PIDTBSDINFO,
            0,
            ctypes.byref(value),
            ctypes.sizeof(value),
        )
        if size == 0:
            raise ProcessNotFound("process no longer exists")
        if size != ctypes.sizeof(value) or value.pbi_pid != pid:
            raise ProcessIdentityError("macOS process identity is incomplete")
        return value

    def capture(self, pid: int) -> ProcessIdentity:
        first = self._info(pid)
        buffer = ctypes.create_string_buffer(self._PROC_PIDPATHINFO_MAXSIZE)
        size = self._libproc.proc_pidpath(pid, buffer, len(buffer))
        if size <= 0:
            # Inventory races are ordinary exits, not ambiguous live
            # processes.  A still-readable BSD record makes this a real
            # identity ambiguity and therefore remains fail-closed.
            try:
                self._info(pid)
            except ProcessNotFound:
                raise
            raise ProcessIdentityError("macOS process executable is unavailable")
        try:
            raw_path = buffer.value.decode("utf-8")
        except UnicodeDecodeError as error:
            raise ProcessIdentityError("macOS process executable is not UTF-8") from error
        executable = _normalize_executable(raw_path)
        executable_id = _file_identity(executable)
        second = self._info(pid)
        creation = "{}:{}".format(
            int(first.pbi_start_tvsec), int(first.pbi_start_tvusec)
        )
        if creation != "{}:{}".format(
            int(second.pbi_start_tvsec), int(second.pbi_start_tvusec)
        ):
            raise ProcessNotFound("process changed while its identity was captured")
        return ProcessIdentity(
            pid,
            creation,
            "uid:{}".format(int(first.pbi_uid)),
            executable,
            executable_id,
        )

    def list_pids(self) -> Iterable[int]:
        required = self._libproc.proc_listpids(self._PROC_ALL_PIDS, 0, None, 0)
        if required <= 0:
            raise ProcessIdentityError("macOS process inventory is unavailable")
        count = max(128, required // ctypes.sizeof(ctypes.c_int) + 64)
        values = (ctypes.c_int * count)()
        actual = self._libproc.proc_listpids(
            self._PROC_ALL_PIDS, 0, ctypes.byref(values), ctypes.sizeof(values)
        )
        if actual < 0:
            raise ProcessIdentityError("macOS process inventory failed")
        return [pid for pid in values[: actual // ctypes.sizeof(ctypes.c_int)] if pid > 0]


class _WindowsFileTime(ctypes.Structure):
    _fields_ = [("low", ctypes.c_uint32), ("high", ctypes.c_uint32)]

    def integer(self) -> int:
        return (int(self.high) << 32) | int(self.low)


class _WindowsBackend:
    _PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    _SYNCHRONIZE = 0x00100000
    _TOKEN_QUERY = 0x0008
    _TOKEN_USER = 1

    def __init__(self) -> None:
        if os.name != "nt":
            raise ProcessIdentityError("Windows process API is unavailable")
        self._kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self._advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
        self._psapi = ctypes.WinDLL("psapi", use_last_error=True)
        handle = ctypes.c_void_p
        dword = ctypes.c_uint32
        boolean = ctypes.c_int
        self._kernel32.GetCurrentProcess.argtypes = []
        self._kernel32.GetCurrentProcess.restype = handle
        self._kernel32.OpenProcess.argtypes = [dword, boolean, dword]
        self._kernel32.OpenProcess.restype = handle
        self._kernel32.CloseHandle.argtypes = [handle]
        self._kernel32.CloseHandle.restype = boolean
        self._kernel32.GetProcessTimes.argtypes = [
            handle,
            ctypes.POINTER(_WindowsFileTime),
            ctypes.POINTER(_WindowsFileTime),
            ctypes.POINTER(_WindowsFileTime),
            ctypes.POINTER(_WindowsFileTime),
        ]
        self._kernel32.GetProcessTimes.restype = boolean
        self._kernel32.QueryFullProcessImageNameW.argtypes = [
            handle,
            dword,
            ctypes.c_wchar_p,
            ctypes.POINTER(dword),
        ]
        self._kernel32.QueryFullProcessImageNameW.restype = boolean
        self._kernel32.LocalFree.argtypes = [handle]
        self._kernel32.LocalFree.restype = handle
        self._advapi32.OpenProcessToken.argtypes = [
            handle,
            dword,
            ctypes.POINTER(handle),
        ]
        self._advapi32.OpenProcessToken.restype = boolean
        self._advapi32.GetTokenInformation.argtypes = [
            handle,
            ctypes.c_int,
            ctypes.c_void_p,
            dword,
            ctypes.POINTER(dword),
        ]
        self._advapi32.GetTokenInformation.restype = boolean
        self._advapi32.ConvertSidToStringSidW.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_wchar_p),
        ]
        self._advapi32.ConvertSidToStringSidW.restype = boolean
        self._psapi.EnumProcesses.argtypes = [
            ctypes.c_void_p,
            dword,
            ctypes.POINTER(dword),
        ]
        self._psapi.EnumProcesses.restype = boolean
        self._owner = self._owner_for_handle(self._kernel32.GetCurrentProcess())

    def current_owner(self) -> str:
        return self._owner

    def owner(self, pid: int) -> str:
        handle = self._open(pid)
        try:
            return self._owner_for_handle(handle)
        finally:
            self._kernel32.CloseHandle(handle)

    def image_hints(self, pid: int) -> Tuple[str, ...]:
        handle = self._open(pid)
        try:
            size = ctypes.c_uint32(32768)
            buffer = ctypes.create_unicode_buffer(size.value)
            if not self._kernel32.QueryFullProcessImageNameW(
                handle, 0, buffer, ctypes.byref(size)
            ):
                raise ProcessIdentityError("Windows process image hint is unavailable")
            value = os.path.basename(buffer.value[: size.value])
            return (value,) if value else ()
        finally:
            self._kernel32.CloseHandle(handle)

    def _open(self, pid: int) -> int:
        handle = self._kernel32.OpenProcess(
            self._PROCESS_QUERY_LIMITED_INFORMATION | self._SYNCHRONIZE,
            False,
            pid,
        )
        if not handle:
            error = ctypes.get_last_error()
            if error in {87, 1168}:
                raise ProcessNotFound("process no longer exists")
            raise ProcessIdentityError("Windows process identity is not readable")
        return int(handle)

    def _owner_for_handle(self, process: int) -> str:
        token = ctypes.c_void_p()
        if not self._advapi32.OpenProcessToken(process, self._TOKEN_QUERY, ctypes.byref(token)):
            raise ProcessIdentityError("Windows process owner is unavailable")
        try:
            needed = ctypes.c_uint32()
            self._advapi32.GetTokenInformation(
                token, self._TOKEN_USER, None, 0, ctypes.byref(needed)
            )
            if needed.value == 0:
                raise ProcessIdentityError("Windows process owner size is unavailable")
            buffer = ctypes.create_string_buffer(needed.value)
            if not self._advapi32.GetTokenInformation(
                token,
                self._TOKEN_USER,
                buffer,
                needed.value,
                ctypes.byref(needed),
            ):
                raise ProcessIdentityError("Windows process owner is unavailable")
            sid_pointer = ctypes.c_void_p.from_buffer(buffer).value
            string_sid = ctypes.c_wchar_p()
            if not self._advapi32.ConvertSidToStringSidW(
                sid_pointer, ctypes.byref(string_sid)
            ):
                raise ProcessIdentityError("Windows process owner SID is unavailable")
            try:
                return "sid:{}".format(string_sid.value)
            finally:
                self._kernel32.LocalFree(ctypes.cast(string_sid, ctypes.c_void_p))
        finally:
            self._kernel32.CloseHandle(token)

    def capture(self, pid: int) -> ProcessIdentity:
        handle = self._open(pid)
        try:
            creation = _WindowsFileTime()
            exit_time = _WindowsFileTime()
            kernel = _WindowsFileTime()
            user = _WindowsFileTime()
            if not self._kernel32.GetProcessTimes(
                handle,
                ctypes.byref(creation),
                ctypes.byref(exit_time),
                ctypes.byref(kernel),
                ctypes.byref(user),
            ):
                raise ProcessIdentityError("Windows process creation time is unavailable")
            size = ctypes.c_uint32(32768)
            buffer = ctypes.create_unicode_buffer(size.value)
            if not self._kernel32.QueryFullProcessImageNameW(
                handle, 0, buffer, ctypes.byref(size)
            ):
                raise ProcessIdentityError("Windows process executable is unavailable")
            executable = _normalize_executable(buffer.value[: size.value])
            return ProcessIdentity(
                pid,
                str(creation.integer()),
                self._owner_for_handle(handle),
                executable,
                _file_identity(executable),
            )
        finally:
            self._kernel32.CloseHandle(handle)

    def list_pids(self) -> Iterable[int]:
        count = 1024
        while count <= 65536:
            values = (ctypes.c_uint32 * count)()
            needed = ctypes.c_uint32()
            if not self._psapi.EnumProcesses(
                ctypes.byref(values), ctypes.sizeof(values), ctypes.byref(needed)
            ):
                raise ProcessIdentityError("Windows process inventory is unavailable")
            actual = needed.value // ctypes.sizeof(ctypes.c_uint32)
            if actual < count:
                return [pid for pid in values[:actual] if pid > 0]
            count *= 2
        raise ProcessIdentityError("Windows process inventory exceeds its safe bound")


__all__ = [
    "ProcessIdentity",
    "ProcessIdentityError",
    "ProcessInspector",
    "ProcessNotFound",
]
