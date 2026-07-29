"""Cross-platform state placement for the delivery-efficiency recorder."""

from __future__ import annotations

import ctypes
import ntpath
import os
import platform as platform_module
import posixpath
import re
from dataclasses import dataclass
from pathlib import Path
from typing import List, Mapping, Optional


STATE_OVERRIDE_ENV = "HOLYSKILLS_DELIVERY_EFFICIENCY_STATE_DIR"
_DARWIN_MNT_LOCAL = 0x00001000
_WINDOWS_LOCAL_DRIVE_TYPES = frozenset({3})
_LINUX_LOCAL_FILESYSTEMS = frozenset(
    {
        "aufs",
        "bcachefs",
        "btrfs",
        "ext2",
        "ext3",
        "ext4",
        "f2fs",
        "jfs",
        "lxfs",
        "nilfs2",
        "overlay",
        "reiserfs",
        "ubifs",
        "wslfs",
        "xfs",
        "zfs",
    }
)
_LINUX_VOLATILE_FILESYSTEMS = frozenset({"ramfs", "tmpfs"})
_LINUX_REMOTE_FILESYSTEMS = frozenset(
    {
        "9p",
        "afs",
        "ceph",
        "cifs",
        "davfs",
        "davfs2",
        "drvfs",
        "gfs2",
        "glusterfs",
        "lustre",
        "ncpfs",
        "nfs",
        "nfs4",
        "ocfs2",
        "smb",
        "smb2",
        "sshfs",
        "virtiofs",
    }
)


class PlatformConfigurationError(ValueError):
    """Raised when the recorder cannot select a safe local state directory."""


@dataclass(frozen=True)
class PlatformIdentity:
    os: str
    environment: str

    def as_event_value(self):
        return {"os": self.os, "environment": self.environment}


@dataclass(frozen=True)
class _LinuxMount:
    mount_point: str
    filesystem_type: str
    source: str
    mount_options: str
    super_options: str


def detect_platform(
    *,
    system: Optional[str] = None,
    release: Optional[str] = None,
    environ: Optional[Mapping[str, str]] = None,
) -> PlatformIdentity:
    """Detect native Windows/macOS/Linux and distinguish WSL from Linux."""

    env = _casefold_environment(os.environ if environ is None else environ)
    system_value = (platform_module.system() if system is None else system).strip().lower()
    release_value = (platform_module.release() if release is None else release).strip().lower()
    if system_value == "windows":
        return PlatformIdentity("windows", "native")
    if system_value == "darwin":
        return PlatformIdentity("macos", "native")
    if system_value == "linux":
        is_wsl = (
            "microsoft" in release_value
            or "WSL_DISTRO_NAME" in env
            or "WSL_INTEROP" in env
        )
        return PlatformIdentity("linux", "wsl" if is_wsl else "native")
    raise PlatformConfigurationError("unsupported operating system")


def default_state_path(
    platform: PlatformIdentity,
    *,
    environ: Optional[Mapping[str, str]] = None,
    home: Optional[str] = None,
) -> str:
    """Return the platform-native per-user cold-state path as text.

    Text is used rather than a foreign-platform ``Path`` so installers can plan
    Windows configuration while executing on another platform.
    """

    raw_env = os.environ if environ is None else environ
    env = _casefold_environment(raw_env)
    override = env.get(STATE_OVERRIDE_ENV.upper())
    if override:
        return validate_state_path(override, platform)

    if platform.os == "windows":
        base = env.get("LOCALAPPDATA")
        if not base:
            home_value = home or env.get("USERPROFILE") or env.get("HOME")
            if not home_value:
                raise PlatformConfigurationError("Windows state placement requires LOCALAPPDATA or a user home")
            base = ntpath.join(home_value, "AppData", "Local")
        return validate_state_path(ntpath.join(base, "HolySkills", "DeliveryEfficiency"), platform)

    home_value = home or env.get("HOME")
    if not home_value:
        try:
            home_value = str(Path.home())
        except RuntimeError as exc:
            raise PlatformConfigurationError("state placement requires a user home") from exc
    if platform.os == "macos":
        return validate_state_path(
            posixpath.join(home_value, "Library", "Application Support", "HolySkills", "DeliveryEfficiency"),
            platform,
        )
    if platform.os == "linux":
        xdg_state = env.get("XDG_STATE_HOME")
        # The XDG base-directory specification requires an absolute value;
        # relative values are ignored rather than treated as an invalid
        # explicit recorder override.
        base = xdg_state if xdg_state and posixpath.isabs(xdg_state) else posixpath.join(home_value, ".local", "state")
        return validate_state_path(posixpath.join(base, "holyskills", "delivery-efficiency"), platform)
    raise PlatformConfigurationError("unsupported platform identity")


