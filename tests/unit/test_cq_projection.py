"""Focused reliability tests for the deterministic local CQ projection."""

from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner

from kb.__main__ import cli
from kb.cq.projection.ledger import ProjectionLedger
from kb.cq.projection.lock import ProjectionLock, ProjectionLockError
from kb.cq.projection.models import (
    AccessClassification,
    LedgerRecord,
    ProjectionAction,
    ProjectionManifest,
    ProjectionOperation,
    ProjectionScope,
)
from kb.cq.projection.planner import build_plan
from kb.cq.projection.safety import ProjectionSafetyError
from kb.cq.projection.service import apply_manifest, verify


def _vault(tmp_path: Path, body: str = "# Ada\n\nPublic profile.\n") -> Path:
    root = tmp_path / "vault"
    (root / "people").mkdir(parents=True)
    (root / "people" / "ada.md").write_text(
        "---\naccess: public\naliases: [Ada Lovelace]\n---\n" + body,
        encoding="utf-8",
    )
    return root


def _target(tmp_path: Path) -> tuple[Path, dict[str, str]]:
    target = tmp_path / "cq.db"
    target.touch()
    return target.resolve(), {"CQ_LOCAL_DB_PATH": str(target.resolve())}


class FakeCQ:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str | None]] = []
        self.units: dict[str, dict] = {}
        self.next = 0

    def status(self) -> dict:
        self.calls.append(("status", None))
        return {"local": True}

    def propose(self, source) -> str:
        self.next += 1
        ku_id = f"ku-{self.next}"
        self.calls.append(("propose", source.key))
        self.units[ku_id] = {"id": ku_id, "detail": source.detail + "\n" + source.marker}
        return ku_id

    def stale(self, ku_id: str) -> None:
        self.calls.append(("stale", ku_id))
        self.units.pop(ku_id, None)

    def find_identity(self, identity_domain: str) -> dict[str, dict]:
        self.calls.append(("find", identity_domain))
        return self.units


class DescribePlan:
    def it_registers_plan_and_verify_commands(self):
        result = CliRunner().invoke(cli, ["cq", "projection", "--help"])

        assert result.exit_code == 0
        assert "plan" in result.output
        assert "verify" in result.output

    def it_writes_a_secure_unapproved_plan_through_the_cli(self, tmp_path, monkeypatch):
        root = _vault(tmp_path)
        target, _ = _target(tmp_path)
        output = tmp_path / "plan.json"
        monkeypatch.setattr("kb.__main__._projection_target", lambda: target)

        result = CliRunner().invoke(
            cli,
            [
                "cq",
                "projection",
                "plan",
                "--kb-root",
                str(root),
                "--ledger-path",
                str(tmp_path / "ledger.json"),
                "--output",
                str(output),
            ],
        )

        assert result.exit_code == 0
        manifest = ProjectionManifest.from_dict(__import__("json").loads(output.read_text()))
        assert manifest.approved is False
        assert output.stat().st_mode & 0o777 == 0o600

    def it_splits_long_records_and_adds_entity_and_alias_domains(self, tmp_path):
        root = _vault(tmp_path, "# Ada\n\n## Current\n\n" + ("fact\n\n" * 2_000))
        ledger = ProjectionLedger.open(tmp_path / "ledger.json")
        target, _ = _target(tmp_path)

        manifest = build_plan(
            kb_root=root,
            ledger=ledger,
            target_db=target,
            authorization_policy=None,
            scopes=(ProjectionScope.PEOPLE,),
        )

        assert len(manifest.operations) > 1
        assert all(len(item.source.detail) <= 7_000 for item in manifest.operations)
        assert "ada" in manifest.operations[0].source.domains
        assert "ada-lovelace" in manifest.operations[0].source.domains

    def it_requires_explicit_authorization_for_scope_default_internal(self, tmp_path):
        root = tmp_path / "vault"
        (root / "projects").mkdir(parents=True)
        (root / "projects" / "project.md").write_text("# Project\n", encoding="utf-8")
        ledger = ProjectionLedger.open(tmp_path / "ledger.json")
        target, _ = _target(tmp_path)

        with pytest.raises(ProjectionSafetyError):
            build_plan(
                kb_root=root,
                ledger=ledger,
                target_db=target,
                authorization_policy=None,
                scopes=(ProjectionScope.PROJECTS,),
            )

    def it_enforces_generated_cq_schema_limits_for_many_long_aliases(self, tmp_path):
        aliases = ", ".join(f"alias-{'x' * 100}-{index}" for index in range(20))
        root = tmp_path / "vault"
        (root / "people").mkdir(parents=True)
        (root / "people" / "ada.md").write_text(
            f"---\naccess: public\naliases: [{aliases}]\n---\n# Ada\n",
            encoding="utf-8",
        )
        ledger = ProjectionLedger.open(tmp_path / "ledger.json")
        target, _ = _target(tmp_path)

        source = (
            build_plan(
                kb_root=root,
                ledger=ledger,
                target_db=target,
                authorization_policy=None,
                scopes=(ProjectionScope.PEOPLE,),
            )
            .operations[0]
            .source
        )

        assert len(source.summary) <= 500
        assert len(source.detail) + len(source.marker) + 2 <= 8_000
        assert len(source.action) <= 2_000
        assert len(source.domains) <= 16
        assert all(len(domain) <= 64 for domain in source.domains)


