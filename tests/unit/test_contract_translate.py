"""Translating engine-internal dataclasses (core/models.py) into Contract Profiles.

This is the seam between the private on-disk format and the public typed Contract:
domain-model/spec.md says the Contract is the only public surface, so nothing outside
`kb.contract` should construct a `Profile` by hand from a `Person`/`Project`.
"""

from kb.contract.schema_pack import Profile
from kb.contract.translate import person_to_profile, project_to_profile
from kb.core.markdown import Section as CoreSection
from kb.core.models import (
    EntityKind,
    EntityRef,
    Person,
    Project,
    Resolution,
    ResolutionStatus,
    Wikilink,
)


class _FakeResolver:
    """A resolver stub satisfying the same `resolve_wikilink` shape `VaultIndex`
    exposes, without needing a full vault scan to test the translation seam.
    """

    def __init__(self, entities: dict[tuple[str, EntityKind], EntityRef]) -> None:
        self._entities = entities

    def resolve_wikilink(self, target: str, kind: EntityKind) -> Resolution:
        entity = self._entities.get((target, kind))
        if entity is None:
            return Resolution(ResolutionStatus.UNRESOLVED)
        return Resolution(ResolutionStatus.RESOLVED, entity=entity)


class DescribePersonToProfile:
    def it_gives_the_profile_a_ref_that_is_not_the_persons_file_path(self):
        person = Person(
            file="people/panand.md",
            frontmatter={},
            email=None,
            team=None,
            title=None,
            slack_id=None,
            aliases=[],
            project_links=[],
            sections=[],
        )

        profile = person_to_profile(person, _FakeResolver({}))

        assert profile.ref != person.file
        assert not profile.ref.endswith(".md")

    def it_translates_a_person_into_a_profile_with_matching_field_values(self):
        person = Person(
            file="people/panand.md",
            frontmatter={"email": "k@example.com", "team": "Research"},
            email="k@example.com",
            team="Research",
            title="ML Researcher",
            slack_id="U06EFAKE02",
            aliases=["Priya", "Priya Anand"],
            project_links=[
                Wikilink(raw_text="Sentinel", source_file="people/panand.md", source_line=5)
            ],
            sections=[CoreSection(heading="Current", level=2, lines=["ML researcher"])],
        )
        resolver = _FakeResolver(
            {
                ("Sentinel", EntityKind.PROJECT): EntityRef(
                    canonical="lumen-sentinel",
                    kind=EntityKind.PROJECT,
                    file="projects/lumen-sentinel.md",
                )
            }
        )

        profile = person_to_profile(person, resolver)

        assert isinstance(profile, Profile)
        assert profile.kind == "person"
        assert profile.ref == "people/panand"
        assert profile.fields["email"] == "k@example.com"
        assert profile.fields["team"] == "Research"
        assert profile.fields["title"] == "ML Researcher"
        assert profile.fields["slack_id"] == "U06EFAKE02"
        assert profile.fields["aliases"] == ["Priya", "Priya Anand"]
        assert profile.sections[0].heading == "Current"
        assert profile.sections[0].body == "ML researcher"
        assert [r.model_dump() for r in profile.relationships] == [
            {"name": "projects", "target": "projects/lumen-sentinel"}
        ]

    def it_translates_a_person_with_no_project_links_to_no_relationships(self):
        person = Person(
            file="people/elena.md",
            frontmatter={},
            email=None,
            team=None,
            title=None,
            slack_id=None,
            aliases=[],
            project_links=[],
            sections=[],
        )

        profile = person_to_profile(person, _FakeResolver({}))

        assert profile.relationships == []
        assert profile.sections == []

    def it_falls_back_to_the_raw_wikilink_text_when_a_link_does_not_resolve(self):
        person = Person(
            file="people/elena.md",
            frontmatter={},
            email=None,
            team=None,
            title=None,
            slack_id=None,
            aliases=[],
            project_links=[
                Wikilink(
                    raw_text="Some Dead Link", source_file="people/elena.md", source_line=1
                )
            ],
            sections=[],
        )

        profile = person_to_profile(person, _FakeResolver({}))

        assert [r.model_dump() for r in profile.relationships] == [
            {"name": "projects", "target": "Some Dead Link"}
        ]


class DescribeProjectToProfile:
    def it_translates_a_project_into_a_profile_with_matching_field_values(self):
        project = Project(
            file="projects/lumen-sentinel.md",
            frontmatter={"status": "active"},
            status="active",
            product_link=Wikilink(
                raw_text="LUMEN", source_file="projects/lumen-sentinel.md", source_line=1
            ),
            github="lumen-labs/lumen-sentinel",
            linear="SENT",
            aliases=["Sentinel"],
            people_links=[
                Wikilink(
                    raw_text="Priya Anand",
                    source_file="projects/lumen-sentinel.md",
                    source_line=3,
                )
            ],
            sections=[CoreSection(heading="Status", level=2, lines=["on track"])],
        )
        resolver = _FakeResolver(
            {
                ("LUMEN", EntityKind.PRODUCT): EntityRef(
                    canonical="lumen", kind=EntityKind.PRODUCT, file="products/lumen.md"
                ),
                ("Priya Anand", EntityKind.PERSON): EntityRef(
                    canonical="panand",
                    kind=EntityKind.PERSON,
                    file="people/panand.md",
                ),
            }
        )

        profile = project_to_profile(project, resolver)

        assert isinstance(profile, Profile)
        assert profile.kind == "project"
        assert profile.ref == "projects/lumen-sentinel"
        assert profile.fields["status"] == "active"
        assert profile.fields["github"] == "lumen-labs/lumen-sentinel"
        assert profile.fields["linear"] == "SENT"
        assert profile.fields["aliases"] == ["Sentinel"]
        assert profile.sections[0].heading == "Status"
        assert profile.sections[0].body == "on track"
        assert {"name": "product", "target": "products/lumen"} in [
            r.model_dump() for r in profile.relationships
        ]
        assert {"name": "people", "target": "people/panand"} in [
            r.model_dump() for r in profile.relationships
        ]

    def it_translates_a_project_with_no_product_link_to_only_people_relationships(self):
        project = Project(
            file="projects/atlas.md",
            frontmatter={},
            status=None,
            product_link=None,
            github=None,
            linear=None,
            aliases=[],
            people_links=[],
            sections=[],
        )

        profile = project_to_profile(project, _FakeResolver({}))

        assert profile.relationships == []