def validate_state_path(path: str, platform: PlatformIdentity) -> str:
    """Validate and normalize a state path without touching the filesystem."""

    if not isinstance(path, str) or not path or "\x00" in path or len(path.encode("utf-8")) > 4096:
        raise PlatformConfigurationError("state path is empty or exceeds its safe bound")
    if platform.os == "windows":
        normalized = ntpath.normpath(path)
        if not ntpath.isabs(normalized):
            raise PlatformConfigurationError("Windows state path must be absolute")
        folded = normalized.replace("/", "\\").casefold()
        if folded.startswith("\\\\?\\unc\\") or (
            folded.startswith("\\\\") and not folded.startswith("\\\\?\\")
        ):
            raise PlatformConfigurationError(
                "Windows recorder state must not use a UNC or network path"
            )
        drive, _tail = ntpath.splitdrive(normalized)
        if not drive:
            raise PlatformConfigurationError(
                "Windows state path must identify an absolute local drive"
            )
        return normalized
    normalized = posixpath.normpath(path)
    if not posixpath.isabs(normalized):
        raise PlatformConfigurationError("state path must be absolute")
    if platform.environment == "wsl" and _is_wsl_mounted_path(normalized):
        raise PlatformConfigurationError("WSL recorder state must not use /mnt-backed storage")
    return normalized


def state_directory(path: Optional[Path] = None) -> Path:
    """Resolve a concrete state directory on a confirmed local filesystem."""

    identity = detect_platform()
    if path is None:
        selected = default_state_path(identity)
    else:
        selected = validate_state_path(str(path), identity)
    concrete = Path(selected).expanduser()
    resolved = concrete.resolve(strict=False) if identity.os != "windows" else concrete
    if identity.environment == "wsl":
        # A lexical safe path may still traverse a symlink onto DrvFS.
        validate_state_path(str(resolved), identity)
    _validate_local_state_filesystem(str(resolved), identity)
    return concrete


def _decode_mountinfo_field(value: str) -> str:
    """Decode the octal escapes specified for proc mount-table path fields."""

    def replace(match: "re.Match[str]") -> str:
        return chr(int(match.group(1), 8))

    return re.sub(r"\\([0-7]{3})", replace, value)


def _parse_linux_mountinfo(raw: str) -> List[_LinuxMount]:
    mounts: List[_LinuxMount] = []
    for line in raw.splitlines():
        fields = line.split()
        try:
            separator = fields.index("-")
        except ValueError:
            continue
        if separator < 6 or len(fields) < separator + 4:
            continue
        mounts.append(
            _LinuxMount(
                mount_point=posixpath.normpath(_decode_mountinfo_field(fields[4])),
                filesystem_type=fields[separator + 1].casefold(),
                source=_decode_mountinfo_field(fields[separator + 2]),
                mount_options=fields[5],
                super_options=fields[separator + 3],
            )
        )
    return mounts


def _linux_mount_for_path(path: str, raw: str) -> Optional[_LinuxMount]:
    normalized = posixpath.normpath(path)
    selected: Optional[_LinuxMount] = None
    selected_length = -1
    for mount in _parse_linux_mountinfo(raw):
        point = mount.mount_point
        contains = point == "/" or normalized == point or normalized.startswith(point.rstrip("/") + "/")
        if contains and len(point) >= selected_length:
            selected = mount
            selected_length = len(point)
    return selected


def _read_linux_mountinfo() -> str:
    try:
        with open("/proc/self/mountinfo", "r", encoding="utf-8", errors="strict") as stream:
            return stream.read(4 * 1024 * 1024 + 1)
    except (OSError, UnicodeError) as error:
        raise PlatformConfigurationError(
            "Linux mount evidence is unavailable; recorder state locality is unknown"
        ) from error


def _windows_drive_type(path: str) -> int:
    if os.name != "nt":
        raise PlatformConfigurationError(
            "Windows drive evidence is unavailable on this host"
        )
    drive, _tail = ntpath.splitdrive(path)
    if not drive:
        raise PlatformConfigurationError("Windows state path has no drive root")
    root = drive.rstrip("\\/") + "\\"
    try:
        function = ctypes.windll.kernel32.GetDriveTypeW
        function.argtypes = [ctypes.c_wchar_p]
        function.restype = ctypes.c_uint
        return int(function(root))
    except (AttributeError, OSError) as error:
        raise PlatformConfigurationError(
            "Windows drive evidence is unavailable"
        ) from error