class DescribeRecoveryAndVerification:
    def it_persists_pending_create_then_recovers_without_duplicate_propose(self, tmp_path):
        root = _vault(tmp_path)
        target, environment = _target(tmp_path)
        ledger = ProjectionLedger.open(tmp_path / "ledger.json")
        source = (
            build_plan(
                kb_root=root,
                ledger=ledger,
                target_db=target,
                authorization_policy=None,
                scopes=(ProjectionScope.PEOPLE,),
            )
            .operations[0]
            .source
        )
        manifest = ProjectionManifest(
            target_db=str(target),
            authorization_policy=None,
            scope_expectations={"people": [source.key]},
            operations=[ProjectionOperation(ProjectionAction.CREATE, source)],
        ).approve()
        cq = FakeCQ()

        apply_manifest(
            manifest=manifest,
            ledger=ledger,
            kb_root=root,
            target_db=target,
            environment=environment,
            cq=cq,
        )
        apply_manifest(
            manifest=manifest,
            ledger=ProjectionLedger.open(ledger.path),
            kb_root=root,
            target_db=target,
            environment=environment,
            cq=cq,
        )

        assert [call[0] for call in cq.calls].count("propose") == 1
        assert ledger.completions()[0].complete is False
        assert all(
            result.valid
            for result in verify(
                ledger=ledger,
                cq=cq,
                scopes=(ProjectionScope.PEOPLE,),
            )
        )
        assert ledger.completions()[0].complete is True

    def it_does_not_complete_scope_when_apply_cannot_retrieve_created_ku(self, tmp_path):
        root = _vault(tmp_path)
        target, environment = _target(tmp_path)
        ledger = ProjectionLedger.open(tmp_path / "ledger.json")
        manifest = build_plan(
            kb_root=root,
            ledger=ledger,
            target_db=target,
            authorization_policy=None,
            scopes=(ProjectionScope.PEOPLE,),
        ).approve()

        class NoRetrieveCQ(FakeCQ):
            def find_identity(self, identity_domain: str) -> dict[str, dict]:
                self.calls.append(("find", identity_domain))
                return {}

        apply_manifest(
            manifest=manifest,
            ledger=ledger,
            kb_root=root,
            target_db=target,
            environment=environment,
            cq=NoRetrieveCQ(),
        )

        completion = ledger.completions()[0]
        assert completion.active == 1
        assert completion.backfill_complete_at is None
        assert completion.complete is False

    def it_keeps_replacement_recoverable_after_each_cq_mutation(self, tmp_path):
        root = _vault(tmp_path)
        target, environment = _target(tmp_path)
        ledger = ProjectionLedger.open(tmp_path / "ledger.json")
        source = (
            build_plan(
                kb_root=root,
                ledger=ledger,
                target_db=target,
                authorization_policy=None,
                scopes=(ProjectionScope.PEOPLE,),
            )
            .operations[0]
            .source
        )
        ledger.put(
            LedgerRecord(
                scope=source.scope,
                source_path=source.source_path,
                fragment=source.fragment,
                source_fingerprint="old",
                classification=source.classification,
                identity_domain=source.identity_domain,
                marker="old",
                active_ku_ids=["ku-old"],
            )
        )
        ledger.save()
        manifest = ProjectionManifest(
            target_db=str(target),
            authorization_policy=None,
            scope_expectations={"people": [source.key]},
            operations=[ProjectionOperation(ProjectionAction.REPLACE, source, ["ku-old"])],
        ).approve()
        cq = FakeCQ()

        apply_manifest(
            manifest=manifest,
            ledger=ledger,
            kb_root=root,
            target_db=target,
            environment=environment,
            cq=cq,
        )

        reloaded = ProjectionLedger.open(ledger.path)
        record = reloaded.get(source.scope, source.source_path, source.fragment)
        assert record is not None
        assert record.active_ku_ids == ["ku-1"]
        assert record.replaced_ku_ids == ["ku-old"]
        assert reloaded.pending() == []

    def it_recovers_after_a_stale_failure_without_another_propose(self, tmp_path):
        root = _vault(tmp_path)
        target, environment = _target(tmp_path)
        ledger = ProjectionLedger.open(tmp_path / "ledger.json")
        source = (
            build_plan(
                kb_root=root,
                ledger=ledger,
                target_db=target,
                authorization_policy=None,
                scopes=(ProjectionScope.PEOPLE,),
            )
            .operations[0]
            .source
        )
        ledger.put(
            LedgerRecord(
                scope=source.scope,
                source_path=source.source_path,
                fragment=source.fragment,
                source_fingerprint="old",
                classification=source.classification,
                identity_domain=source.identity_domain,
                marker="old",
                active_ku_ids=["ku-old"],
            )
        )
        ledger.save()
        manifest = ProjectionManifest(
            target_db=str(target),
            authorization_policy=None,
            scope_expectations={"people": [source.key]},
            operations=[ProjectionOperation(ProjectionAction.REPLACE, source, ["ku-old"])],
        ).approve()

        class FailingCQ(FakeCQ):
            fail = True

            def stale(self, ku_id: str) -> None:
                if self.fail:
                    self.fail = False
                    raise RuntimeError("simulated stale failure")
                super().stale(ku_id)

        cq = FailingCQ()
        with pytest.raises(RuntimeError, match="simulated"):
            apply_manifest(
                manifest=manifest,
                ledger=ledger,
                kb_root=root,
                target_db=target,
                environment=environment,
                cq=cq,
            )

        pending = ProjectionLedger.open(ledger.path).pending()
        assert pending[0].created_ku_ids == ["ku-1"]

        apply_manifest(
            manifest=manifest,
            ledger=ProjectionLedger.open(ledger.path),
            kb_root=root,
            target_db=target,
            environment=environment,
            cq=cq,
        )

        assert [call[0] for call in cq.calls].count("propose") == 1

    def it_enforces_a_single_projection_run(self, tmp_path):
        path = tmp_path / "ledger.json"
        with ProjectionLock(path):
            with pytest.raises(ProjectionLockError):
                with ProjectionLock(path):
                    pass

    def it_rejects_invalid_identity_or_content_mapping(self, tmp_path):
        ledger = ProjectionLedger.open(tmp_path / "ledger.json")
        ledger.put(
            LedgerRecord(
                scope=ProjectionScope.PEOPLE,
                source_path="people/ada.md",
                fragment="overview-1",
                source_fingerprint="fingerprint",
                classification=AccessClassification.PUBLIC,
                identity_domain="kb-id-ada",
                marker="kb-projection:ada:fingerprint",
                active_ku_ids=["ku-1"],
            )
        )
        ledger.set_scope_expectations({"people": ["people:people/ada.md#overview-1"]})
        ledger.mark_scope_complete((ProjectionScope.PEOPLE,))
        cq = FakeCQ()
        cq.units["ku-1"] = {"id": "ku-1", "detail": "wrong marker"}

        result = verify(ledger=ledger, cq=cq, scopes=(ProjectionScope.PEOPLE,))
        assert ledger.completions()[0].complete is False
        assert result[0].valid is False

    def it_verifies_with_nested_insight_detail_marker(self, tmp_path):
        """Regression: CQ query results carry the marker inside insight.detail,
        not at a top-level key.  _unit_text must find it there.
        """
        ledger = ProjectionLedger.open(tmp_path / "ledger.json")
        ledger.put(
            LedgerRecord(
                scope=ProjectionScope.PEOPLE,
                source_path="people/ada.md",
                fragment="overview-1",
                source_fingerprint="fingerprint",
                classification=AccessClassification.PUBLIC,
                identity_domain="kb-id-ada",
                marker="kb-projection:ada:fingerprint",
                active_ku_ids=["ku-1"],
            )
        )
        ledger.set_scope_expectations({"people": ["people:people/ada.md#overview-1"]})
        ledger.mark_scope_complete((ProjectionScope.PEOPLE,))
        cq = FakeCQ()
        cq.units["ku-1"] = {
            "id": "ku-1",
            "insight": {
                "summary": "KB: Ada",
                "detail": "## Status\nSome status text.\nkb-projection:ada:fingerprint",
                "action": "Use this fact.",
            },
            # No top-level marker key exists — marker is only in insight.detail.
        }

        result = verify(ledger=ledger, cq=cq, scopes=(ProjectionScope.PEOPLE,))
        assert result[0].valid is True

        assert result[0].active_ku_ids == ["ku-1"]
        assert ledger.completions()[0].complete is True

    def it_returns_nonzero_when_cli_verification_finds_invalid_mapping(self, tmp_path, monkeypatch):
        target, _ = _target(tmp_path)
        ledger = ProjectionLedger.open(tmp_path / "ledger.json")
        ledger.put(
            LedgerRecord(
                scope=ProjectionScope.PEOPLE,
                source_path="people/ada.md",
                fragment="overview-1",
                source_fingerprint="fingerprint",
                classification=AccessClassification.PUBLIC,
                identity_domain="kb-id-ada",
                marker="kb-projection:ada:fingerprint",
                active_ku_ids=["ku-1"],
            )
        )
        ledger.save()
        ledger.set_scope_expectations({"people": ["people:people/ada.md#overview-1"]})
        monkeypatch.setattr("kb.__main__._projection_target", lambda: target)
        monkeypatch.setattr("kb.__main__.CQCli", lambda *args, **kwargs: FakeCQ())

        result = CliRunner().invoke(
            cli,
            [
                "cq",
                "projection",
                "verify",
                "--scope",
                "people",
                "--ledger-path",
                str(ledger.path),
            ],
        )

        assert result.exit_code == 1
        assert '"invalid": 1' in result.output

    def it_reports_uninitialized_empty_scope_as_incomplete(self, tmp_path):
        ledger = ProjectionLedger.open(tmp_path / "ledger.json")
        completion = next(
            item for item in ledger.completions() if item.scope is ProjectionScope.DECISIONS
        )

        assert completion.expected == 0
        assert completion.complete is False

    def it_rejects_canonical_content_changed_after_approval(self, tmp_path):
        root = _vault(tmp_path)
        target, environment = _target(tmp_path)
        ledger = ProjectionLedger.open(tmp_path / "ledger.json")
        planned = build_plan(
            kb_root=root,
            ledger=ledger,
            target_db=target,
            authorization_policy=None,
            scopes=(ProjectionScope.PEOPLE,),
        )
        manifest = planned.approve()
        (root / "people" / "ada.md").write_text(
            "---\naccess: public\n---\n# Ada\n\nChanged canonical fact.\n",
            encoding="utf-8",
        )
        cq = FakeCQ()

        with pytest.raises(ProjectionSafetyError, match="canonical"):
            apply_manifest(
                manifest=manifest,
                ledger=ledger,
                kb_root=root,
                target_db=target,
                environment=environment,
                cq=cq,
            )

        assert "propose" not in [call[0] for call in cq.calls]


