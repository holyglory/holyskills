#!/usr/bin/env python3
"""Unit and safety tests for the full-repo-audit completion-ledger importer."""

from __future__ import annotations

import copy
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path


SCRIPT = Path(__file__).with_name("update_completion_ledger.py")
SPEC = importlib.util.spec_from_file_location("update_completion_ledger", SCRIPT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("unable to load completion-ledger updater")
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)
LEDGER = MODULE.completion_ledger
MERGE = MODULE.merge_findings
AUDIT_SELF_TEST = SCRIPT.with_name("self_test.py")
BUILD_AUDIT = SCRIPT.with_name("build_audit_batches.py")


def load_audit_fixture_helpers():
    spec = importlib.util.spec_from_file_location(
        "full_repo_audit_fixture_helpers_for_updater",
        AUDIT_SELF_TEST,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("unable to load full-repo-audit fixture helpers")
    helper = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = helper
    spec.loader.exec_module(helper)
    return helper


def check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def expect_error(callback, needle: str) -> None:
    try:
        callback()
    except (MODULE.UpdateError, LEDGER.LedgerError) as exc:
        check(needle in str(exc), f"expected {needle!r} in {exc!r}")
    else:
        raise AssertionError(f"expected failure containing {needle!r}")


def finding(priority: str, summary: str, path: str) -> dict:
    item = {
        "priority": priority,
        "summary": summary,
        "files": [path],
        "evidence": f"Concrete source evidence for {summary}.",
        "expected_behavior": f"The responsibility in {path} should work end to end.",
        "gap": f"The implementation gap in {path} remains unresolved.",
        "suggested_direction": f"Complete the real path in {path}.",
        "sources": ["batch_001.md"],
    }
    item["candidate_id"] = MERGE.candidate_id(item)
    return item


def actual_verifier_gate_self_test() -> None:
    """Prove the updater accepts real verified evidence and rejects forged receipts."""

    helpers = load_audit_fixture_helpers()
    with tempfile.TemporaryDirectory(prefix="full-repo-ledger-real-verifier-") as temporary:
        root = Path(temporary)
        repo = root / "repo"
        source = repo / "src" / "calculate.py"
        source.parent.mkdir(parents=True)
        source.write_text(
            "def calculate_tax(total, rate):\n    return total * rate\n",
            encoding="utf-8",
        )
        test_source = repo / "tests" / "test_calculate.py"
        test_source.parent.mkdir(parents=True)
        test_source.write_text(
            "def test_calculate_tax():\n    assert 10 * 0.2 == 2\n",
            encoding="utf-8",
        )
        audit_root = root / "audit"
        result = subprocess.run(
            [
                sys.executable,
                str(BUILD_AUDIT),
                "--repo",
                str(repo),
                "--out",
                str(audit_root),
                "--batch-size",
                "200",
            ],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        check(
            result.returncode == 0,
            f"real verifier fixture build failed: {result.stdout}\n{result.stderr}",
        )
        complete_report = helpers.write_reports(
            root / "fixture-reports",
            audit_root / "manifest.json",
        )[-1]
        helpers.install_report(audit_root, complete_report)
        helpers.complete_effort_ledger(audit_root)

        manifest_path = audit_root / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        reports_dir = audit_root / "reports"
        report_names = MODULE.authorized_report_names(manifest)
        verifier_report_paths = sorted(
            reports_dir / name
            for name in report_names
            if MODULE.audit_verifier.REPORT_FILENAME_RE.fullmatch(name)
            or name == MODULE.audit_verifier.LEAD_RECONCILIATION_REPORT_NAME
        )
        verifier_result, receipt = MODULE.audit_verifier.verify_with_receipt_data(
            manifest_path,
            verifier_report_paths,
            skip_current_hash_check=False,
        )
        check(
            verifier_result.get("ok") is True,
            "real verifier fixture must genuinely pass: "
            + json.dumps(verifier_result, indent=2, sort_keys=True),
        )
        check(receipt is not None, "a genuine passing verifier run must create receipt data")
        receipt_path = audit_root / "verification_receipt.json"
        receipt_path.write_text(json.dumps(receipt, sort_keys=True), encoding="utf-8")

        consolidated = MERGE.merge_findings(reports_dir, report_names=report_names)
        projection = MERGE.render_completion_ledger_projection(
            consolidated,
            run_id=manifest["run_id"],
            repo_root=manifest["repo_root"],
            manifest_sha256=MODULE.sha256_file(manifest_path),
        )
        projection["review_status"] = "complete"
        projection_path = audit_root / "completion_ledger_projection.json"
        projection_path.write_text(json.dumps(projection, sort_keys=True), encoding="utf-8")

        plan = MODULE.build_plan(repo, manifest_path, reports_dir, projection_path)
        check(plan["audit_verification"] == "verified", "real plan must record a fresh verifier pass")
        check(
            plan["verifier_result_sha256"] == receipt["verifier_result_sha256"],
            "real plan must bind the rerun verifier result digest",
        )
        plan_path = audit_root / "completion_ledger_plan.json"
        plan_path.write_text(json.dumps(plan, sort_keys=True), encoding="utf-8")
        MODULE.apply_plan(repo, manifest_path, reports_dir, projection_path, plan_path)
        check(not (repo / "CompletionLedger.md").exists(), "a real clean audit must remain a no-op")

        effort_path = audit_root / "effort_ledger.json"
        effort_bytes = effort_path.read_bytes()
        original_verify = MODULE.audit_verifier.verify

        def verify_then_aba_effort(*args, **kwargs):
            verified = original_verify(*args, **kwargs)
            effort_path.write_bytes(effort_bytes + b"\n")
            effort_path.write_bytes(effort_bytes)
            return verified

        MODULE.audit_verifier.verify = verify_then_aba_effort
        try:
            expect_error(
                lambda: MODULE.build_plan(repo, manifest_path, reports_dir, projection_path),
                "audit effort ledger changed during apply",
            )
        finally:
            MODULE.audit_verifier.verify = original_verify
        check(effort_path.read_bytes() == effort_bytes, "companion ABA fixture must restore its bytes")

        genuine_receipt = receipt_path.read_bytes()
        forged_digest_receipt = json.loads(genuine_receipt)
        forged_digest_receipt["verifier_result_sha256"] = MODULE.audit_verifier.canonical_json_sha256(
            {"ok": True, "forged": True}
        )
        receipt_path.write_text(json.dumps(forged_digest_receipt), encoding="utf-8")
        expect_error(
            lambda: MODULE.build_plan(repo, manifest_path, reports_dir, projection_path),
            "does not match the pass-only verification receipt",
        )
        receipt_path.write_bytes(genuine_receipt)

        lead_report = reports_dir / MODULE.audit_verifier.LEAD_RECONCILIATION_REPORT_NAME
        lead_report.write_text("## Findings\nNo findings.\n", encoding="utf-8")
        forged_receipt = json.loads(genuine_receipt)
        forged_receipt["report_sha256"][lead_report.name] = MODULE.sha256_file(lead_report)
        forged_receipt["verifier_result_sha256"] = MODULE.audit_verifier.canonical_json_sha256(
            {"ok": True}
        )
        receipt_path.write_text(json.dumps(forged_receipt), encoding="utf-8")
        expect_error(
            lambda: MODULE.build_plan(repo, manifest_path, reports_dir, projection_path),
            "audit verifier did not pass",
        )
        expect_error(
            lambda: MODULE.apply_plan(
                repo,
                manifest_path,
                reports_dir,
                projection_path,
                plan_path,
            ),
            "audit verifier did not pass",
        )


def main() -> int:
    actual_verifier_gate_self_test()
    escaped = LEDGER.LedgerRow(
        "Q-EXISTING",
        "Preserve the A | B contract and path C:\\state.",
        "An unrelated active obligation must survive audit imports.",
        "Open",
        "Run the existing end-to-end verification after implementation.",
    )
    rendered = LEDGER.render_ledger([escaped])
    check(LEDGER.parse_ledger(rendered) == [escaped], "ledger rendering should round-trip escaped cells")
    spaced = LEDGER.LedgerRow(
        "Q-SPACED",
        "Preserve two  intentional spaces in active work.",
        "Reviewed ledger content must not be silently normalized.",
        "Open",
        "Verify the exact  reviewed wording remains present.",
    )
    check(LEDGER.parse_ledger(LEDGER.render_ledger([spaced])) == [spaced], "ledger rendering must preserve internal whitespace")
    blocked = LEDGER.LedgerRow(
        "Q-BLOCKED",
        "Complete the integration after the external repair.",
        "The dependency currently prevents end-to-end completion.",
        "Blocked — until the upstream defect is fixed",
        "Rerun the end-to-end path once the upstream defect is fixed.",
    )
    check(LEDGER.parse_ledger(LEDGER.render_ledger([blocked])) == [blocked], "a future unblock condition may describe a fix")
    expect_error(
        lambda: LEDGER.parse_ledger(rendered.replace("| Open |", "| Resolved |")),
        "terminal",
    )
    expect_error(
        lambda: LEDGER.parse_ledger(rendered.replace("| Open |", "| Open / Resolved |")),
        "terminal",
    )

    consolidated = {
        "reports_scanned": 1,
        "raw_findings": 3,
        "unique_findings": 3,
        "priority_counts": {"P0": 0, "P1": 1, "P2": 1, "P3": 1},
        "findings": [
            finding("P1", "Calculation returns a fixed value", "src/calculate.py"),
            finding("P2", "Duplicate of existing active work", "src/existing.py"),
            finding("P3", "Possible concern requiring product confirmation", "src/question.py"),
        ],
    }
    expected = MERGE.render_completion_ledger_projection(
        consolidated,
        run_id="run-1",
        repo_root="/tmp/repo",
        manifest_sha256="a" * 64,
    )
    projection = copy.deepcopy(expected)
    projection["review_status"] = "complete"
    confirmed, duplicate, hypothesis = projection["candidates"]
    confirmed["disposition"] = "confirmed"
    confirmed["disposition_reason"] = "Lead source trace confirmed a hard-coded result instead of the required calculation."
    confirmed["ledger_row"].update(
        {
            "remaining_work": "[P1] Implement the input-derived calculation in src/calculate.py.",
            "why_it_matters": "Every input currently receives the same incorrect result.",
            "status": "Open",
            "verification": "Exercise varied inputs and assert the computed outputs through the public entry point.",
        }
    )
    duplicate["disposition"] = "duplicate"
    duplicate["disposition_reason"] = "The existing active obligation already requires the same completion outcome."
    duplicate["ledger_row"]["id"] = escaped.id
    hypothesis["disposition"] = "hypothesis"
    hypothesis["disposition_reason"] = "The source alone does not establish the product requirement; user confirmation is required."

    candidates = MODULE.validate_projection(projection, expected, consolidated)
    rows, receipt = MODULE.reconcile_rows([escaped], candidates)
    check(rows[0] == escaped, "unrelated existing rows must be preserved exactly")
    check(len(rows) == 2, "one confirmed finding should add exactly one active row")
    check(receipt["added_ids"] == [confirmed["ledger_row"]["id"]], "confirmed finding should map to its stable ID")
    check(receipt["disposition_counts"]["hypothesis"] == 1, "hypotheses must remain outside the ledger")

    rows_again, receipt_again = MODULE.reconcile_rows(rows, candidates)
    check(rows_again == rows, "reapplying the same reviewed projection must be idempotent")
    check(not receipt_again["added_ids"] and not receipt_again["updated_ids"], "idempotent reconciliation must not add/update rows")
    check(receipt_again["already_present_ids"] == [confirmed["ledger_row"]["id"]], "idempotent replay must be explicit")

    colliding = copy.deepcopy(projection)
    colliding["candidates"][0]["ledger_row"]["why_it_matters"] = (
        "A colliding row must never overwrite the already reviewed active obligation."
    )
    expect_error(lambda: MODULE.reconcile_rows(rows, colliding["candidates"]), "ID collision")

    preserved_text = LEDGER.render_ledger([spaced]).replace("\n", "\r\n")
    preserved_data = preserved_text.encode("utf-8")
    preserved_snapshot = MODULE.LedgerSnapshot(
        (spaced,),
        preserved_data,
        MODULE.sha256_bytes(preserved_data),
        0o640,
        {"device": 1, "inode": 2, "size": len(preserved_data), "mtime_ns": 3, "ctime_ns": 4, "mode": 0o100640},
    )
    no_op_content = MODULE.render_after_content(preserved_snapshot, [spaced], [])
    check(no_op_content == preserved_text, "a no-op import must preserve every existing ledger byte")
    appended = MODULE.render_after_content(preserved_snapshot, [spaced, rows[-1]], [rows[-1].id])
    check(appended is not None and appended.startswith(preserved_text), "append must preserve the original ledger as an exact prefix")
    check("two  intentional" in appended, "append must preserve internal whitespace in unrelated rows")
    check("\r\n| FRA-" in appended, "append must retain the existing CRLF newline convention")
    check(LEDGER.parse_ledger(appended) == [spaced, rows[-1]], "append must produce the exact reviewed row set")
    trailing_bytes = preserved_data + b"  \r\n\r\n"
    trailing_snapshot = MODULE.LedgerSnapshot(
        (spaced,),
        trailing_bytes,
        MODULE.sha256_bytes(trailing_bytes),
        0o640,
        preserved_snapshot.identity,
    )
    trailing_append = MODULE.render_after_content(trailing_snapshot, [spaced, rows[-1]], [rows[-1].id])
    check(
        trailing_append is not None and trailing_append.encode("utf-8").startswith(trailing_bytes),
        "append must preserve accepted trailing whitespace bytes as an exact prefix",
    )

    pending = copy.deepcopy(projection)
    pending["candidates"][0]["disposition"] = "pending"
    expect_error(lambda: MODULE.validate_projection(pending, expected, consolidated), "invalid disposition")
    omitted = copy.deepcopy(projection)
    omitted["candidates"].pop()
    expect_error(lambda: MODULE.validate_projection(omitted, expected, consolidated), "every consolidated finding")
    weak_verification = copy.deepcopy(projection)
    weak_verification["candidates"][0]["ledger_row"]["verification"] = "later"
    expect_error(lambda: MODULE.validate_projection(weak_verification, expected, consolidated), "underspecified verification")
    markup_only_blocked = copy.deepcopy(projection)
    markup_only_blocked["candidates"][0]["ledger_row"]["status"] = "**Blocked**"
    expect_error(
        lambda: MODULE.validate_projection(markup_only_blocked, expected, consolidated),
        "meaningful unblock condition",
    )
    blank_reason = copy.deepcopy(projection)
    blank_reason["candidates"][0]["disposition_reason"] = ""
    expect_error(lambda: MODULE.validate_projection(blank_reason, expected, consolidated), "concrete reason")
    extra_projection_key = copy.deepcopy(projection)
    extra_projection_key["ignored"] = True
    expect_error(lambda: MODULE.validate_projection(extra_projection_key, expected, consolidated), "keys must be exact")
    extra_candidate_key = copy.deepcopy(projection)
    extra_candidate_key["candidates"][0]["ignored"] = True
    expect_error(lambda: MODULE.validate_projection(extra_candidate_key, expected, consolidated), "keys must be exact")
    extra_row_key = copy.deepcopy(projection)
    extra_row_key["candidates"][0]["ledger_row"]["ignored"] = "misleading"
    expect_error(lambda: MODULE.validate_projection(extra_row_key, expected, consolidated), "keys must be exact")

    no_findings = {
        "reports_scanned": 1,
        "raw_findings": 0,
        "unique_findings": 0,
        "priority_counts": {"P0": 0, "P1": 0, "P2": 0, "P3": 0},
        "findings": [],
    }
    empty_expected = MERGE.render_completion_ledger_projection(
        no_findings,
        run_id="run-2",
        repo_root="/tmp/repo",
        manifest_sha256="b" * 64,
    )
    empty_projection = copy.deepcopy(empty_expected)
    empty_projection["review_status"] = "complete"
    empty_candidates = MODULE.validate_projection(empty_projection, empty_expected, no_findings)
    empty_rows, _ = MODULE.reconcile_rows([escaped], empty_candidates)
    check(empty_rows == [escaped], "a clean audit must not prune an existing active row")

    with tempfile.TemporaryDirectory(prefix="full-repo-ledger-updater-") as temporary:
        repo = Path(temporary)
        target = repo / "target.md"
        target.write_text(rendered, encoding="utf-8")
        (repo / "CompletionLedger.md").symlink_to(target)
        expect_error(lambda: MODULE.read_existing_ledger(repo), "symlinked completion ledger")

        duplicate_json = repo / "duplicate.json"
        duplicate_json.write_text('{"review_status":"pending","review_status":"complete"}\n', encoding="utf-8")
        expect_error(lambda: MODULE.load_json(duplicate_json, "projection"), "duplicate object key")
        nonfinite_json = repo / "nonfinite.json"
        nonfinite_json.write_text('{"value":NaN}\n', encoding="utf-8")
        expect_error(lambda: MODULE.load_json(nonfinite_json, "projection"), "non-finite number")

        victim = repo / "victim.json"
        victim.write_text("must remain unchanged\n", encoding="utf-8")
        plan_link = repo / "plan.json"
        plan_link.symlink_to(victim)
        expect_error(lambda: MODULE.write_json_atomic(plan_link, {"changed": False}), "symlinked output path")
        check(victim.read_text(encoding="utf-8") == "must remain unchanged\n", "plan output must not follow a symlink")

        outside = repo / "outside"
        outside.mkdir()
        linked_parent = repo / "linked-parent"
        linked_parent.symlink_to(outside, target_is_directory=True)
        expect_error(
            lambda: MODULE.write_json_atomic(linked_parent / "plan.json", {"changed": False}),
            "symlinked path component",
        )
        check(not (outside / "plan.json").exists(), "plan output must not follow a symlinked parent")

        real_repository = repo / "real-repository"
        real_repository.mkdir()
        linked_repository = repo / "linked-repository"
        linked_repository.symlink_to(real_repository, target_is_directory=True)
        expect_error(
            lambda: MODULE.open_directory(linked_repository, label="repository"),
            "symlinked path component",
        )

        output_parent = repo / "output-parent"
        output_parent.mkdir()
        moved_output_parent = repo / "moved-output-parent"
        output_outside = repo / "output-outside"
        output_outside.mkdir()
        original_create_temporary_for_output = MODULE.create_temporary_file
        parent_swapped = False

        def create_temporary_then_swap_parent(directory_fd: int, prefix: str, mode: int = 0o600):
            nonlocal parent_swapped
            result = original_create_temporary_for_output(directory_fd, prefix, mode)
            if prefix == "plan.json" and not parent_swapped:
                parent_swapped = True
                output_parent.rename(moved_output_parent)
                output_parent.symlink_to(output_outside, target_is_directory=True)
            return result

        MODULE.create_temporary_file = create_temporary_then_swap_parent
        try:
            expect_error(
                lambda: MODULE.write_json_atomic(output_parent / "plan.json", {"changed": False}),
                "output parent",
            )
        finally:
            MODULE.create_temporary_file = original_create_temporary_for_output
        check(not (output_outside / "plan.json").exists(), "a parent swap must never redirect plan output")
        check(not (moved_output_parent / "plan.json").exists(), "a rejected parent swap must not publish a plan")

        traversal_root = repo / "traversal-root"
        traversal_root.mkdir()
        traversal_link = traversal_root / "link"
        traversal_link.symlink_to(outside, target_is_directory=True)
        expect_error(
            lambda: MODULE.lexical_absolute(traversal_link / ".." / "target"),
            "parent traversal component",
        )

        fifo_repo = repo / "fifo-repo"
        fifo_repo.mkdir()
        os.mkfifo(fifo_repo / "CompletionLedger.md")
        expect_error(
            lambda: MODULE.read_existing_ledger(fifo_repo),
            "not a regular file",
        )
        os.mkfifo(fifo_repo / "projection.fifo")
        expect_error(
            lambda: MODULE.open_file_guard(fifo_repo / "projection.fifo", "projection"),
            "not a regular file",
        )

        guarded_input = repo / "guarded-input.json"
        guarded_input.write_text('{"version":1}\n', encoding="utf-8")
        guarded = MODULE.open_file_guard(guarded_input, "guarded input")
        original_read_descriptor_stable = MODULE.read_descriptor_stable

        def replace_guard_name_after_read(descriptor: int, path: Path, label: str):
            result = original_read_descriptor_stable(descriptor, path, label)
            if label == "guarded input":
                replacement = repo / "guarded-input-replacement.json"
                replacement.write_text('{"version":2}\n', encoding="utf-8")
                os.replace(replacement, guarded_input)
            return result

        MODULE.read_descriptor_stable = replace_guard_name_after_read
        try:
            expect_error(guarded.validate, "replaced during apply")
        finally:
            MODULE.read_descriptor_stable = original_read_descriptor_stable
            guarded.close()

        guarded_parent = repo / "guarded-parent"
        guarded_parent.mkdir()
        guarded_parent_input = guarded_parent / "projection.json"
        guarded_parent_input.write_text('{"version":1}\n', encoding="utf-8")
        parent_guard = MODULE.open_file_guard(guarded_parent_input, "parent-bound input")
        moved_guarded_parent = repo / "moved-guarded-parent"
        parent_swapped_during_read = False

        def replace_guard_parent_during_read(descriptor: int, path: Path, label: str):
            nonlocal parent_swapped_during_read
            if label == "parent-bound input" and not parent_swapped_during_read:
                parent_swapped_during_read = True
                guarded_parent.rename(moved_guarded_parent)
                guarded_parent.mkdir()
                guarded_parent_input.write_text('{"version":2}\n', encoding="utf-8")
            return original_read_descriptor_stable(descriptor, path, label)

        MODULE.read_descriptor_stable = replace_guard_parent_during_read
        try:
            expect_error(parent_guard.validate, "parent path changed")
        finally:
            MODULE.read_descriptor_stable = original_read_descriptor_stable
            parent_guard.close()

        snapshot_dir = repo / "snapshot-race"
        snapshot_dir.mkdir()
        snapshot_target = snapshot_dir / "target.md"
        snapshot_target.write_text(rendered, encoding="utf-8")
        snapshot_directory_fd = MODULE.open_directory(snapshot_dir)

        def replace_named_snapshot_after_read(descriptor: int, path: Path, label: str):
            result = original_read_descriptor_stable(descriptor, path, label)
            if label == "named snapshot race":
                replacement = snapshot_dir / "replacement.md"
                replacement.write_text(LEDGER.render_ledger([escaped, spaced]), encoding="utf-8")
                os.replace(replacement, snapshot_target)
            return result

        MODULE.read_descriptor_stable = replace_named_snapshot_after_read
        try:
            expect_error(
                lambda: MODULE.named_file_snapshot(
                    snapshot_directory_fd, snapshot_target.name, "named snapshot race"
                ),
                "while it was being read",
            )
        finally:
            MODULE.read_descriptor_stable = original_read_descriptor_stable
            os.close(snapshot_directory_fd)

        concurrent_output = repo / "concurrent-plan.json"
        concurrent_output.write_text('{"reviewed":true}\n', encoding="utf-8")
        original_create_temporary_output_race = MODULE.create_temporary_file
        output_raced = False

        def create_temporary_then_update_output(directory_fd: int, prefix: str, mode: int = 0o600):
            nonlocal output_raced
            result = original_create_temporary_output_race(directory_fd, prefix, mode)
            if prefix == concurrent_output.name and not output_raced:
                output_raced = True
                concurrent_output.write_text('{"concurrent":true}\n', encoding="utf-8")
            return result

        MODULE.create_temporary_file = create_temporary_then_update_output
        try:
            expect_error(
                lambda: MODULE.write_json_atomic(concurrent_output, {"generated": True}),
                "changed during publication",
            )
        finally:
            MODULE.create_temporary_file = original_create_temporary_output_race
        check(
            concurrent_output.read_text(encoding="utf-8") == '{"concurrent":true}\n',
            "plan output publication must preserve a concurrent regular-file update",
        )

        original_sync_output_race = MODULE.sync_directory
        for existing in (False, True):
            post_sync_output = repo / (
                "post-sync-existing-plan.json" if existing else "post-sync-absent-plan.json"
            )
            if existing:
                post_sync_output.write_text('{"reviewed":true}\n', encoding="utf-8")
            post_sync_writer_ran = False

            def replace_output_during_sync(directory_fd: int):
                nonlocal post_sync_writer_ran
                if not post_sync_writer_ran:
                    post_sync_writer_ran = True
                    replacement = repo / "post-sync-writer.json"
                    replacement.write_text('{"concurrent":true}\n', encoding="utf-8")
                    os.replace(replacement, post_sync_output)
                return original_sync_output_race(directory_fd)

            MODULE.sync_directory = replace_output_during_sync
            try:
                expect_error(
                    lambda: MODULE.write_json_atomic(post_sync_output, {"generated": True}),
                    "writer state was restored" if existing else "inspect target and recovery link",
                )
            finally:
                MODULE.sync_directory = original_sync_output_race
            check(
                post_sync_output.read_text(encoding="utf-8") == '{"concurrent":true}\n',
                "post-sync output validation must preserve a concurrent target replacement",
            )
            for recovery in repo.glob(f".{post_sync_output.name}.*"):
                recovery.unlink()
            post_sync_output.unlink()

        rollback_output = repo / "rollback-output.json"
        rollback_output.write_text('{"reviewed":true}\n', encoding="utf-8")
        os.chmod(rollback_output, 0o640)
        os.setxattr(rollback_output, "user.audit-output-test", b"reviewed-prior")
        original_sync_output_rollback = MODULE.sync_directory
        rollback_output_mutated = False

        def mutate_prior_output_then_fail_sync(directory_fd: int):
            nonlocal rollback_output_mutated
            if not rollback_output_mutated:
                rollback_output_mutated = True
                backup_names = [
                    name
                    for name in os.listdir(directory_fd)
                    if name.startswith(f".{rollback_output.name}.")
                ]
                check(len(backup_names) == 1, "output rollback fixture requires one prior-output backup")
                prior_backup = repo / backup_names[0]
                os.chmod(prior_backup, 0o600)
                os.setxattr(prior_backup, "user.audit-output-test", b"concurrent-change")
                raise OSError("injected output directory sync failure")
            return original_sync_output_rollback(directory_fd)

        MODULE.sync_directory = mutate_prior_output_then_fail_sync
        try:
            expect_error(
                lambda: MODULE.write_json_atomic(rollback_output, {"generated": True}),
                "no longer matches the reviewed prior hash, identity, and metadata",
            )
        finally:
            MODULE.sync_directory = original_sync_output_rollback
        check(
            rollback_output.stat().st_mode & 0o777 == 0o600
            and os.getxattr(rollback_output, "user.audit-output-test") == b"concurrent-change",
            "output rollback must preserve but refuse to misreport a changed prior inode",
        )
        rollback_output_recovery = list(repo.glob(f".{rollback_output.name}.*"))
        check(
            len(rollback_output_recovery) == 1,
            "uncertain output rollback must retain the rejected generated output for inspection",
        )
        rollback_output_recovery[0].unlink()
        rollback_output.unlink()

        rollback_metadata_dir = repo / "rollback-metadata"
        rollback_metadata_dir.mkdir()
        rollback_metadata_fd = MODULE.open_directory(rollback_metadata_dir)
        rollback_ledger = rollback_metadata_dir / MODULE.LEDGER_NAME
        rollback_backup_name = ".CompletionLedger.md.rollback"
        rollback_backup = rollback_metadata_dir / rollback_backup_name
        rollback_ledger.write_text(LEDGER.render_ledger([escaped, spaced]), encoding="utf-8")
        rollback_backup.write_text(LEDGER.render_ledger([escaped]), encoding="utf-8")
        os.chmod(rollback_backup, 0o640)
        os.setxattr(rollback_backup, "user.audit-ledger-test", b"reviewed-prior")
        prior_data, prior_identity, prior_metadata = MODULE.named_file_snapshot(
            rollback_metadata_fd,
            rollback_backup_name,
            "reviewed prior ledger",
        )
        published_data, published_identity, published_metadata = MODULE.named_file_snapshot(
            rollback_metadata_fd,
            MODULE.LEDGER_NAME,
            "published ledger",
        )
        original_exchange_for_metadata = MODULE.exchange_paths
        metadata_changed = False

        def change_prior_metadata_before_rollback_exchange(
            directory_fd: int, first: str, second: str
        ):
            nonlocal metadata_changed
            if not metadata_changed:
                metadata_changed = True
                os.chmod(rollback_backup, 0o600)
                os.setxattr(rollback_backup, "user.audit-ledger-test", b"concurrent-change")
            return original_exchange_for_metadata(directory_fd, first, second)

        MODULE.exchange_paths = change_prior_metadata_before_rollback_exchange
        try:
            expect_error(
                lambda: MODULE.rollback_existing_publication(
                    rollback_metadata_fd,
                    rollback_backup_name,
                    MODULE.sha256_bytes(prior_data),
                    prior_identity,
                    prior_metadata,
                    published_identity,
                    MODULE.sha256_bytes(published_data),
                    published_metadata,
                    RuntimeError("injected rollback"),
                ),
                "no longer matches the reviewed prior",
            )
        finally:
            MODULE.exchange_paths = original_exchange_for_metadata
            os.close(rollback_metadata_fd)
        check(
            rollback_ledger.stat().st_mode & 0o777 == 0o600
            and os.getxattr(rollback_ledger, "user.audit-ledger-test") == b"concurrent-change",
            "rollback must preserve but refuse to misreport a concurrently changed prior inode",
        )

        reports_dir = repo / "reports"
        reports_dir.mkdir()
        lead_report = reports_dir / "lead_reconciliation.md"
        lead_report.write_text("## Findings\nNo findings.\n", encoding="utf-8")
        (reports_dir / "rogue.md").write_text(
            "## Findings\n### P0 - Unverified injected candidate\n- Files: `src/rogue.py`\n- Gap: injected\n",
            encoding="utf-8",
        )
        source_path = repo / "src" / "calculate.py"
        source_path.parent.mkdir()
        source_path.write_text("def calculate_total(items):\n    return 42\n", encoding="utf-8")
        manifest_path = repo / "manifest.json"
        manifest = {
            "run_id": "run-report-race",
            "repo_root": str(repo),
            "reports_dir": str(reports_dir),
            "batches": [],
            "journey_audit": {"required": False},
            "lead_reconciliation": {"required": True, "report": "reports/lead_reconciliation.md"},
            "source_files": [
                {
                    "rel_path": "src/calculate.py",
                    "sha256": MODULE.sha256_bytes(source_path.read_bytes()),
                }
            ],
        }
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        (repo / "queue_complete.json").write_text("{}\n", encoding="utf-8")
        (repo / "excluded_files.json").write_text("[]\n", encoding="utf-8")
        (repo / "effort_ledger.json").write_text("{}\n", encoding="utf-8")
        report_names = MODULE.authorized_report_names(manifest)
        clean_consolidated = MERGE.merge_findings(reports_dir, report_names=report_names)
        check(clean_consolidated["ignored_unverified_reports"] == ["rogue.md"], "rogue reports must be excluded")
        clean_projection = MERGE.render_completion_ledger_projection(
            clean_consolidated,
            run_id=manifest["run_id"],
            repo_root=manifest["repo_root"],
            manifest_sha256=MODULE.sha256_file(manifest_path),
        )
        clean_projection["review_status"] = "complete"
        projection_path = repo / "projection.json"
        projection_path.write_text(json.dumps(clean_projection), encoding="utf-8")
        receipt_path = repo / "verification_receipt.json"

        def write_receipt(consolidated: dict) -> None:
            receipt_path.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "audit_kind": "full-repo-audit",
                        "run_id": manifest["run_id"],
                        "repo_root": manifest["repo_root"],
                        "manifest_sha256": MODULE.sha256_file(manifest_path),
                        "reports_dir": str(reports_dir),
                        "report_sha256": consolidated["report_sha256"],
                        "verifier_result_sha256": "0" * 64,
                    }
                ),
                encoding="utf-8",
            )

        write_receipt(clean_consolidated)

        ledger_path = repo / "CompletionLedger.md"
        ledger_path.unlink()
        original_audit_mode = MODULE.audit_verification_mode
        MODULE.audit_verification_mode = lambda *_args: ("verified", "0" * 64)
        try:
            clean_absent_plan = MODULE.build_plan(repo, manifest_path, reports_dir, projection_path)
            check(not clean_absent_plan["changed"], "a clean audit must not create an absent ledger")
            clean_absent_plan_path = repo / "clean-absent-plan.json"
            clean_absent_plan_path.write_text(json.dumps(clean_absent_plan), encoding="utf-8")
            reviewed_receipt_bytes = receipt_path.read_bytes()
            changed_receipt = json.loads(reviewed_receipt_bytes)
            changed_receipt["verifier_result_sha256"] = "1" * 64
            receipt_path.write_text(json.dumps(changed_receipt), encoding="utf-8")
            expect_error(
                lambda: MODULE.apply_plan(
                    repo,
                    manifest_path,
                    reports_dir,
                    projection_path,
                    clean_absent_plan_path,
                ),
                "plan is stale or malformed",
            )
            check(not ledger_path.exists(), "a changed receipt must invalidate apply before ledger creation")
            receipt_path.write_bytes(reviewed_receipt_bytes)
            reviewed_source_bytes = source_path.read_bytes()
            source_path.write_text("def calculate_total(items):\n    return 7\n", encoding="utf-8")
            expect_error(
                lambda: MODULE.apply_plan(
                    repo,
                    manifest_path,
                    reports_dir,
                    projection_path,
                    clean_absent_plan_path,
                ),
                "source changed after pass-only audit verification",
            )
            check(not ledger_path.exists(), "source drift must invalidate apply before ledger creation")
            source_path.write_bytes(reviewed_source_bytes)
            MODULE.apply_plan(repo, manifest_path, reports_dir, projection_path, clean_absent_plan_path)
            check(not ledger_path.exists(), "clean plan/apply must leave an absent ledger absent")

            ledger_path.write_text(rendered, encoding="utf-8")
            os.chmod(ledger_path, 0o640)
            os.setxattr(ledger_path, "user.audit-ledger-test", b"preserve-me")
            clean_existing_bytes = ledger_path.read_bytes()
            clean_existing_stat = ledger_path.stat()
            clean_existing_xattrs = {
                name: os.getxattr(ledger_path, name) for name in os.listxattr(ledger_path)
            }
            clean_existing_plan = MODULE.build_plan(repo, manifest_path, reports_dir, projection_path)
            check(not clean_existing_plan["changed"], "a clean audit must preserve an existing active ledger")
            clean_existing_plan_path = repo / "clean-existing-plan.json"
            clean_existing_plan_path.write_text(json.dumps(clean_existing_plan), encoding="utf-8")
            MODULE.apply_plan(repo, manifest_path, reports_dir, projection_path, clean_existing_plan_path)
            clean_after_stat = ledger_path.stat()
            check(ledger_path.read_bytes() == clean_existing_bytes, "clean plan/apply must preserve ledger bytes")
            check(
                (clean_after_stat.st_uid, clean_after_stat.st_gid, clean_after_stat.st_mode & 0o777)
                == (clean_existing_stat.st_uid, clean_existing_stat.st_gid, clean_existing_stat.st_mode & 0o777),
                "clean plan/apply must preserve ledger ownership and mode",
            )
            check(
                {name: os.getxattr(ledger_path, name) for name in os.listxattr(ledger_path)}
                == clean_existing_xattrs,
                "clean plan/apply must preserve ledger xattrs",
            )
        finally:
            MODULE.audit_verification_mode = original_audit_mode

        original_merge_findings = MERGE.merge_findings
        clean_report_bytes = lead_report.read_bytes()

        def merge_while_original_report_performs_aba(reports_path: Path, *, report_names=None):
            lead_report.write_text(
                "## Findings\nNo findings.\n\nA transient unreviewed replacement.\n",
                encoding="utf-8",
            )
            try:
                return original_merge_findings(reports_path, report_names=report_names)
            finally:
                lead_report.write_bytes(clean_report_bytes)

        MERGE.merge_findings = merge_while_original_report_performs_aba
        original_audit_mode = MODULE.audit_verification_mode
        MODULE.audit_verification_mode = lambda *_args: ("verified", "0" * 64)
        try:
            expect_error(
                lambda: MODULE.build_plan(repo, manifest_path, reports_dir, projection_path),
                "changed during apply",
            )
        finally:
            MODULE.audit_verification_mode = original_audit_mode
            MERGE.merge_findings = original_merge_findings
        check(
            lead_report.read_bytes() == clean_report_bytes,
            "A/B/A report-race fixture must restore the reviewed path bytes",
        )

        ledger_path.unlink()
        ledger_path.write_text(rendered, encoding="utf-8")
        snapshot = MODULE.read_existing_ledger(repo)
        ledger_path.write_text(LEDGER.render_ledger([escaped, spaced]), encoding="utf-8")
        directory_fd = MODULE.open_directory(repo)
        try:
            expect_error(
                lambda: MODULE.assert_ledger_snapshot(repo, directory_fd, snapshot.sha256, snapshot.identity),
                "changed after planning",
            )
        finally:
            os.close(directory_fd)

        lead_report.write_text(
            """## Findings
### P1 - Calculation is replaced by a fixed result
- Files: `src/calculate.py`
- Evidence: `calculate_total` returns literal `42` for every input.
- Expected behavior/standard: The public result must be calculated from its inputs.
- Gap: The implementation returns a fixed result instead of calculating.
- Suggested direction: Implement and verify the real calculation.
""",
            encoding="utf-8",
        )
        race_consolidated = MERGE.merge_findings(reports_dir, report_names=report_names)
        write_receipt(race_consolidated)
        race_projection = MERGE.render_completion_ledger_projection(
            race_consolidated,
            run_id=manifest["run_id"],
            repo_root=manifest["repo_root"],
            manifest_sha256=MODULE.sha256_file(manifest_path),
        )
        race_projection["review_status"] = "complete"
        race_candidate = race_projection["candidates"][0]
        race_candidate["disposition"] = "confirmed"
        race_candidate["disposition_reason"] = "Lead review confirmed the fixed return value is an unresolved implementation gap."
        race_candidate["ledger_row"].update(
            {
                "remaining_work": "[P1] Replace the fixed result with the real calculation in src/calculate.py.",
                "why_it_matters": "Every input currently produces the same incorrect public result.",
                "status": "Open",
                "verification": "Exercise varied inputs through calculate_total and assert calculated outputs.",
            }
        )
        projection_path.write_text(json.dumps(race_projection), encoding="utf-8")
        original_audit_mode = MODULE.audit_verification_mode
        MODULE.audit_verification_mode = lambda *_args: ("verified", "0" * 64)
        try:
            def reviewed_plan(name: str):
                plan = MODULE.build_plan(repo, manifest_path, reports_dir, projection_path)
                path = repo / f"{name}.json"
                path.write_text(json.dumps(plan), encoding="utf-8")
                return plan, path

            ledger_path.unlink()
            ledger_path.write_text(rendered, encoding="utf-8")
            os.chmod(ledger_path, 0o640)
            os.setxattr(ledger_path, "user.audit-ledger-test", b"preserve-through-replacement")
            original_stat = ledger_path.stat()
            original_xattrs = {
                name: os.getxattr(ledger_path, name) for name in os.listxattr(ledger_path)
            }
            successful_plan, successful_plan_path = reviewed_plan("successful-plan")
            check(successful_plan["changed"], "a confirmed finding must produce a ledger append plan")
            MODULE.apply_plan(repo, manifest_path, reports_dir, projection_path, successful_plan_path)
            successful_rows = LEDGER.parse_ledger(ledger_path.read_text(encoding="utf-8"))
            check(
                successful_rows == [escaped, MODULE.row_from_projection(race_candidate)],
                "successful apply must append the exact reviewed row",
            )
            replaced_stat = ledger_path.stat()
            check(
                (replaced_stat.st_uid, replaced_stat.st_gid, replaced_stat.st_mode & 0o777)
                == (original_stat.st_uid, original_stat.st_gid, original_stat.st_mode & 0o777),
                "replacement must preserve ownership and mode",
            )
            check(
                {name: os.getxattr(ledger_path, name) for name in os.listxattr(ledger_path)}
                == original_xattrs,
                "replacement must preserve ACL/xattr metadata",
            )

            ledger_path.unlink()
            ledger_path.write_text(LEDGER.render_ledger([escaped, spaced]), encoding="utf-8")
            race_plan, race_plan_path = reviewed_plan("pre-publication-race-plan")
            original_create_temporary = MODULE.create_temporary_file

            def create_temporary_then_drift(directory_fd: int, prefix: str, mode: int = 0o600):
                result = original_create_temporary(directory_fd, prefix, mode)
                if prefix == MODULE.LEDGER_NAME:
                    ledger_path.write_text(LEDGER.render_ledger([escaped, spaced, blocked]), encoding="utf-8")
                return result

            MODULE.create_temporary_file = create_temporary_then_drift
            try:
                expect_error(
                    lambda: MODULE.apply_plan(repo, manifest_path, reports_dir, projection_path, race_plan_path),
                    "changed after planning",
                )
            finally:
                MODULE.create_temporary_file = original_create_temporary
            check(
                LEDGER.parse_ledger(ledger_path.read_text(encoding="utf-8")) == [escaped, spaced, blocked],
                "a concurrent ledger edit after temporary-file creation must not be overwritten",
            )

            ledger_path.unlink()
            ledger_path.write_text(LEDGER.render_ledger([escaped, spaced]), encoding="utf-8")
            boundary_plan, boundary_plan_path = reviewed_plan("atomic-boundary-plan")
            original_exchange = MODULE.exchange_paths
            exchange_calls = 0

            def drift_at_atomic_exchange(directory_fd: int, first: str, second: str):
                nonlocal exchange_calls
                if exchange_calls == 0:
                    ledger_path.write_text(
                        LEDGER.render_ledger([escaped, spaced, blocked]), encoding="utf-8"
                    )
                exchange_calls += 1
                return original_exchange(directory_fd, first, second)

            MODULE.exchange_paths = drift_at_atomic_exchange
            try:
                expect_error(
                    lambda: MODULE.apply_plan(
                        repo, manifest_path, reports_dir, projection_path, boundary_plan_path
                    ),
                    "no longer matches the reviewed prior",
                )
            finally:
                MODULE.exchange_paths = original_exchange
            check(
                LEDGER.parse_ledger(ledger_path.read_text(encoding="utf-8"))
                == [escaped, spaced, blocked],
                "atomic exchange must detect and restore a concurrent boundary edit",
            )
            check(
                bool(list(repo.glob(".CompletionLedger.md.*"))),
                "uncertain boundary rollback must retain the rejected publication for inspection",
            )
            for backup in repo.glob(".CompletionLedger.md.*"):
                backup.unlink()

            ledger_path.unlink()
            ledger_path.write_text(LEDGER.render_ledger([escaped, spaced]), encoding="utf-8")
            post_sync_existing_plan, post_sync_existing_plan_path = reviewed_plan(
                "post-sync-existing-replacement-plan"
            )
            original_sync_directory = MODULE.sync_directory
            post_sync_existing_replaced = False
            post_sync_existing_writer_rows = [escaped, blocked]

            def replace_existing_ledger_during_sync(directory_fd: int):
                nonlocal post_sync_existing_replaced
                if not post_sync_existing_replaced:
                    post_sync_existing_replaced = True
                    writer_path = repo / "post-sync-existing-writer.md"
                    writer_path.write_text(
                        LEDGER.render_ledger(post_sync_existing_writer_rows),
                        encoding="utf-8",
                    )
                    os.replace(writer_path, ledger_path)
                return original_sync_directory(directory_fd)

            MODULE.sync_directory = replace_existing_ledger_during_sync
            try:
                expect_error(
                    lambda: MODULE.apply_plan(
                        repo,
                        manifest_path,
                        reports_dir,
                        projection_path,
                        post_sync_existing_plan_path,
                    ),
                    "concurrent writer was restored",
                )
            finally:
                MODULE.sync_directory = original_sync_directory
            check(
                LEDGER.parse_ledger(ledger_path.read_text(encoding="utf-8"))
                == post_sync_existing_writer_rows,
                "post-sync validation must preserve an existing-ledger replacement",
            )
            post_sync_existing_backups = list(repo.glob(".CompletionLedger.md.*"))
            check(
                post_sync_existing_backups,
                "post-sync existing-ledger replacement must retain the reviewed prior ledger",
            )
            for backup in post_sync_existing_backups:
                backup.unlink()

            ledger_path.unlink()
            ledger_path.write_text(LEDGER.render_ledger([escaped, spaced]), encoding="utf-8")
            fsync_plan, fsync_plan_path = reviewed_plan("fsync-failure-plan")
            publication_started = False
            sync_failed = False

            def exchange_then_mark(directory_fd: int, first: str, second: str):
                nonlocal publication_started
                result = original_exchange(directory_fd, first, second)
                publication_started = True
                return result

            def fail_first_post_publication_sync(directory_fd: int):
                nonlocal sync_failed
                if publication_started and not sync_failed:
                    sync_failed = True
                    raise OSError("injected post-publication directory fsync failure")
                return original_sync_directory(directory_fd)

            MODULE.exchange_paths = exchange_then_mark
            MODULE.sync_directory = fail_first_post_publication_sync
            try:
                expect_error(
                    lambda: MODULE.apply_plan(
                        repo, manifest_path, reports_dir, projection_path, fsync_plan_path
                    ),
                    "prior ledger was restored",
                )
            finally:
                MODULE.exchange_paths = original_exchange
                MODULE.sync_directory = original_sync_directory
            check(
                LEDGER.parse_ledger(ledger_path.read_text(encoding="utf-8")) == [escaped, spaced],
                "a post-publication fsync failure must restore the prior ledger",
            )

            ledger_path.unlink()
            ledger_path.write_text(LEDGER.render_ledger([escaped, spaced]), encoding="utf-8")
            rollback_race_plan, rollback_race_plan_path = reviewed_plan("rollback-writer-race-plan")
            exchange_call_count = 0
            rollback_publication_started = False
            rollback_sync_failed = False
            writer_rows = [escaped, blocked]

            def exchange_with_writer_at_rollback(directory_fd: int, first: str, second: str):
                nonlocal exchange_call_count, rollback_publication_started
                exchange_call_count += 1
                if exchange_call_count == 2:
                    writer_path = repo / "concurrent-writer-ledger.md"
                    writer_path.write_text(LEDGER.render_ledger(writer_rows), encoding="utf-8")
                    os.replace(writer_path, ledger_path)
                result = original_exchange(directory_fd, first, second)
                rollback_publication_started = True
                return result

            def fail_sync_to_enter_rollback(directory_fd: int):
                nonlocal rollback_sync_failed
                if rollback_publication_started and not rollback_sync_failed:
                    rollback_sync_failed = True
                    raise OSError("injected validation failure before rollback race")
                return original_sync_directory(directory_fd)

            MODULE.exchange_paths = exchange_with_writer_at_rollback
            MODULE.sync_directory = fail_sync_to_enter_rollback
            try:
                expect_error(
                    lambda: MODULE.apply_plan(
                        repo,
                        manifest_path,
                        reports_dir,
                        projection_path,
                        rollback_race_plan_path,
                    ),
                    "concurrent writer was restored",
                )
            finally:
                MODULE.exchange_paths = original_exchange
                MODULE.sync_directory = original_sync_directory
            check(
                LEDGER.parse_ledger(ledger_path.read_text(encoding="utf-8")) == writer_rows,
                "rollback must not delete a concurrent ledger replacement",
            )
            rollback_backups = list(repo.glob(".CompletionLedger.md.*"))
            check(rollback_backups, "uncertain rollback must retain the prior ledger for inspection")
            for backup in rollback_backups:
                backup.unlink()

            ledger_path.unlink()
            ledger_path.write_text(LEDGER.render_ledger([escaped, spaced]), encoding="utf-8")
            input_race_plan, input_race_plan_path = reviewed_plan("input-race-plan")
            original_projection_bytes = projection_path.read_bytes()
            input_drifted = False

            def exchange_then_drift_input(directory_fd: int, first: str, second: str):
                nonlocal input_drifted
                result = original_exchange(directory_fd, first, second)
                if not input_drifted:
                    input_drifted = True
                    projection_path.write_bytes(original_projection_bytes + b" \n")
                return result

            MODULE.exchange_paths = exchange_then_drift_input
            try:
                expect_error(
                    lambda: MODULE.apply_plan(
                        repo, manifest_path, reports_dir, projection_path, input_race_plan_path
                    ),
                    "prior ledger was restored",
                )
            finally:
                MODULE.exchange_paths = original_exchange
                projection_path.write_bytes(original_projection_bytes)
            check(
                LEDGER.parse_ledger(ledger_path.read_text(encoding="utf-8")) == [escaped, spaced],
                "late projection drift must roll back the ledger publication",
            )

            ledger_path.unlink()
            absent_plan, absent_plan_path = reviewed_plan("absent-ledger-failure-plan")
            check(absent_plan["before_sha256"] is None, "absent-ledger fixture must plan creation")
            absent_sync_failed = False

            def fail_absent_publication_sync(directory_fd: int):
                nonlocal absent_sync_failed
                if not absent_sync_failed:
                    absent_sync_failed = True
                    raise OSError("injected absent-ledger post-publication failure")
                return original_sync_directory(directory_fd)

            MODULE.sync_directory = fail_absent_publication_sync
            try:
                expect_error(
                    lambda: MODULE.apply_plan(
                        repo, manifest_path, reports_dir, projection_path, absent_plan_path
                    ),
                    "deliberately not unlinked",
                )
            finally:
                MODULE.sync_directory = original_sync_directory
            check(ledger_path.is_file(), "uncertain absent-ledger publication must not delete the ledger")
            check(
                MODULE.row_from_projection(race_candidate).id
                in {row.id for row in LEDGER.parse_ledger(ledger_path.read_text(encoding="utf-8"))},
                "uncertain absent-ledger publication must retain the reviewed row",
            )
            absent_recovery = list(repo.glob(".CompletionLedger.md.*"))
            check(absent_recovery, "uncertain absent-ledger publication must retain a recovery link")
            ledger_path.unlink()
            for recovery in absent_recovery:
                recovery.unlink()

            post_sync_absent_plan, post_sync_absent_plan_path = reviewed_plan(
                "post-sync-absent-replacement-plan"
            )
            post_sync_absent_replaced = False
            post_sync_absent_writer_rows = [escaped, blocked]

            def replace_absent_ledger_during_sync(directory_fd: int):
                nonlocal post_sync_absent_replaced
                if not post_sync_absent_replaced:
                    post_sync_absent_replaced = True
                    writer_path = repo / "post-sync-absent-writer.md"
                    writer_path.write_text(
                        LEDGER.render_ledger(post_sync_absent_writer_rows),
                        encoding="utf-8",
                    )
                    os.replace(writer_path, ledger_path)
                return original_sync_directory(directory_fd)

            MODULE.sync_directory = replace_absent_ledger_during_sync
            try:
                expect_error(
                    lambda: MODULE.apply_plan(
                        repo,
                        manifest_path,
                        reports_dir,
                        projection_path,
                        post_sync_absent_plan_path,
                    ),
                    "deliberately not unlinked",
                )
            finally:
                MODULE.sync_directory = original_sync_directory
            check(
                LEDGER.parse_ledger(ledger_path.read_text(encoding="utf-8"))
                == post_sync_absent_writer_rows,
                "post-sync validation must preserve an absent-ledger replacement",
            )
            post_sync_absent_recovery = list(repo.glob(".CompletionLedger.md.*"))
            check(
                post_sync_absent_recovery,
                "post-sync absent-ledger replacement must retain the generated recovery link",
            )
            ledger_path.unlink()
            for recovery in post_sync_absent_recovery:
                recovery.unlink()
        finally:
            MODULE.audit_verification_mode = original_audit_mode

    original_iter = MODULE.audit_verifier.iter_report_files
    original_verify = MODULE.audit_verifier.verify
    try:
        MODULE.audit_verifier.iter_report_files = lambda _paths: []
        verifier_result = {
            "expected_count": 1,
            "reported_count": 1,
            "expected_batch_count": 1,
            "report_files": [],
            "effort_ledger_provenance_note": "fixture",
            "effort_verification_scope": "ledger-recorded",
            "lead_reconciliation_contract_count": 2,
            "current_hash_check_skipped": False,
            "current_hash_mismatches": [
                {
                    "file": "CompletionLedger.md",
                    "expected": "a" * 64,
                    "current": "b" * 64,
                    "reason": "changed",
                }
            ],
            "lead_reconciliation_issues": [{"reason": "lead report is incomplete"}],
            "ok": False,
        }
        MODULE.audit_verifier.verify = lambda *_args, **_kwargs: verifier_result
        expect_error(
            lambda: MODULE.audit_verification_mode(
                Path("manifest.json"),
                [],
                {"verifier_result_sha256": "0" * 64},
            ),
            "did not pass",
        )
        verifier_result = {
            key: value for key, value in verifier_result.items() if key != "lead_reconciliation_issues"
        }
        verifier_result["future_blocking_gate"] = [{"reason": "new verifier issue"}]
        MODULE.audit_verifier.verify = lambda *_args, **_kwargs: verifier_result
        expect_error(
            lambda: MODULE.audit_verification_mode(
                Path("manifest.json"),
                [],
                {"verifier_result_sha256": "0" * 64},
            ),
            "did not pass",
        )
        verifier_result = {key: value for key, value in verifier_result.items() if key != "future_blocking_gate"}
        MODULE.audit_verifier.verify = lambda *_args, **_kwargs: verifier_result
        normalized = dict(verifier_result)
        normalized["current_hash_mismatches"] = []
        normalized["ok"] = True
        expected_digest = MODULE.audit_verifier.canonical_json_sha256(normalized)
        check(
            MODULE.audit_verification_mode(
                Path("manifest.json"),
                [],
                {"verifier_result_sha256": expected_digest},
            )[0]
            == "verified-post-ledger-only-drift",
            "the explicit ledger-only hash drift exception should remain supported",
        )
    finally:
        MODULE.audit_verifier.iter_report_files = original_iter
        MODULE.audit_verifier.verify = original_verify

    print("completion-ledger updater self-test ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
