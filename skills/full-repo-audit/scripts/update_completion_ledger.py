#!/usr/bin/env python3
"""Plan or apply a verified full-repo-audit finding projection to CompletionLedger.md."""

from __future__ import annotations

import argparse
import base64
import ctypes
import errno
import fcntl
import hashlib
import json
import os
import platform
import secrets
import stat
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent
REPO_ROOT = Path(__file__).resolve().parents[3]
VENDOR_ROOT = SCRIPT_DIR / "_vendor"
DEV_SKILL_DIR = (REPO_ROOT / "skills" / "full-repo-audit").resolve()
running_in_dev_repo = DEV_SKILL_DIR == SKILL_DIR.resolve() and (REPO_ROOT / "full_repo_harness").is_dir()
path_roots = [REPO_ROOT, VENDOR_ROOT] if running_in_dev_repo else [VENDOR_ROOT]
for root in reversed([item for item in path_roots if item.is_dir()]):
    root_text = str(root)
    if root_text not in sys.path:
        sys.path.insert(0, root_text)
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from full_repo_harness import completion_ledger, merge_findings  # noqa: E402
import verify_audit_results as audit_verifier  # noqa: E402


LEDGER_NAME = "CompletionLedger.md"
ALLOWED_DISPOSITIONS = {"confirmed", "duplicate", "hypothesis", "invalid", "out_of_scope"}
IMMUTABLE_CANDIDATE_FIELDS = (
    "candidate_id",
    "priority",
    "summary",
    "files",
    "evidence",
    "expected_behavior",
    "gap",
    "suggested_direction",
    "source_reports",
)
LEDGER_ROW_KEYS = {"id", "remaining_work", "why_it_matters", "status", "verification"}
PROJECTION_KEYS = {
    "schema_version",
    "run_id",
    "repo_root",
    "manifest_sha256",
    "consolidated_findings_sha256",
    "review_status",
    "review_instructions",
    "candidates",
}
CANDIDATE_KEYS = {
    *IMMUTABLE_CANDIDATE_FIELDS,
    "disposition",
    "disposition_reason",
    "ledger_row",
}
VERIFIER_INFORMATION_KEYS = {
    "expected_count",
    "reported_count",
    "expected_batch_count",
    "report_files",
    "effort_ledger_provenance_note",
    "effort_verification_scope",
    "lead_reconciliation_contract_count",
    "current_hash_check_skipped",
    "ok",
}


class UpdateError(ValueError):
    """Raised when the audit projection cannot be safely planned or applied."""


class PublicationUncertainError(UpdateError):
    """Raised when a publication error cannot be rolled back without risking data loss."""


@dataclass(frozen=True)
class LedgerSnapshot:
    rows: tuple[completion_ledger.LedgerRow, ...]
    data: bytes | None
    sha256: str | None
    mode: int
    identity: dict[str, int] | None
    metadata: dict | None = None


@dataclass
class FileGuard:
    """A no-follow file snapshot whose descriptor stays open through publication."""

    path: Path
    label: str
    descriptor: int
    parent_descriptor: int
    parent_identity: tuple[int, int]
    parent_metadata: dict[str, int]
    name: str
    data: bytes
    sha256: str
    identity: dict[str, int]
    monitor_parent_metadata: bool = True

    def validate(self) -> None:
        current_parent = open_directory(self.path.parent, label=f"{self.label} parent")
        try:
            parent_stat = os.fstat(current_parent)
            if (parent_stat.st_dev, parent_stat.st_ino) != self.parent_identity:
                raise UpdateError(f"{self.label} parent path changed during apply: {self.path.parent}")
        finally:
            os.close(current_parent)
        if (
            self.monitor_parent_metadata
            and stat_identity(os.fstat(self.parent_descriptor)) != self.parent_metadata
        ):
            raise UpdateError(f"{self.label} parent changed during apply: {self.path.parent}")
        try:
            path_stat = os.stat(self.name, dir_fd=self.parent_descriptor, follow_symlinks=False)
        except FileNotFoundError as exc:
            raise UpdateError(f"{self.label} disappeared during apply: {self.path}") from exc
        if not stat.S_ISREG(path_stat.st_mode):
            raise UpdateError(f"{self.label} is no longer a regular file: {self.path}")
        if (path_stat.st_dev, path_stat.st_ino) != (
            self.identity["device"],
            self.identity["inode"],
        ):
            raise UpdateError(f"{self.label} was replaced during apply: {self.path}")
        data, identity = read_descriptor_stable(self.descriptor, self.path, self.label)
        if identity != self.identity or sha256_bytes(data) != self.sha256:
            raise UpdateError(f"{self.label} changed during apply: {self.path}")
        final_path_stat = os.stat(self.name, dir_fd=self.parent_descriptor, follow_symlinks=False)
        if not stat.S_ISREG(final_path_stat.st_mode) or stat_identity(final_path_stat) != self.identity:
            raise UpdateError(f"{self.label} was replaced during apply: {self.path}")
        validate_directory_binding(
            self.path.parent,
            self.parent_descriptor,
            f"{self.label} parent",
        )

    def finish_verification(self) -> None:
        self.monitor_parent_metadata = False

    def close(self) -> None:
        os.close(self.descriptor)
        os.close(self.parent_descriptor)


@dataclass
class AbsentFileGuard:
    """A path proven absent whose parent metadata catches create/delete ABA."""

    path: Path
    label: str
    parent_descriptor: int
    parent_identity: dict[str, int]
    name: str
    monitor_parent_identity: bool = True

    def validate(self) -> None:
        validate_directory_binding(self.path.parent, self.parent_descriptor, f"{self.label} parent")
        current_parent = stat_identity(os.fstat(self.parent_descriptor))
        if self.monitor_parent_identity and current_parent != self.parent_identity:
            raise UpdateError(
                f"{self.label} parent changed while absence was relied upon: {self.path.parent}"
            )
        try:
            os.stat(self.name, dir_fd=self.parent_descriptor, follow_symlinks=False)
        except FileNotFoundError:
            return
        raise UpdateError(f"{self.label} appeared during apply: {self.path}")

    def finish_verification(self) -> None:
        self.monitor_parent_identity = False

    def close(self) -> None:
        os.close(self.parent_descriptor)


@dataclass
class DirectoryGuard:
    """An open directory snapshot used to bind verifier path resolution."""

    path: Path
    label: str
    descriptor: int
    identity: dict[str, int]
    monitor_metadata: bool = True

    def validate(self) -> None:
        validate_directory_binding(self.path, self.descriptor, self.label)
        if self.monitor_metadata and stat_identity(os.fstat(self.descriptor)) != self.identity:
            raise UpdateError(f"{self.label} changed while audit verification was running: {self.path}")

    def finish_verification(self) -> None:
        self.monitor_metadata = False

    def close(self) -> None:
        os.close(self.descriptor)


EvidenceGuard = FileGuard | AbsentFileGuard | DirectoryGuard


@dataclass
class EvidenceBundle:
    """Exact audit inputs held open while a plan is derived or applied."""

    guards: list[EvidenceGuard]
    manifest_guard: FileGuard
    projection_guard: FileGuard
    receipt_guard: FileGuard
    report_guards: dict[str, FileGuard]
    source_guards: dict[str, FileGuard]
    companion_guards: dict[str, EvidenceGuard]
    manifest: dict
    projection: dict
    receipt: dict
    report_names: list[str]
    ignored_report_names: list[str]
    verification_mode: str
    verifier_result_sha256: str

    def close(self) -> None:
        for guard in reversed(self.guards):
            guard.close()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def lexical_absolute(path: Path) -> Path:
    expanded = path.expanduser()
    if ".." in expanded.parts:
        raise UpdateError(f"refusing path with parent traversal component: {path}")
    return Path(os.path.abspath(os.fspath(expanded)))


def safe_relative_path(root: Path, relative: str, label: str) -> Path:
    candidate = Path(relative)
    if (
        not relative
        or candidate.is_absolute()
        or any(part in {"", ".", ".."} for part in candidate.parts)
    ):
        raise UpdateError(f"{label} path must be a normalized relative path within its root: {relative!r}")
    return lexical_absolute(root) / candidate