@pytest.mark.parametrize(
    "mutation",
    [
        "content",
        "access",
        "fragment",
        "addition",
        "removal",
    ],
)
def test_apply_rejects_canonical_source_set_or_fragment_changes(tmp_path, mutation):
    root = _vault(tmp_path)
    target, environment = _target(tmp_path)
    ledger = ProjectionLedger.open(tmp_path / "ledger.json")
    manifest = build_plan(
        kb_root=root,
        ledger=ledger,
        target_db=target,
        authorization_policy=None,
        scopes=(ProjectionScope.PEOPLE,),
    ).approve()
    source_path = root / "people" / "ada.md"
    if mutation == "content":
        source_path.write_text("---\naccess: public\n---\n# Ada\n\nChanged.\n", encoding="utf-8")
    elif mutation == "access":
        source_path.write_text(
            "---\naccess: internal\n---\n# Ada\n\nPublic profile.\n", encoding="utf-8"
        )
    elif mutation == "fragment":
        source_path.write_text(
            "---\naccess: public\n---\n# Ada\n\n## Current\n\nPublic profile.\n",
            encoding="utf-8",
        )
    elif mutation == "addition":
        (root / "people" / "new.md").write_text(
            "---\naccess: public\n---\n# New\n",
            encoding="utf-8",
        )
    else:
        source_path.unlink()
    cq = FakeCQ()

    with pytest.raises(ProjectionSafetyError):
        apply_manifest(
            manifest=manifest,
            ledger=ledger,
            kb_root=root,
            target_db=target,
            environment=environment,
            cq=cq,
        )

    assert "propose" not in [call[0] for call in cq.calls]