class _DarwinStatFs(ctypes.Structure):
    _fields_ = [
        ("f_bsize", ctypes.c_uint32),
        ("f_iosize", ctypes.c_int32),
        ("f_blocks", ctypes.c_uint64),
        ("f_bfree", ctypes.c_uint64),
        ("f_bavail", ctypes.c_uint64),
        ("f_files", ctypes.c_uint64),
        ("f_ffree", ctypes.c_uint64),
        ("f_fsid", ctypes.c_int32 * 2),
        ("f_owner", ctypes.c_uint32),
        ("f_type", ctypes.c_uint32),
        ("f_flags", ctypes.c_uint32),
        ("f_fssubtype", ctypes.c_uint32),
        ("f_fstypename", ctypes.c_char * 16),
        ("f_mntonname", ctypes.c_char * 1024),
        ("f_mntfromname", ctypes.c_char * 1024),
        ("f_flags_ext", ctypes.c_uint32),
        ("f_reserved", ctypes.c_uint32 * 7),
    ]


def _existing_ancestor(path: Path) -> Path:
    candidate = path
    while not candidate.exists():
        parent = candidate.parent
        if parent == candidate:
            raise PlatformConfigurationError(
                "no existing ancestor can establish state filesystem locality"
            )
        candidate = parent
    return candidate


def _darwin_mount_flags(path: str) -> int:
    if platform_module.system().strip().lower() != "darwin":
        raise PlatformConfigurationError(
            "macOS mount evidence is unavailable on this host"
        )
    buffer = _DarwinStatFs()
    function = ctypes.CDLL(None, use_errno=True).statfs
    function.argtypes = [ctypes.c_char_p, ctypes.POINTER(_DarwinStatFs)]
    function.restype = ctypes.c_int
    existing = _existing_ancestor(Path(path))
    if function(os.fsencode(str(existing)), ctypes.byref(buffer)) != 0:
        error_number = ctypes.get_errno()
        raise PlatformConfigurationError(
            "macOS mount evidence is unavailable: {}".format(os.strerror(error_number))
        )
    return int(buffer.f_flags)


def _validate_local_state_filesystem(
    path: str,
    platform: PlatformIdentity,
    *,
    linux_mountinfo: Optional[str] = None,
    windows_drive_type: Optional[int] = None,
    darwin_mount_flags: Optional[int] = None,
) -> None:
    """Fail closed unless platform evidence confirms SQLite-WAL-local storage.

    The optional evidence values exist for deterministic cross-platform
    fixtures. Production callers omit them and use only host-owned evidence.
    """

    if platform.os == "windows":
        normalized = validate_state_path(path, platform)
        observed = _windows_drive_type(normalized) if windows_drive_type is None else windows_drive_type
        if observed not in _WINDOWS_LOCAL_DRIVE_TYPES:
            raise PlatformConfigurationError(
                "Windows recorder state must use a confirmed fixed local drive"
            )
        return
    if platform.os == "macos":
        observed_flags = _darwin_mount_flags(path) if darwin_mount_flags is None else darwin_mount_flags
        if observed_flags & _DARWIN_MNT_LOCAL == 0:
            raise PlatformConfigurationError(
                "macOS recorder state must use a confirmed local filesystem"
            )
        return
    if platform.os != "linux":
        raise PlatformConfigurationError("unsupported platform identity")

    raw = _read_linux_mountinfo() if linux_mountinfo is None else linux_mountinfo
    if len(raw.encode("utf-8")) > 4 * 1024 * 1024:
        raise PlatformConfigurationError("Linux mount evidence exceeds its safe bound")
    mount = _linux_mount_for_path(path, raw)
    if mount is None:
        raise PlatformConfigurationError(
            "Linux mount evidence does not identify the state filesystem"
        )
    evidence = " ".join(
        (mount.filesystem_type, mount.source, mount.mount_options, mount.super_options)
    ).casefold()
    if platform.environment == "wsl" and (
        mount.filesystem_type in {"9p", "drvfs"} or "drvfs" in evidence
    ):
        raise PlatformConfigurationError(
            "WSL DrvFS state is not a local filesystem suitable for SQLite WAL"
        )
    if mount.filesystem_type in _LINUX_VOLATILE_FILESYSTEMS:
        raise PlatformConfigurationError(
            "Linux recorder state must use a durable local filesystem, not RAM-backed storage"
        )
    if mount.filesystem_type in _LINUX_LOCAL_FILESYSTEMS:
        return
    if (
        mount.filesystem_type in _LINUX_REMOTE_FILESYSTEMS
        or mount.filesystem_type.startswith("fuse.")
    ):
        raise PlatformConfigurationError(
            "Linux recorder state must use a local filesystem suitable for SQLite WAL"
        )
    raise PlatformConfigurationError(
        "Linux filesystem type {!r} is not recognized as local; refusing unknown state storage".format(
            mount.filesystem_type
        )
    )


def _is_wsl_mounted_path(path: str) -> bool:
    normalized = path.replace("\\", "/").rstrip("/").lower()
    return normalized == "/mnt" or normalized.startswith("/mnt/")


def _casefold_environment(environ: Mapping[str, str]):
    # Windows environment names are case-insensitive.  Applying the same
    # normalization everywhere makes injected platform tests deterministic.
    return {str(key).upper(): str(value) for key, value in environ.items()}
