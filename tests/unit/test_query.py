from rune_registry.index.models import Visibility
from rune_registry.index.query import score_entry, search
from rune_registry.index.store import InMemoryIndex
from rune_registry.sharing.access import ANONYMOUS, CallerContext
from rune_registry.sharing.grants import GrantStore
from rune_registry.sharing.models import GranteeType, SharePermission
from tests.fixtures.index_entries import make_entry


def _index_with(*entries):
    index = InMemoryIndex()
    for e in entries:
        index.put(e)
    return index


def test_exact_id_match_scores_highest():
    exact = make_entry(id="acme.text.summarizer", name="Summarizer", tags=())
    other = make_entry(id="acme.text.other", name="Other thing", description="mentions summarizer")
    index = _index_with(exact, other)

    page = search(index, query="acme.text.summarizer")
    assert page.items[0].entry.id == "acme.text.summarizer"
    assert page.items[0].score == 1.0


def test_query_with_no_match_excludes_entry():
    index = _index_with(make_entry())
    page = search(index, query="nothing-matches-this-at-all")
    assert page.items == []
    assert page.total == 0


def test_category_filter():
    nlp = make_entry(id="acme.text.summarizer", category="nlp")
    vision = make_entry(id="acme.vision.detector", category="vision")
    index = _index_with(nlp, vision)

    page = search(index, category="vision")
    assert [i.entry.id for i in page.items] == ["acme.vision.detector"]


def test_tags_filter_requires_all_tags_present():
    entry = make_entry(tags=("summarization", "nlp"))
    index = _index_with(entry)

    assert search(index, tags=["summarization"]).total == 1
    assert search(index, tags=["summarization", "nlp"]).total == 1
    assert search(index, tags=["summarization", "vision"]).total == 0


def test_runtime_filter_excludes_incompatible():
    entry = make_entry(runtime_families=("python",), runtime_ranges={"python": ">=3.10.0,<4.0.0"})
    index = _index_with(entry)

    assert search(index, runtime="python").total == 1
    assert search(index, runtime="node").total == 0


def test_pagination_is_deterministic_and_stable():
    entries = [make_entry(id=f"acme.a.skill{i:02d}") for i in range(5)]
    index = _index_with(*entries)

    page1 = search(index, page=1, page_size=2)
    page2 = search(index, page=2, page_size=2)
    assert [i.entry.id for i in page1.items] == ["acme.a.skill00", "acme.a.skill01"]
    assert [i.entry.id for i in page2.items] == ["acme.a.skill02", "acme.a.skill03"]
    assert page1.total == 5
    assert page1.next_page_token == "2"


def test_last_page_has_no_next_token():
    entries = [make_entry(id=f"acme.a.skill{i:02d}") for i in range(3)]
    index = _index_with(*entries)
    page = search(index, page=2, page_size=2)
    assert [i.entry.id for i in page.items] == ["acme.a.skill02"]
    assert page.next_page_token is None


def test_score_entry_empty_query_is_zero():
    assert score_entry(make_entry(), "") == 0.0


def test_version_constraint_with_no_matching_version_excludes_skill():
    index = _index_with(make_entry(version="1.0.0"))
    page = search(index, version_constraint=">=2.0.0")
    assert page.total == 0


def test_score_entry_weights_stack_across_fields():
    entry = make_entry(
        id="acme.text.summarizer",
        name="platform",
        owner_team="platform",
        tags=("platform",),
        category="platform",
        description="platform tool",
    )
    # a query matching multiple weighted fields should out-score one matching fewer
    assert score_entry(entry, "platform") > score_entry(entry, "nlp")


class TestVisibilityFilter:
    """ui-design.md §5.4 applied at the search layer."""

    def test_anonymous_caller_only_sees_public_entries(self):
        public = make_entry(id="acme.text.public", visibility=Visibility.PUBLIC)
        private = make_entry(id="acme.text.private", visibility=Visibility.PRIVATE)
        index = _index_with(public, private)

        page = search(index, caller=ANONYMOUS)

        assert [i.entry.id for i in page.items] == ["acme.text.public"]

    def test_default_caller_matches_pre_existing_no_auth_behavior(self):
        """search() with no caller/grants args at all (every pre-Phase-2 call
        site) must behave exactly as it did before the visibility model."""
        entry = make_entry()  # defaults to PUBLIC
        index = _index_with(entry)

        page = search(index)

        assert page.total == 1

    def test_owning_tenant_member_sees_their_own_private_entry(self):
        private = make_entry(
            id="acme.text.private", visibility=Visibility.PRIVATE, owner_tenant="tnt_1"
        )
        index = _index_with(private)
        caller = CallerContext(user_id="usr_1", tenant_id="tnt_1")

        page = search(index, caller=caller)

        assert page.total == 1

    def test_grant_makes_a_private_entry_visible_to_its_grantee(self, tmp_path):
        private = make_entry(
            id="acme.text.private", visibility=Visibility.PRIVATE, owner_tenant="tnt_owner"
        )
        index = _index_with(private)
        grants = GrantStore(tmp_path)
        grants.create(
            skill_id="acme.text.private",
            grantee_type=GranteeType.USER,
            grantee_id="usr_grantee",
            permission=SharePermission.READ,
            granted_by="usr_owner",
        )
        caller = CallerContext(user_id="usr_grantee", tenant_id="tnt_other")

        page = search(index, caller=caller, grants=grants)

        assert page.total == 1

    def test_unrelated_caller_never_sees_a_private_entry_even_with_other_filters_matching(self):
        private = make_entry(
            id="acme.text.private",
            category="nlp",
            visibility=Visibility.PRIVATE,
            owner_tenant="tnt_owner",
        )
        index = _index_with(private)
        caller = CallerContext(user_id="usr_unrelated", tenant_id="tnt_unrelated")

        page = search(index, category="nlp", caller=caller)

        assert page.total == 0