class DescribeSafetyAndApproval:
    def it_uses_explicit_public_metadata_not_identifier_regexes(self, tmp_path):
        root = _vault(tmp_path, "# Ada\n\nContact: ada@example.test\n")
        ledger = ProjectionLedger.open(tmp_path / "ledger.json")
        target, _ = _target(tmp_path)

        manifest = build_plan(
            kb_root=root,
            ledger=ledger,
            target_db=target,
            authorization_policy=None,
            scopes=(ProjectionScope.PEOPLE,),
        )

        assert manifest.operations[0].source.classification is AccessClassification.PUBLIC

    def it_rejects_any_credential_environment_variable(self, tmp_path):
        from kb.cq.projection.safety import checked_target

        target, environment = _target(tmp_path)
        environment["UNRELATED_API_KEY"] = "secret"

        with pytest.raises(ProjectionSafetyError):
            checked_target(target, environment)

    def it_approval_digest_rejects_post_approval_manifest_edits(self, tmp_path):
        root = _vault(tmp_path)
        ledger = ProjectionLedger.open(tmp_path / "ledger.json")
        target, _ = _target(tmp_path)
        manifest = build_plan(
            kb_root=root,
            ledger=ledger,
            target_db=target,
            authorization_policy=None,
            scopes=(ProjectionScope.PEOPLE,),
        ).approve()
        data = manifest.to_dict()
        data["operations"][0]["source"]["detail"] = "changed after approval"

        edited = ProjectionManifest.from_dict(data)

        assert edited.approved is False

    def it_passes_only_minimal_environment_to_cq_child(self, tmp_path):
        from subprocess import CompletedProcess

        from kb.cq.projection.cq_cli import CQCli

        target, _ = _target(tmp_path)
        executable = tmp_path / "cq"
        executable.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        executable.chmod(0o755)
        observed = {}

        def runner(command, **kwargs):
            observed.update(kwargs["env"])
            return CompletedProcess(command, 0, '{"data": {}}', "")

        CQCli(
            target,
            executable=str(executable),
            environment={"HOME": "/tmp/home", "PATH": "/custom", "UNRELATED_API_KEY": "x"},
            runner=runner,
        ).status()

        assert observed == {
            "HOME": "/tmp/home",
            "LANG": "C",
            "PATH": str(executable.parent),
            "CQ_LOCAL_DB_PATH": str(target),
        }

    def it_executes_fake_cq_from_a_non_system_path(self, tmp_path, monkeypatch):
        from kb.cq.projection.cq_cli import CQCli

        target, _ = _target(tmp_path)
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        executable = bin_dir / "cq"
        executable.write_text("#!/bin/sh\nprintf '{\"data\": {}}'\n", encoding="utf-8")
        executable.chmod(0o755)
        monkeypatch.setenv("PATH", str(bin_dir))

        CQCli(target).status()