def open_directory(path: Path, *, label: str = "directory") -> int:
    """Open every directory component without following symlinks."""

    absolute = lexical_absolute(path)
    flags = (
        os.O_RDONLY
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    try:
        descriptor = os.open(absolute.anchor, flags)
    except OSError as exc:
        raise UpdateError(f"could not open {label} root {absolute.anchor}: {exc}") from exc
    try:
        for component in absolute.parts[1:]:
            try:
                next_descriptor = os.open(component, flags, dir_fd=descriptor)
            except OSError as exc:
                if exc.errno in {errno.ELOOP, errno.ENOTDIR}:
                    raise UpdateError(
                        f"refusing {label} through symlinked path component or non-directory: {absolute}"
                    ) from exc
                raise UpdateError(f"could not open {label} {absolute}: {exc}") from exc
            os.close(descriptor)
            descriptor = next_descriptor
        return descriptor
    except Exception:
        os.close(descriptor)
        raise


def read_descriptor_stable(descriptor: int, path: Path, label: str) -> tuple[bytes, dict[str, int]]:
    before = os.fstat(descriptor)
    if not stat.S_ISREG(before.st_mode):
        raise UpdateError(f"{label} is not a regular file: {path}")
    os.lseek(descriptor, 0, os.SEEK_SET)
    chunks: list[bytes] = []
    while True:
        chunk = os.read(descriptor, 1024 * 1024)
        if not chunk:
            break
        chunks.append(chunk)
    after = os.fstat(descriptor)
    if stat_identity(before) != stat_identity(after):
        raise UpdateError(f"{label} changed while it was being read: {path}")
    return b"".join(chunks), stat_identity(after)


def open_file_guard(path: Path, label: str) -> FileGuard:
    absolute = lexical_absolute(path)
    parent_descriptor = open_directory(absolute.parent, label=f"{label} parent")
    flags = (
        os.O_RDONLY
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NONBLOCK", 0)
    )
    try:
        try:
            descriptor = os.open(absolute.name, flags, dir_fd=parent_descriptor)
        except OSError as exc:
            if exc.errno in {errno.ELOOP, errno.ENOTDIR}:
                raise UpdateError(f"refusing symlinked {label}: {absolute}") from exc
            raise UpdateError(f"could not open {label} {absolute}: {exc}") from exc
        try:
            data, identity = read_descriptor_stable(descriptor, absolute, label)
            path_stat = os.stat(absolute.name, dir_fd=parent_descriptor, follow_symlinks=False)
            if not stat.S_ISREG(path_stat.st_mode) or (path_stat.st_dev, path_stat.st_ino) != (
                identity["device"],
                identity["inode"],
            ):
                raise UpdateError(f"{label} was replaced while it was being opened: {absolute}")
            parent_stat = os.fstat(parent_descriptor)
            return FileGuard(
                path=absolute,
                label=label,
                descriptor=descriptor,
                parent_descriptor=parent_descriptor,
                parent_identity=(parent_stat.st_dev, parent_stat.st_ino),
                parent_metadata=stat_identity(parent_stat),
                name=absolute.name,
                data=data,
                sha256=sha256_bytes(data),
                identity=identity,
            )
        except Exception:
            os.close(descriptor)
            raise
    except Exception:
        os.close(parent_descriptor)
        raise


def open_directory_guard(path: Path, label: str) -> DirectoryGuard:
    absolute = lexical_absolute(path)
    descriptor = open_directory(absolute, label=label)
    return DirectoryGuard(
        path=absolute,
        label=label,
        descriptor=descriptor,
        identity=stat_identity(os.fstat(descriptor)),
    )


def open_optional_file_guard(path: Path, label: str) -> EvidenceGuard:
    """Snapshot an existing regular file or bind its absence without following links."""

    absolute = lexical_absolute(path)
    parent_descriptor = open_directory(absolute.parent, label=f"{label} parent")
    try:
        try:
            os.stat(absolute.name, dir_fd=parent_descriptor, follow_symlinks=False)
        except FileNotFoundError:
            return AbsentFileGuard(
                path=absolute,
                label=label,
                parent_descriptor=parent_descriptor,
                parent_identity=stat_identity(os.fstat(parent_descriptor)),
                name=absolute.name,
            )
    except Exception:
        os.close(parent_descriptor)
        raise
    os.close(parent_descriptor)
    return open_file_guard(absolute, label)


def sha256_file(path: Path) -> str:
    guard = open_file_guard(path, "file")
    try:
        guard.validate()
        return guard.sha256
    finally:
        guard.close()


def parse_json_bytes(data: bytes, path: Path, label: str) -> dict:
    def object_pairs(pairs: list[tuple[str, object]]) -> dict:
        value: dict[str, object] = {}
        for key, item in pairs:
            if key in value:
                raise UpdateError(f"{label} JSON contains duplicate object key {key!r}: {path}")
            value[key] = item
        return value

    def reject_constant(value: str) -> None:
        raise UpdateError(f"{label} JSON contains non-finite number {value!r}: {path}")

    try:
        value = json.loads(
            data.decode("utf-8"),
            object_pairs_hook=object_pairs,
            parse_constant=reject_constant,
        )
    except UpdateError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise UpdateError(f"could not read {label} JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise UpdateError(f"{label} JSON must be an object: {path}")
    return value


def load_json(path: Path, label: str) -> dict:
    guard = open_file_guard(path, label)
    try:
        guard.validate()
        return parse_json_bytes(guard.data, guard.path, label)
    finally:
        guard.close()


def require_exact_keys(value: dict, expected: set[str], label: str) -> None:
    actual = set(value)
    if actual == expected:
        return
    missing = sorted(expected - actual)
    extra = sorted(actual - expected)
    raise UpdateError(f"{label} keys must be exact; missing={missing}, extra={extra}")


def normalized_audit_verification(result: dict) -> tuple[str, dict]:
    """Return the receipt-comparable pass result or reject every real blocker."""

    if result.get("ok") is True:
        return "verified", result
    allowed_ledger_drift = result.get("current_hash_mismatches") or []
    ledger_drift_is_exact = (
        isinstance(allowed_ledger_drift, list)
        and len(allowed_ledger_drift) == 1
        and isinstance(allowed_ledger_drift[0], dict)
        and allowed_ledger_drift[0].get("file") == LEDGER_NAME
        and allowed_ledger_drift[0].get("reason") == "changed"
        and isinstance(allowed_ledger_drift[0].get("expected"), str)
        and isinstance(allowed_ledger_drift[0].get("current"), str)
        and len(allowed_ledger_drift[0]["expected"]) == 64
        and len(allowed_ledger_drift[0]["current"]) == 64
        and all(char in "0123456789abcdef" for char in allowed_ledger_drift[0]["expected"])
        and all(char in "0123456789abcdef" for char in allowed_ledger_drift[0]["current"])
        and allowed_ledger_drift[0]["expected"] != allowed_ledger_drift[0]["current"]
    )
    if ledger_drift_is_exact:
        blocking = {
            key: value
            for key, value in result.items()
            if key not in VERIFIER_INFORMATION_KEYS
            and key != "current_hash_mismatches"
            and bool(value)
        }
        if not blocking:
            normalized = dict(result)
            normalized["current_hash_mismatches"] = []
            normalized["ok"] = True
            return "verified-post-ledger-only-drift", normalized
    raise UpdateError("audit verifier did not pass; refusing completion-ledger projection")


def audit_verification_mode(
    manifest_path: Path,
    report_paths: list[Path],
    receipt: dict,
) -> tuple[str, str]:
    """Rerun the verifier and bind its genuine pass result to the held receipt."""

    try:
        result = audit_verifier.verify(
            manifest_path,
            sorted(report_paths),
            skip_current_hash_check=False,
        )
    except (OSError, ValueError) as exc:
        raise UpdateError(f"audit verifier could not validate held evidence: {exc}") from exc
    mode, receipt_comparable_result = normalized_audit_verification(result)
    observed_digest = audit_verifier.canonical_json_sha256(receipt_comparable_result)
    if observed_digest != receipt.get("verifier_result_sha256"):
        raise UpdateError(
            "audit verifier result does not match the pass-only verification receipt"
        )
    return mode, observed_digest


def expected_projection(
    manifest_path: Path,
    reports_dir: Path,
    manifest: dict,
    report_names: list[str],
) -> tuple[dict, dict]:
    consolidated = merge_findings.merge_findings(reports_dir, report_names=report_names)
    projection = merge_findings.render_completion_ledger_projection(
        consolidated,
        run_id=manifest["run_id"],
        repo_root=manifest["repo_root"],
        manifest_sha256=sha256_file(manifest_path),
    )
    return consolidated, projection


def authorized_report_names(manifest: dict) -> list[str]:
    try:
        return merge_findings.manifest_report_names(manifest)
    except ValueError as exc:
        raise UpdateError(f"audit manifest report allowlist is invalid: {exc}") from exc


def snapshot_report_sha256(reports_dir: Path, report_names: list[str]) -> dict[str, str]:
    hashes: dict[str, str] = {}
    for name in report_names:
        report_path = safe_relative_path(reports_dir, name, "verified report")
        try:
            hashes[name] = sha256_file(report_path)
        except UpdateError as exc:
            raise UpdateError(f"required verified report is unavailable or unsafe: {name}: {exc}") from exc
    return hashes


def row_from_projection(candidate: dict) -> completion_ledger.LedgerRow:
    raw = candidate.get("ledger_row")
    if not isinstance(raw, dict):
        raise UpdateError(f"confirmed candidate {candidate.get('candidate_id')} requires ledger_row")
    require_exact_keys(raw, LEDGER_ROW_KEYS, f"candidate {candidate.get('candidate_id')} ledger_row")
    if not all(isinstance(raw[key], str) for key in LEDGER_ROW_KEYS):
        raise UpdateError(f"confirmed candidate {candidate.get('candidate_id')} ledger_row values must be strings")
    row = completion_ledger.LedgerRow(
        id=raw["id"],
        remaining_work=raw["remaining_work"],
        why_it_matters=raw["why_it_matters"],
        status=raw["status"],
        verification=raw["verification"],
    )
    completion_ledger.validate_rows([row])
    for field in ("remaining_work", "why_it_matters", "verification"):
        if len(getattr(row, field).strip()) < 12:
            raise UpdateError(f"confirmed candidate {candidate.get('candidate_id')} has underspecified {field}")
    priority = candidate.get("priority")
    if f"[{priority}]" not in row.remaining_work:
        raise UpdateError(f"confirmed candidate {candidate.get('candidate_id')} remaining_work must include [{priority}]")
    files = candidate.get("files") or []
    if files and not all(path in row.remaining_work for path in files):
        raise UpdateError(
            f"confirmed candidate {candidate.get('candidate_id')} remaining_work must name every affected file"
        )
    expected_id = candidate.get("candidate_id", "").replace("FRA-C-", "FRA-", 1)
    if row.id != expected_id:
        raise UpdateError(
            f"confirmed candidate {candidate.get('candidate_id')} must use stable ledger id {expected_id}"
        )
    if row.status.casefold().startswith("blocked") and len(row.status.strip()) < 12:
        raise UpdateError(f"blocked ledger row {row.id} must name its unblock condition")
    return row


def validate_projection(
    projection: dict,
    expected: dict,
    consolidated: dict,
) -> list[dict]:
    require_exact_keys(projection, PROJECTION_KEYS, "completion-ledger projection")
    if projection.get("schema_version") != 1:
        raise UpdateError("completion-ledger projection schema_version must be 1")
    for field in ("run_id", "repo_root", "manifest_sha256", "consolidated_findings_sha256"):
        if projection.get(field) != expected.get(field):
            raise UpdateError(f"completion-ledger projection {field} does not match verified audit evidence")
    if projection.get("review_status") != "complete":
        raise UpdateError("completion-ledger projection review_status must be complete")
    if projection.get("review_instructions") != expected.get("review_instructions"):
        raise UpdateError("completion-ledger projection review_instructions do not match the generated contract")
    candidates = projection.get("candidates")
    if not isinstance(candidates, list):
        raise UpdateError("completion-ledger projection candidates must be a list")
    for index, candidate in enumerate(candidates):
        if not isinstance(candidate, dict):
            raise UpdateError(f"completion-ledger projection candidate {index} must be an object")
        require_exact_keys(candidate, CANDIDATE_KEYS, f"completion-ledger projection candidate {index}")
        raw_row = candidate.get("ledger_row")
        if not isinstance(raw_row, dict):
            raise UpdateError(f"completion-ledger projection candidate {index} ledger_row must be an object")
        require_exact_keys(raw_row, LEDGER_ROW_KEYS, f"completion-ledger projection candidate {index} ledger_row")
        if not all(isinstance(raw_row[key], str) for key in LEDGER_ROW_KEYS):
            raise UpdateError(f"completion-ledger projection candidate {index} ledger_row values must be strings")
    expected_candidates = {item["candidate_id"]: item for item in expected["candidates"]}
    observed_ids = [item.get("candidate_id") for item in candidates]
    if any(not isinstance(item, str) for item in observed_ids) or len(set(observed_ids)) != len(observed_ids):
        raise UpdateError("completion-ledger projection candidate IDs must be unique strings")
    if set(observed_ids) != set(expected_candidates):
        raise UpdateError("completion-ledger projection must dispose every consolidated finding exactly once")
    if projection["consolidated_findings_sha256"] != merge_findings.canonical_json_sha256(consolidated):
        raise UpdateError("completion-ledger projection consolidated findings digest is stale")

    for candidate in candidates:
        expected_candidate = expected_candidates[candidate["candidate_id"]]
        for field in IMMUTABLE_CANDIDATE_FIELDS:
            if candidate.get(field) != expected_candidate.get(field):
                raise UpdateError(
                    f"completion-ledger projection candidate {candidate['candidate_id']} changed immutable field {field}"
                )
        disposition = candidate.get("disposition")
        reason = candidate.get("disposition_reason")
        if disposition not in ALLOWED_DISPOSITIONS:
            raise UpdateError(
                f"completion-ledger projection candidate {candidate['candidate_id']} has invalid disposition {disposition!r}"
            )
        if not isinstance(reason, str) or len(reason.strip()) < 12:
            raise UpdateError(
                f"completion-ledger projection candidate {candidate['candidate_id']} disposition {disposition} requires a concrete reason"
            )
        if disposition == "confirmed":
            row_from_projection(candidate)
    return candidates


def stat_identity(value: os.stat_result) -> dict[str, int]:
    return {
        "device": value.st_dev,
        "inode": value.st_ino,
        "size": value.st_size,
        "mtime_ns": value.st_mtime_ns,
        "ctime_ns": value.st_ctime_ns,
        "mode": value.st_mode,
    }


def exchange_identity_matches(observed: dict[str, int], expected: dict[str, int]) -> bool:
    """Compare immutable/content metadata; some filesystems touch ctime on name exchange."""

    return all(
        observed.get(key) == expected.get(key)
        for key in ("device", "inode", "size", "mtime_ns", "mode")
    )


def descriptor_metadata(descriptor: int) -> dict:
    value = os.fstat(descriptor)
    try:
        names = sorted(os.listxattr(descriptor))
        xattrs = {
            name: base64.b64encode(os.getxattr(descriptor, name)).decode("ascii")
            for name in names
        }
    except OSError as exc:
        raise UpdateError(f"could not snapshot CompletionLedger.md extended attributes: {exc}") from exc
    return {
        "uid": value.st_uid,
        "gid": value.st_gid,
        "mode": stat.S_IMODE(value.st_mode),
        "xattrs_base64": xattrs,
    }


def apply_descriptor_metadata(descriptor: int, metadata: dict | None) -> None:
    if metadata is None:
        return
    try:
        os.fchown(descriptor, metadata["uid"], metadata["gid"])
        os.fchmod(descriptor, metadata["mode"])
        expected_xattrs = metadata["xattrs_base64"]
        for name in os.listxattr(descriptor):
            if name not in expected_xattrs:
                os.removexattr(descriptor, name)
        for name, encoded in expected_xattrs.items():
            os.setxattr(descriptor, name, base64.b64decode(encoded, validate=True))
    except (KeyError, TypeError, ValueError, OSError) as exc:
        raise UpdateError(f"could not preserve CompletionLedger.md ownership, mode, ACLs, or xattrs: {exc}") from exc
    if descriptor_metadata(descriptor) != metadata:
        raise UpdateError("temporary CompletionLedger.md metadata does not match the existing ledger")


def read_existing_ledger(repo: Path, *, directory_fd: int | None = None) -> LedgerSnapshot:
    path = repo / LEDGER_NAME
    owned_directory_fd = directory_fd is None
    if directory_fd is None:
        try:
            directory_fd = open_directory(repo, label="repository")
        except OSError as exc:
            raise UpdateError(f"could not open repository directory {repo}: {exc}") from exc
    assert directory_fd is not None
    try:
        try:
            data, identity, metadata = named_file_snapshot(
                directory_fd, LEDGER_NAME, "completion ledger"
            )
        except FileNotFoundError:
            return LedgerSnapshot((), None, None, 0o664, None)
        except OSError as exc:
            if exc.errno == errno.ELOOP:
                raise UpdateError(f"refusing symlinked completion ledger: {path}") from exc
            raise UpdateError(f"could not open completion ledger {path}: {exc}") from exc
        try:
            rows = completion_ledger.parse_ledger(data.decode("utf-8"))
        except (UnicodeDecodeError, completion_ledger.LedgerError) as exc:
            raise UpdateError(f"existing completion ledger is invalid: {exc}") from exc
        return LedgerSnapshot(
            tuple(rows),
            data,
            sha256_bytes(data),
            stat.S_IMODE(identity["mode"]),
            identity,
            metadata,
        )
    finally:
        if owned_directory_fd:
            os.close(directory_fd)


def reconcile_rows(
    existing_rows: list[completion_ledger.LedgerRow],
    candidates: list[dict],
) -> tuple[list[completion_ledger.LedgerRow], dict]:
    existing_by_id = {row.id: row for row in existing_rows}
    existing_by_folded_id = {row.id.casefold(): row for row in existing_rows}
    confirmed: dict[str, completion_ledger.LedgerRow] = {}
    already_present: set[str] = set()
    for candidate in candidates:
        if candidate["disposition"] != "confirmed":
            continue
        row = row_from_projection(candidate)
        collision = existing_by_folded_id.get(row.id.casefold())
        if collision is not None:
            if collision == row:
                already_present.add(row.id)
                continue
            raise UpdateError(
                f"completion-ledger ID collision for {row.id}; preserve the existing row and mark the candidate duplicate"
            )
        if row.id in confirmed:
            raise UpdateError(f"multiple confirmed candidates map to completion-ledger ID {row.id}")
        confirmed[row.id] = row
    known_ids = set(existing_by_id) | set(confirmed)
    for candidate in candidates:
        if candidate["disposition"] == "duplicate":
            ledger_id = candidate.get("ledger_row", {}).get("id")
            if not isinstance(ledger_id, str) or ledger_id not in known_ids:
                raise UpdateError(
                    f"duplicate candidate {candidate['candidate_id']} must name an existing or confirmed ledger_row.id"
                )

    final_rows = list(existing_rows)
    added: list[str] = []
    preserved = [row.id for row in existing_rows]
    for candidate in candidates:
        raw_id = candidate.get("ledger_row", {}).get("id") if candidate.get("disposition") == "confirmed" else None
        if raw_id in confirmed:
            final_rows.append(confirmed.pop(raw_id))
            added.append(raw_id)
    if confirmed:
        raise UpdateError(f"unreconciled confirmed ledger rows: {sorted(confirmed)}")
    completion_ledger.validate_rows(final_rows, allow_empty=True)
    dispositions = {name: 0 for name in sorted(ALLOWED_DISPOSITIONS)}
    mappings = []
    for candidate in candidates:
        disposition = candidate["disposition"]
        dispositions[disposition] += 1
        mappings.append(
            {
                "candidate_id": candidate["candidate_id"],
                "disposition": disposition,
                "ledger_id": candidate.get("ledger_row", {}).get("id") if disposition in {"confirmed", "duplicate"} else None,
            }
        )
    return final_rows, {
        "added_ids": added,
        "updated_ids": [],
        "preserved_ids": preserved,
        "already_present_ids": sorted(already_present),
        "disposition_counts": dispositions,
        "candidate_mapping": mappings,
    }


def render_after_content(
    snapshot: LedgerSnapshot,
    final_rows: list[completion_ledger.LedgerRow],
    added_ids: list[str],
) -> str | None:
    if snapshot.data is None:
        return completion_ledger.render_ledger(final_rows) if final_rows else None
    existing_text = snapshot.data.decode("utf-8")
    if not added_ids:
        return existing_text
    added = set(added_ids)
    appended_rows = [row for row in final_rows if row.id in added]
    if len(appended_rows) != len(added_ids):
        raise UpdateError("completion-ledger append set does not match the reviewed reconciliation")
    first_newline = existing_text.find("\n")
    newline = "\r\n" if first_newline > 0 and existing_text[first_newline - 1] == "\r" else "\n"
    separator = "" if existing_text.endswith(("\n", "\r")) else newline
    result = (
        existing_text
        + separator
        + newline.join(completion_ledger.render_row(row) for row in appended_rows)
        + newline
    )
    if completion_ledger.parse_ledger(result) != final_rows:
        raise UpdateError("completion-ledger append did not preserve the reviewed row set")
    return result


def ignored_markdown_reports(reports_dir: Path, report_names: list[str]) -> list[str]:
    """Snapshot direct unverified Markdown names for an informational plan field."""

    directory_fd = open_directory(reports_dir, label="reports directory")
    try:
        ignored: list[str] = []
        allowed = set(report_names)
        for name in os.listdir(directory_fd):
            if not isinstance(name, str) or not name.endswith(".md") or name in allowed:
                continue
            try:
                value = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
            except FileNotFoundError:
                continue
            if stat.S_ISREG(value.st_mode):
                ignored.append(name)
        return sorted(ignored)
    finally:
        os.close(directory_fd)


def open_verifier_companion_guards(
    *,
    repo: Path,
    manifest_path: Path,
    manifest: dict,
    guards: list[EvidenceGuard],
) -> tuple[dict[str, EvidenceGuard], list[EvidenceGuard]]:
    """Bind every non-report path the audit verifier can inspect.

    The returned verification-only guards cover the current completion ledger:
    the verifier must see one stable ledger state, but the reviewed apply is
    subsequently allowed to replace or create that exact file.
    """

    audit_root = manifest_path.parent
    companion_guards: dict[str, EvidenceGuard] = {}
    verification_only_guards: list[EvidenceGuard] = []
    guarded_paths = {
        guard.path
        for guard in guards
        if isinstance(guard, (FileGuard, AbsentFileGuard))
    }

    def add_path(path: Path, label: str, *, required: bool = False) -> EvidenceGuard:
        absolute = lexical_absolute(path)
        existing = companion_guards.get(str(absolute))
        if existing is not None:
            return existing
        if absolute in guarded_paths:
            # The path is already held by a manifest/report/source guard.
            return next(
                guard
                for guard in guards
                if isinstance(guard, (FileGuard, AbsentFileGuard)) and guard.path == absolute
            )
        guard = open_file_guard(absolute, label) if required else open_optional_file_guard(absolute, label)
        guards.append(guard)
        companion_guards[str(absolute)] = guard
        guarded_paths.add(absolute)
        return guard

    for name, label in (
        ("queue_complete.json", "audit queue completion marker"),
        ("excluded_files.json", "audit excluded-files record"),
        ("effort_ledger.json", "audit effort ledger"),
    ):
        add_path(audit_root / name, label, required=True)
    add_path(audit_root / "audit_complete.json", "legacy audit completion marker")

    prompt_references: list[str] = []
    for batch in manifest.get("batches", []):
        if isinstance(batch, dict) and isinstance(batch.get("prompt"), str):
            prompt_references.append(batch["prompt"])
    lead = manifest.get("lead_reconciliation")
    if isinstance(lead, dict) and isinstance(lead.get("prompt"), str):
        prompt_references.append(lead["prompt"])
    journey = manifest.get("journey_audit")
    if isinstance(journey, dict):
        for field in audit_verifier.JOURNEY_PROMPT_FIELDS.values():
            value = journey.get(field)
            if isinstance(value, str):
                prompt_references.append(value)

    effort_guard = companion_guards[str(lexical_absolute(audit_root / "effort_ledger.json"))]
    if not isinstance(effort_guard, FileGuard):
        raise UpdateError("audit effort ledger must be a regular file")
    effort = parse_json_bytes(effort_guard.data, effort_guard.path, "audit effort ledger")
    lead_effort = effort.get("lead_reconciliation")
    if isinstance(lead_effort, dict):
        for field in ("prompt", "report"):
            value = lead_effort.get(field)
            if isinstance(value, str):
                prompt_references.append(value)
    for worker_key in ("journey_source_worker", "visual_journey_worker"):
        worker = effort.get(worker_key)
        if isinstance(worker, dict):
            for field in ("prompt", "report"):
                value = worker.get(field)
                if isinstance(value, str):
                    prompt_references.append(value)
    batches = effort.get("batches")
    if isinstance(batches, list):
        for batch in batches:
            if not isinstance(batch, dict):
                continue
            for field in ("prompt", "report"):
                value = batch.get(field)
                if isinstance(value, str):
                    prompt_references.append(value)

    for index, reference in enumerate(dict.fromkeys(prompt_references)):
        referenced_path = safe_relative_path(
            audit_root,
            reference,
            f"verifier companion reference {index}",
        )
        add_path(referenced_path, f"verifier companion reference {reference}")

    visual_guard = add_path(
        audit_root / audit_verifier.audit_evidence.VISUAL_EVIDENCE_FILENAME,
        "visual evidence manifest",
    )
    if isinstance(visual_guard, FileGuard):
        visual = parse_json_bytes(
            visual_guard.data,
            visual_guard.path,
            "visual evidence manifest",
        )
        artifacts = visual.get("artifacts")
        if isinstance(artifacts, list):
            for index, record in enumerate(artifacts):
                if not isinstance(record, dict) or not isinstance(record.get("path"), str):
                    continue
                artifact_path = safe_relative_path(
                    audit_root,
                    record["path"],
                    f"visual evidence artifact {index}",
                )
                add_path(artifact_path, f"visual evidence artifact {index}")

    if any(
        isinstance(item, dict) and item.get("rel_path") == LEDGER_NAME
        for item in manifest.get("source_files", [])
    ):
        ledger_guard = open_optional_file_guard(repo / LEDGER_NAME, "verifier completion ledger source")
        guards.append(ledger_guard)
        verification_only_guards.append(ledger_guard)

    return companion_guards, verification_only_guards


def add_verifier_directory_hierarchy_guards(
    guards: list[EvidenceGuard],
    roots: list[Path],
) -> None:
    """Guard each path-resolution directory so ancestor A/B/A swaps fail closed."""

    existing = {
        guard.path for guard in guards if isinstance(guard, DirectoryGuard)
    }
    file_paths = [
        guard.path
        for guard in guards
        if isinstance(guard, (FileGuard, AbsentFileGuard))
    ]
    for raw_root in dict.fromkeys(lexical_absolute(root) for root in roots):
        if raw_root not in existing:
            guards.append(open_directory_guard(raw_root, f"verifier path root {raw_root}"))
            existing.add(raw_root)
        for file_path in file_paths:
            try:
                relative_parent = file_path.parent.relative_to(raw_root)
            except ValueError:
                continue
            current = raw_root
            for part in relative_parent.parts:
                current /= part
                if current in existing:
                    continue
                guards.append(
                    open_directory_guard(current, f"verifier path directory {current}")
                )
                existing.add(current)


def open_evidence_bundle(
    repo: Path,
    manifest_path: Path,
    reports_dir: Path,
    projection_path: Path,
) -> EvidenceBundle:
    """Open every receipt-bound input once and retain it through plan publication."""

    repo = lexical_absolute(repo)
    manifest_path = lexical_absolute(manifest_path)
    reports_dir = lexical_absolute(reports_dir)
    projection_path = lexical_absolute(projection_path)
    guards: list[EvidenceGuard] = []
    try:
        guards.append(open_directory_guard(repo, "repository"))
        guards.append(open_directory_guard(manifest_path.parent, "audit output directory"))

        manifest_guard = open_file_guard(manifest_path, "audit manifest")
        guards.append(manifest_guard)
        manifest = parse_json_bytes(manifest_guard.data, manifest_guard.path, "manifest")
        manifest_repo = lexical_absolute(Path(str(manifest.get("repo_root", ""))))
        if manifest_repo != repo:
            raise UpdateError("manifest repo_root does not match --repo")
        if manifest_repo != repo:
            raise UpdateError("manifest repository binding changed while opening evidence")

        expected_reports_dir = lexical_absolute(manifest_path.parent / "reports")
        declared_reports = manifest.get("reports_dir")
        if (
            reports_dir != expected_reports_dir
            or not isinstance(declared_reports, str)
            or lexical_absolute(Path(declared_reports)) != reports_dir
        ):
            raise UpdateError(
                "--reports must be the exact manifest-owned reports directory declared by the audit manifest"
            )
        guards.append(open_directory_guard(reports_dir, "reports directory"))

        projection_guard = open_file_guard(projection_path, "completion-ledger projection")
        guards.append(projection_guard)
        projection = parse_json_bytes(
            projection_guard.data,
            projection_guard.path,
            "completion-ledger projection",
        )

        receipt_path = manifest_path.parent / "verification_receipt.json"
        receipt_guard = open_file_guard(receipt_path, "pass-only verification receipt")
        guards.append(receipt_guard)
        receipt = parse_json_bytes(
            receipt_guard.data,
            receipt_guard.path,
            "pass-only verification receipt",
        )

        report_names = authorized_report_names(manifest)
        report_guards: dict[str, FileGuard] = {}
        for name in report_names:
            guard = open_file_guard(
                safe_relative_path(reports_dir, name, "verified report"),
                f"verified report {name}",
            )
            guards.append(guard)
            report_guards[name] = guard

        try:
            receipt_report_hashes = merge_findings.validate_verification_receipt(
                receipt,
                manifest=manifest,
                manifest_sha256=manifest_guard.sha256,
                reports_dir=reports_dir,
                report_names=report_names,
            )
        except ValueError as exc:
            raise UpdateError(f"pass-only verification receipt is invalid: {exc}") from exc
        observed_report_hashes = {
            name: guard.sha256 for name, guard in report_guards.items()
        }
        if receipt_report_hashes != observed_report_hashes:
            raise UpdateError(
                "manifest-authorized reports do not match the pass-only verification receipt"
            )

        source_guards: dict[str, FileGuard] = {}
        for item in manifest.get("source_files", []):
            if not isinstance(item, dict):
                continue
            rel_path = item.get("rel_path")
            expected = item.get("sha256")
            if rel_path == LEDGER_NAME:
                continue
            if not isinstance(rel_path, str) or not rel_path:
                continue
            if not isinstance(expected, str):
                raise UpdateError(
                    f"manifest source {rel_path} lacks the SHA-256 required for receipt-bound freshness"
                )
            guard = open_file_guard(
                safe_relative_path(repo, rel_path, "manifest source"),
                f"manifest source {rel_path}",
            )
            guards.append(guard)
            if guard.sha256 != expected:
                raise UpdateError(f"manifest source changed after pass-only audit verification: {rel_path}")
            source_guards[rel_path] = guard

        companion_guards, verification_only_guards = open_verifier_companion_guards(
            repo=repo,
            manifest_path=manifest_path,
            manifest=manifest,
            guards=guards,
        )
        add_verifier_directory_hierarchy_guards(
            guards,
            [repo, manifest_path.parent],
        )

        verifier_report_names = sorted(
            name
            for name in report_names
            if audit_verifier.REPORT_FILENAME_RE.fullmatch(name)
            or name == audit_verifier.LEAD_RECONCILIATION_REPORT_NAME
        )
        verifier_report_paths = [
            report_guards[name].path for name in verifier_report_names
        ]
        try:
            verification_mode, verifier_result_sha256 = audit_verification_mode(
                manifest_guard.path,
                verifier_report_paths,
                receipt,
            )
        finally:
            # The verifier reads the canonical paths. Revalidate every held
            # descriptor afterward so replacement and A/B/A races cannot make
            # a different manifest, report, or source satisfy the gate.
            validate_guards(guards)
        for guard in guards:
            if isinstance(guard, (FileGuard, AbsentFileGuard, DirectoryGuard)):
                guard.finish_verification()
        for guard in verification_only_guards:
            guards.remove(guard)
            guard.close()
        return EvidenceBundle(
            guards=guards,
            manifest_guard=manifest_guard,
            projection_guard=projection_guard,
            receipt_guard=receipt_guard,
            report_guards=report_guards,
            source_guards=source_guards,
            companion_guards=companion_guards,
            manifest=manifest,
            projection=projection,
            receipt=receipt,
            report_names=report_names,
            ignored_report_names=ignored_markdown_reports(reports_dir, report_names),
            verification_mode=verification_mode,
            verifier_result_sha256=verifier_result_sha256,
        )
    except Exception:
        for guard in reversed(guards):
            guard.close()
        raise


def build_plan_from_evidence(repo: Path, evidence: EvidenceBundle) -> dict:
    """Derive a plan exclusively from held receipt-bound bytes."""

    repo = lexical_absolute(repo)
    snapshot = read_existing_ledger(repo)
    with tempfile.TemporaryDirectory(prefix="full-repo-ledger-evidence-") as temporary:
        staged_reports = Path(temporary) / "reports"
        staged_reports.mkdir(mode=0o700)
        for name, guard in evidence.report_guards.items():
            target = staged_reports / name
            target.write_bytes(guard.data)
            target.chmod(0o400)
        try:
            consolidated = merge_findings.merge_findings(
                staged_reports,
                report_names=evidence.report_names,
            )
        except ValueError as exc:
            raise UpdateError(f"could not consolidate receipt-bound audit reports: {exc}") from exc
    expected_report_hashes = {
        name: guard.sha256 for name, guard in evidence.report_guards.items()
    }
    if consolidated.get("report_sha256") != expected_report_hashes:
        raise UpdateError("staged audit reports do not match the held receipt-bound evidence")
    consolidated["ignored_unverified_reports"] = evidence.ignored_report_names
    expected = merge_findings.render_completion_ledger_projection(
        consolidated,
        run_id=evidence.manifest["run_id"],
        repo_root=evidence.manifest["repo_root"],
        manifest_sha256=evidence.manifest_guard.sha256,
    )
    candidates = validate_projection(evidence.projection, expected, consolidated)
    final_rows, reconciliation = reconcile_rows(list(snapshot.rows), candidates)
    after_content = render_after_content(snapshot, final_rows, reconciliation["added_ids"])
    after_sha256 = sha256_bytes(after_content.encode("utf-8")) if after_content is not None else None
    return {
        "schema_version": 1,
        "repo_root": str(repo),
        "ledger_path": str(repo / LEDGER_NAME),
        "run_id": evidence.manifest["run_id"],
        "audit_verification": evidence.verification_mode,
        "manifest_sha256": evidence.manifest_guard.sha256,
        "verification_receipt_sha256": evidence.receipt_guard.sha256,
        "verifier_result_sha256": evidence.verifier_result_sha256,
        "projection_sha256": evidence.projection_guard.sha256,
        "report_sha256": consolidated["report_sha256"],
        "ignored_unverified_reports": evidence.ignored_report_names,
        "before_sha256": snapshot.sha256,
        "before_identity": snapshot.identity,
        "after_sha256": after_sha256,
        "after_content": after_content,
        "ledger_mode": snapshot.mode,
        "ledger_metadata": snapshot.metadata,
        "changed": snapshot.sha256 != after_sha256,
        **reconciliation,
    }


def build_plan(repo: Path, manifest_path: Path, reports_dir: Path, projection_path: Path) -> dict:
    evidence = open_evidence_bundle(repo, manifest_path, reports_dir, projection_path)
    try:
        plan = build_plan_from_evidence(repo, evidence)
        validate_guards(evidence.guards)
        return plan
    finally:
        evidence.close()


def validate_guards(guards: list[FileGuard]) -> None:
    for guard in guards:
        guard.validate()


def validate_directory_binding(path: Path, descriptor: int, label: str) -> None:
    rebound = open_directory(path, label=label)
    try:
        expected = os.fstat(descriptor)
        observed = os.fstat(rebound)
        if (expected.st_dev, expected.st_ino) != (observed.st_dev, observed.st_ino):
            raise UpdateError(f"{label} path changed during apply: {path}")
    finally:
        os.close(rebound)


def create_temporary_file(directory_fd: int, prefix: str, mode: int = 0o600) -> tuple[int, str]:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0)
    for _ in range(128):
        name = f".{prefix}.{secrets.token_hex(12)}"
        try:
            return os.open(name, flags, mode, dir_fd=directory_fd), name
        except FileExistsError:
            continue
    raise UpdateError(f"could not allocate a temporary file for {prefix}")


def output_entry_type(directory_fd: int, name: str) -> str:
    try:
        value = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
    except FileNotFoundError:
        return "absent"
    if stat.S_ISLNK(value.st_mode):
        return "symlink"
    if stat.S_ISREG(value.st_mode):
        return "regular"
    return "other"


def write_json_atomic(path: Path, value: dict) -> None:
    path = lexical_absolute(path)
    directory_fd = open_directory(path.parent, label="output parent")
    temporary_name: str | None = None
    try:
        entry_type = output_entry_type(directory_fd, path.name)
        if entry_type == "symlink":
            raise UpdateError(f"refusing symlinked output path: {path}")
        if entry_type not in {"absent", "regular"}:
            raise UpdateError(f"output path is not a regular file: {path}")
        before_data: bytes | None = None
        before_identity: dict[str, int] | None = None
        before_metadata: dict | None = None
        if entry_type == "regular":
            before_data, before_identity, before_metadata = named_file_snapshot(
                directory_fd, path.name, "existing output"
            )
        data = (json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n").encode("utf-8")
        descriptor, temporary_name = create_temporary_file(directory_fd, path.name)
        with os.fdopen(descriptor, "wb") as handle:
            if before_metadata is not None:
                apply_descriptor_metadata(handle.fileno(), before_metadata)
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        temporary_data, temporary_identity, temporary_metadata = named_file_snapshot(
            directory_fd, temporary_name, "temporary output"
        )
        if temporary_data != data:
            raise UpdateError(f"temporary output does not match requested JSON: {path}")
        validate_directory_binding(path.parent, directory_fd, "output parent")
        if entry_type == "absent":
            try:
                os.link(
                    temporary_name,
                    path.name,
                    src_dir_fd=directory_fd,
                    dst_dir_fd=directory_fd,
                    follow_symlinks=False,
                )
            except FileExistsError as exc:
                raise UpdateError(f"output path appeared during publication: {path}") from exc
            try:
                validate_directory_binding(path.parent, directory_fd, "output parent")
                assert_named_file_matches(
                    directory_fd,
                    path.name,
                    data,
                    temporary_identity,
                    temporary_metadata,
                    "published output",
                )
                sync_directory(directory_fd)
                assert_named_file_matches(
                    directory_fd,
                    path.name,
                    data,
                    temporary_identity,
                    temporary_metadata,
                    "durable published output",
                )
            except Exception as publication_error:
                recovery_name = temporary_name
                temporary_name = None
                raise PublicationUncertainError(
                    "new output reached publication before a later validation failed; "
                    f"inspect target and recovery link {recovery_name!r}: {publication_error}"
                ) from publication_error
            os.unlink(temporary_name, dir_fd=directory_fd)
            temporary_name = None
        else:
            assert before_data is not None and before_identity is not None and before_metadata is not None
            exchange_paths(directory_fd, temporary_name, path.name)
            backup_name = temporary_name
            temporary_name = None
            restored_before_error = False
            try:
                captured_data, captured_identity, captured_metadata = named_file_snapshot(
                    directory_fd, backup_name, "captured existing output"
                )
                if (
                    captured_data != before_data
                    or not exchange_identity_matches(captured_identity, before_identity)
                    or captured_metadata != before_metadata
                ):
                    exchange_paths(directory_fd, backup_name, path.name)
                    restored_temp_data, restored_temp_identity, restored_temp_metadata = named_file_snapshot(
                        directory_fd, backup_name, "rejected generated output"
                    )
                    if (
                        restored_temp_data != temporary_data
                        or not exchange_identity_matches(restored_temp_identity, temporary_identity)
                        or restored_temp_metadata != temporary_metadata
                    ):
                        raise PublicationUncertainError(
                            "output changed concurrently during rollback; generated and writer states were retained for inspection"
                        )
                    try:
                        assert_named_file_matches(
                            directory_fd,
                            path.name,
                            captured_data,
                            captured_identity,
                            captured_metadata,
                            "restored concurrent output",
                        )
                    except UpdateError as restore_error:
                        raise PublicationUncertainError(
                            "the concurrent output could not be verified after restoration; "
                            f"the rejected generated output remains at {backup_name!r}: {restore_error}"
                        ) from restore_error
                    os.unlink(backup_name, dir_fd=directory_fd)
                    restored_before_error = True
                    raise UpdateError(f"output path changed during publication: {path}")
                validate_directory_binding(path.parent, directory_fd, "output parent")
                assert_named_file_matches(
                    directory_fd,
                    path.name,
                    data,
                    temporary_identity,
                    temporary_metadata,
                    "published output",
                )
                sync_directory(directory_fd)
                assert_named_file_matches(
                    directory_fd,
                    path.name,
                    data,
                    temporary_identity,
                    temporary_metadata,
                    "durable published output",
                )
                os.unlink(backup_name, dir_fd=directory_fd)
            except Exception as publication_error:
                if restored_before_error:
                    raise
                try:
                    exchange_paths(directory_fd, backup_name, path.name)
                    rollback_data, rollback_identity, rollback_metadata = named_file_snapshot(
                        directory_fd, backup_name, "output rollback capture"
                    )
                    if (
                        rollback_data == temporary_data
                        and exchange_identity_matches(rollback_identity, temporary_identity)
                        and rollback_metadata == temporary_metadata
                    ):
                        try:
                            assert_named_file_matches(
                                directory_fd,
                                path.name,
                                before_data,
                                before_identity,
                                before_metadata,
                                "restored prior output",
                            )
                        except UpdateError as restore_error:
                            raise PublicationUncertainError(
                                "output rollback preserved the prior-output inode, but it no longer "
                                "matches the reviewed prior hash, identity, and metadata; "
                                f"inspect {path.name!r} and {backup_name!r}: {restore_error}"
                            ) from publication_error
                        os.unlink(backup_name, dir_fd=directory_fd)
                        sync_directory(directory_fd)
                        raise UpdateError(
                            f"output publication failed and the previous output was restored: {publication_error}"
                        ) from publication_error
                    exchange_paths(directory_fd, backup_name, path.name)
                except UpdateError:
                    raise
                except Exception as rollback_error:
                    raise PublicationUncertainError(
                        "output publication failed and concurrent state prevented safe rollback; "
                        f"the prior output remains at {backup_name!r}: {rollback_error}"
                    ) from publication_error
                raise PublicationUncertainError(
                    "output publication failed while another writer changed the target; "
                    f"the writer state was restored and prior output remains at {backup_name!r}"
                ) from publication_error
        validate_directory_binding(path.parent, directory_fd, "output parent")
    finally:
        if temporary_name is not None:
            try:
                os.unlink(temporary_name, dir_fd=directory_fd)
            except FileNotFoundError:
                pass
        os.close(directory_fd)


def assert_ledger_snapshot(repo: Path, directory_fd: int, expected_sha256: str | None, expected_identity: dict | None) -> LedgerSnapshot:
    snapshot = read_existing_ledger(repo, directory_fd=directory_fd)
    if snapshot.sha256 != expected_sha256 or snapshot.identity != expected_identity:
        raise UpdateError("CompletionLedger.md changed after planning; regenerate the plan")
    return snapshot


def exchange_paths(directory_fd: int, first: str, second: str) -> None:
    """Atomically exchange two names or refuse when the platform lacks the primitive."""

    libc = ctypes.CDLL(None, use_errno=True)
    first_bytes = os.fsencode(first)
    second_bytes = os.fsencode(second)
    if platform.system() == "Linux" and hasattr(libc, "renameat2"):
        function = libc.renameat2
        function.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
        function.restype = ctypes.c_int
        result = function(directory_fd, first_bytes, directory_fd, second_bytes, 2)  # RENAME_EXCHANGE
    elif platform.system() == "Darwin" and hasattr(libc, "renameatx_np"):
        function = libc.renameatx_np
        function.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
        function.restype = ctypes.c_int
        result = function(directory_fd, first_bytes, directory_fd, second_bytes, 0x00000002)  # RENAME_SWAP
    else:
        raise UpdateError(
            "this platform lacks an atomic name-exchange primitive; refusing a ledger update that could lose concurrent work"
        )
    if result != 0:
        error = ctypes.get_errno()
        raise OSError(error, os.strerror(error), f"{first} <-> {second}")


def named_file_snapshot(directory_fd: int, name: str, label: str) -> tuple[bytes, dict[str, int], dict]:
    flags = (
        os.O_RDONLY
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NONBLOCK", 0)
    )
    descriptor = os.open(name, flags, dir_fd=directory_fd)
    try:
        data, identity = read_descriptor_stable(descriptor, Path(name), label)
        metadata = descriptor_metadata(descriptor)
        final_descriptor_stat = os.fstat(descriptor)
        final_identity = stat_identity(final_descriptor_stat)
        if final_identity != identity:
            raise UpdateError(f"{label} data or metadata changed while it was being read: {name}")
        try:
            final_path_stat = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
        except FileNotFoundError as exc:
            raise UpdateError(f"{label} disappeared while it was being read: {name}") from exc
        if not stat.S_ISREG(final_path_stat.st_mode) or stat_identity(final_path_stat) != final_identity:
            raise UpdateError(f"{label} was replaced while it was being read: {name}")
        return data, final_identity, metadata
    finally:
        os.close(descriptor)


def assert_named_file_matches(
    directory_fd: int,
    name: str,
    expected_data: bytes,
    expected_identity: dict[str, int],
    expected_metadata: dict,
    label: str,
) -> None:
    data, identity, metadata = named_file_snapshot(directory_fd, name, label)
    if (
        data != expected_data
        or not exchange_identity_matches(identity, expected_identity)
        or metadata != expected_metadata
    ):
        raise UpdateError(f"{label} changed during publication")


def sync_directory(directory_fd: int) -> None:
    os.fsync(directory_fd)


def assert_published_ledger(
    directory_fd: int,
    published_identity: dict[str, int],
    expected_sha256: str,
    expected_metadata: dict | None,
) -> None:
    data, identity, metadata = named_file_snapshot(
        directory_fd, LEDGER_NAME, "published completion ledger"
    )
    if (identity["device"], identity["inode"]) != (
        published_identity["device"],
        published_identity["inode"],
    ):
        raise UpdateError("published CompletionLedger.md was concurrently replaced")
    if sha256_bytes(data) != expected_sha256:
        raise UpdateError("published CompletionLedger.md hash does not match the reviewed plan")
    if expected_metadata is not None and metadata != expected_metadata:
        raise UpdateError("published CompletionLedger.md metadata changed during publication")
    try:
        completion_ledger.parse_ledger(data.decode("utf-8"))
    except (UnicodeDecodeError, completion_ledger.LedgerError) as exc:
        raise UpdateError(f"published CompletionLedger.md is invalid: {exc}") from exc


def rollback_existing_publication(
    directory_fd: int,
    temporary_name: str,
    expected_before_sha256: str,
    expected_before_identity: dict[str, int],
    expected_before_metadata: dict,
    published_identity: dict[str, int],
    expected_after_sha256: str,
    expected_after_metadata: dict,
    cause: Exception,
) -> None:
    try:
        exchange_paths(directory_fd, temporary_name, LEDGER_NAME)
    except Exception as rollback_error:
        raise PublicationUncertainError(
            "ledger publication failed and atomic rollback also failed; "
            f"the prior ledger should remain at {temporary_name!r}: {rollback_error}"
        ) from cause
    try:
        captured_data, captured_identity, captured_metadata = named_file_snapshot(
            directory_fd, temporary_name, "rollback-captured completion ledger"
        )
        captured_is_published = (
            sha256_bytes(captured_data) == expected_after_sha256
            and exchange_identity_matches(captured_identity, published_identity)
            and captured_metadata == expected_after_metadata
        )
        if not captured_is_published:
            try:
                exchange_paths(directory_fd, temporary_name, LEDGER_NAME)
            except Exception as restore_error:
                raise PublicationUncertainError(
                    "rollback captured a concurrent ledger replacement and could not restore it; "
                    f"the captured writer state remains at {temporary_name!r}: {restore_error}"
                ) from cause
            try:
                restored_writer_data, restored_writer_identity, restored_writer_metadata = named_file_snapshot(
                    directory_fd, LEDGER_NAME, "restored concurrent completion ledger"
                )
                if (
                    sha256_bytes(restored_writer_data) != sha256_bytes(captured_data)
                    or not exchange_identity_matches(restored_writer_identity, captured_identity)
                    or restored_writer_metadata != captured_metadata
                ):
                    raise PublicationUncertainError(
                        "rollback detected a concurrent ledger replacement, but its restored path changed again"
                    )
            except PublicationUncertainError:
                raise
            except Exception as restore_check_error:
                raise PublicationUncertainError(
                    "rollback restored a concurrent ledger replacement but could not verify it: "
                    f"{restore_check_error}"
                ) from cause
            raise PublicationUncertainError(
                "ledger publication failed while another writer replaced CompletionLedger.md; "
                f"the concurrent writer was restored and the prior ledger is retained at {temporary_name!r}: {cause}"
            ) from cause

        restored_data, restored_identity, restored_metadata = named_file_snapshot(
            directory_fd, LEDGER_NAME, "restored completion ledger"
        )
        if (
            sha256_bytes(restored_data) != expected_before_sha256
            or not exchange_identity_matches(restored_identity, expected_before_identity)
            or restored_metadata != expected_before_metadata
        ):
            raise PublicationUncertainError(
                "rollback preserved the state found in the prior-ledger inode, but it no longer matches "
                f"the reviewed prior hash, identity, and metadata; inspect {temporary_name!r} and "
                "CompletionLedger.md"
            )
        try:
            sync_directory(directory_fd)
        except OSError as sync_error:
            raise PublicationUncertainError(
                "the prior completion ledger was restored, but rollback durability could not be confirmed; "
                f"the rejected published ledger remains at {temporary_name!r}: {sync_error}"
            ) from cause
        try:
            os.unlink(temporary_name, dir_fd=directory_fd)
        except OSError as cleanup_error:
            raise PublicationUncertainError(
                "the prior completion ledger was restored, but the rejected published ledger "
                f"at {temporary_name!r} could not be removed: {cleanup_error}"
            ) from cause
    except PublicationUncertainError:
        raise
    except Exception as rollback_check_error:
        raise PublicationUncertainError(
            f"ledger rollback completed but could not be verified: {rollback_check_error}"
        ) from cause
    raise UpdateError(f"ledger publication refused and the prior ledger was restored: {cause}") from cause


def rollback_absent_publication(
    directory_fd: int,
    temporary_name: str,
    published_identity: dict[str, int],
    expected_after_sha256: str,
    expected_after_metadata: dict,
    cause: Exception,
) -> None:
    raise PublicationUncertainError(
        "new CompletionLedger.md reached publication before a later validation failed; "
        "it was deliberately not unlinked because a non-cooperating writer could have replaced it. "
        f"Inspect the ledger and recovery link {temporary_name!r}; original error: {cause}"
    ) from cause


def apply_plan(
    repo: Path,
    manifest_path: Path,
    reports_dir: Path,
    projection_path: Path,
    plan_path: Path,
) -> dict:
    repo = lexical_absolute(repo)
    manifest_path = lexical_absolute(manifest_path)
    reports_dir = lexical_absolute(reports_dir)
    projection_path = lexical_absolute(projection_path)
    plan_path = lexical_absolute(plan_path)
    directory_fd = open_directory(repo, label="repository")
    guards: list[FileGuard] = []
    try:
        fcntl.flock(directory_fd, fcntl.LOCK_EX)
        plan_guard = open_file_guard(plan_path, "completion-ledger plan")
        # The plan is not a verifier input, and the updater itself may publish
        # the ledger in the same directory. Its own descriptor/path identity
        # remains guarded without treating that authorized directory mutation
        # as an external race.
        plan_guard.finish_verification()
        guards.append(plan_guard)
        recorded_plan = parse_json_bytes(plan_guard.data, plan_guard.path, "completion-ledger plan")
        evidence = open_evidence_bundle(repo, manifest_path, reports_dir, projection_path)
        guards.extend(evidence.guards)
        current_plan = build_plan_from_evidence(repo, evidence)
        validate_guards(guards)
        if set(recorded_plan) != set(current_plan) or recorded_plan != current_plan:
            raise UpdateError("completion-ledger plan is stale or malformed; regenerate and review it before apply")
        validate_directory_binding(repo, directory_fd, "repository")
        assert_ledger_snapshot(
            repo,
            directory_fd,
            current_plan["before_sha256"],
            current_plan["before_identity"],
        )
        if current_plan["changed"]:
            content = current_plan["after_content"]
            if content is None:
                raise UpdateError("audit ledger importer never deletes CompletionLedger.md")
            descriptor, temporary_name = create_temporary_file(directory_fd, LEDGER_NAME)
            try:
                with os.fdopen(descriptor, "wb") as handle:
                    if current_plan["ledger_metadata"] is None:
                        os.fchmod(handle.fileno(), current_plan["ledger_mode"])
                    else:
                        apply_descriptor_metadata(handle.fileno(), current_plan["ledger_metadata"])
                    handle.write(content.encode("utf-8"))
                    handle.flush()
                    os.fsync(handle.fileno())
                assert_ledger_snapshot(
                    repo,
                    directory_fd,
                    current_plan["before_sha256"],
                    current_plan["before_identity"],
                )
                validate_guards(guards)
                validate_directory_binding(repo, directory_fd, "repository")
                temporary_data, published_identity, published_metadata = named_file_snapshot(
                    directory_fd,
                    temporary_name,
                    "temporary completion ledger",
                )
                if sha256_bytes(temporary_data) != current_plan["after_sha256"]:
                    raise UpdateError("temporary CompletionLedger.md hash does not match the reviewed plan")
                if (
                    current_plan["ledger_metadata"] is not None
                    and published_metadata != current_plan["ledger_metadata"]
                ):
                    raise UpdateError("temporary CompletionLedger.md metadata does not match the reviewed plan")
                if current_plan["before_identity"] is None:
                    try:
                        os.link(
                            temporary_name,
                            LEDGER_NAME,
                            src_dir_fd=directory_fd,
                            dst_dir_fd=directory_fd,
                            follow_symlinks=False,
                        )
                    except FileExistsError as exc:
                        raise UpdateError("CompletionLedger.md appeared during apply; regenerate the plan") from exc
                    published = True
                    recovery_name = temporary_name
                    temporary_name = None
                    try:
                        validate_guards(guards)
                        validate_directory_binding(repo, directory_fd, "repository")
                        assert_published_ledger(
                            directory_fd,
                            published_identity,
                            current_plan["after_sha256"],
                            published_metadata,
                        )
                        sync_directory(directory_fd)
                        assert_published_ledger(
                            directory_fd,
                            published_identity,
                            current_plan["after_sha256"],
                            published_metadata,
                        )
                    except Exception as publication_error:
                        rollback_absent_publication(
                            directory_fd,
                            recovery_name,
                            published_identity,
                            current_plan["after_sha256"],
                            published_metadata,
                            publication_error,
                        )
                    if published:
                        try:
                            os.unlink(recovery_name, dir_fd=directory_fd)
                        except OSError as cleanup_error:
                            raise PublicationUncertainError(
                                "the new CompletionLedger.md was applied, but its temporary recovery link "
                                f"{recovery_name!r} could not be removed: {cleanup_error}"
                            ) from cleanup_error
                else:
                    exchange_paths(directory_fd, temporary_name, LEDGER_NAME)
                    backup_name = temporary_name
                    temporary_name = None
                    try:
                        backup_data, backup_identity, backup_metadata = named_file_snapshot(
                            directory_fd,
                            backup_name,
                            "prior completion ledger backup",
                        )
                        if (
                            sha256_bytes(backup_data) != current_plan["before_sha256"]
                            or not exchange_identity_matches(
                                backup_identity, current_plan["before_identity"]
                            )
                            or backup_metadata != current_plan["ledger_metadata"]
                        ):
                            raise UpdateError(
                                "CompletionLedger.md changed at the atomic publication boundary: "
                                f"hash_match={sha256_bytes(backup_data) == current_plan['before_sha256']}, "
                                f"identity_expected={current_plan['before_identity']}, "
                                f"identity_observed={backup_identity}, "
                                f"metadata_match={backup_metadata == current_plan['ledger_metadata']}"
                            )
                        validate_guards(guards)
                        validate_directory_binding(repo, directory_fd, "repository")
                        assert_published_ledger(
                            directory_fd,
                            published_identity,
                            current_plan["after_sha256"],
                            current_plan["ledger_metadata"],
                        )
                        sync_directory(directory_fd)
                        assert_published_ledger(
                            directory_fd,
                            published_identity,
                            current_plan["after_sha256"],
                            current_plan["ledger_metadata"],
                        )
                    except Exception as publication_error:
                        rollback_existing_publication(
                            directory_fd,
                            backup_name,
                            current_plan["before_sha256"],
                            current_plan["before_identity"],
                            current_plan["ledger_metadata"],
                            published_identity,
                            current_plan["after_sha256"],
                            current_plan["ledger_metadata"],
                            publication_error,
                        )
                    try:
                        os.unlink(backup_name, dir_fd=directory_fd)
                    except OSError as cleanup_error:
                        raise PublicationUncertainError(
                            "CompletionLedger.md was applied and made durable, but the prior-ledger backup "
                            f"{backup_name!r} could not be removed: {cleanup_error}"
                        ) from cleanup_error
            finally:
                if temporary_name is not None:
                    try:
                        os.unlink(temporary_name, dir_fd=directory_fd)
                    except FileNotFoundError:
                        pass
        else:
            validate_guards(guards)
            validate_directory_binding(repo, directory_fd, "repository")
            assert_ledger_snapshot(
                repo,
                directory_fd,
                current_plan["after_sha256"],
                current_plan["before_identity"],
            )
    finally:
        for guard in reversed(guards):
            guard.close()
        os.close(directory_fd)
    return current_plan


def add_common_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--repo", required=True, type=Path)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--reports", required=True, type=Path)
    parser.add_argument("--projection", required=True, type=Path)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    plan_parser = subparsers.add_parser(
        "plan",
        help="Bind pass-only audit evidence and current sources into a no-mutation ledger plan.",
    )
    add_common_arguments(plan_parser)
    plan_parser.add_argument("--out", required=True, type=Path)
    apply_parser = subparsers.add_parser(
        "apply",
        help="Revalidate bound evidence and atomically apply an exact reviewed plan.",
    )
    add_common_arguments(apply_parser)
    apply_parser.add_argument("--plan", required=True, type=Path)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        if args.command == "plan":
            plan = build_plan(args.repo, args.manifest, args.reports, args.projection)
            write_json_atomic(args.out, plan)
        else:
            plan = apply_plan(args.repo, args.manifest, args.reports, args.projection, args.plan)
        print(json.dumps({key: value for key, value in plan.items() if key != "after_content"}, indent=2, sort_keys=True))
        return 0
    except PublicationUncertainError as exc:
        print(f"completion-ledger publication state requires inspection: {exc}", file=sys.stderr)
        return 2
    except (OSError, UpdateError, completion_ledger.LedgerError, KeyError) as exc:
        print(f"completion-ledger update refused: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
