from jaas_registry.index.models import Visibility
from jaas_registry.index.query import score_entry, search
from jaas_registry.index.store import InMemoryIndex
from jaas_registry.sharing.access import ANONYMOUS, CallerContext
from jaas_registry.sharing.grants import GrantStore
from jaas_registry.sharing.models import GranteeType, SharePermission
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

    def test_tenant_grant_makes_a_private_entry_visible_to_every_member_of_that_tenant(
        self, tmp_path
    ):
        private = make_entry(
            id="acme.text.private", visibility=Visibility.PRIVATE, owner_tenant="tnt_owner"
        )
        index = _index_with(private)
        grants = GrantStore(tmp_path)
        grants.create(
            skill_id="acme.text.private",
            grantee_type=GranteeType.TENANT,
            grantee_id="tnt_grantee",
            permission=SharePermission.READ,
            granted_by="usr_owner",
        )
        caller = CallerContext(user_id="usr_member", tenant_id="tnt_grantee")

        page = search(index, caller=caller, grants=grants)

        assert page.total == 1


class TestGrantLookupIsRequestScopedNotPerCandidate:
    """IMPLEMENTATION_PLAN.md Phase 3.2: ui-implementation-plan.md's risk
    register specified request-scoped memoization of grant lookups (not a
    cross-request cache — that carries real invalidate-on-revoke risk
    nothing here currently justifies). Precomputing the caller's full
    visible-skill-id set once via list_for_grantee(), instead of one
    list_for_skill() file read per non-public search candidate, is the
    actual fix — these tests prove the GrantStore call count stays fixed
    regardless of candidate count, and that results are unchanged."""

    def test_grant_store_is_queried_a_fixed_number_of_times_regardless_of_candidate_count(
        self, tmp_path, monkeypatch
    ):
        entries = [
            make_entry(
                id=f"acme.text.private{i}",
                visibility=Visibility.PRIVATE,
                owner_tenant="tnt_owner",
            )
            for i in range(25)
        ]
        index = _index_with(*entries)
        grants = GrantStore(tmp_path)
        for entry in entries:
            grants.create(
                skill_id=entry.id,
                grantee_type=GranteeType.USER,
                grantee_id="usr_grantee",
                permission=SharePermission.READ,
                granted_by="usr_owner",
            )
        caller = CallerContext(user_id="usr_grantee", tenant_id="tnt_other")

        call_count = 0
        original_list_for_skill = GrantStore.list_for_skill

        def counting_list_for_skill(self, skill_id):
            nonlocal call_count
            call_count += 1
            return original_list_for_skill(self, skill_id)

        monkeypatch.setattr(GrantStore, "list_for_skill", counting_list_for_skill)

        page = search(index, caller=caller, grants=grants)

        assert page.total == 25
        # The old per-candidate design would call list_for_skill once per
        # non-public candidate (25 calls); the fix replaces that with a
        # fixed, small number of list_for_grantee calls instead.
        assert call_count == 0

    def test_results_are_identical_to_the_per_skill_lookup_baseline(self, tmp_path):
        visible = make_entry(
            id="acme.text.visible", visibility=Visibility.PRIVATE, owner_tenant="tnt_owner"
        )
        hidden = make_entry(
            id="acme.text.hidden", visibility=Visibility.PRIVATE, owner_tenant="tnt_owner"
        )
        index = _index_with(visible, hidden)
        grants = GrantStore(tmp_path)
        grants.create(
            skill_id="acme.text.visible",
            grantee_type=GranteeType.USER,
            grantee_id="usr_grantee",
            permission=SharePermission.READ,
            granted_by="usr_owner",
        )
        caller = CallerContext(user_id="usr_grantee", tenant_id="tnt_other")

        page = search(index, caller=caller, grants=grants)

        assert [i.entry.id for i in page.items] == ["acme.text.visible"]


class TestUsageBasedRanking:
    """IMPLEMENTATION_PLAN.md Phase 3.1. usage_counts=None (the default)
    must be byte-identical to pre-Phase-3.1 behavior — every existing test
    above passes usage_counts nowhere and must keep passing unchanged."""

    def test_usage_counts_none_is_unchanged_from_before_this_feature(self):
        a = make_entry(id="acme.text.a", name="Zed")
        b = make_entry(id="acme.text.b", name="Alpha")
        index = _index_with(a, b)

        page = search(index)

        # No query, no usage_counts: falls back to the pre-existing
        # alphabetical-by-id tiebreak (score 0.0 for everyone).
        assert [i.entry.id for i in page.items] == ["acme.text.a", "acme.text.b"]

    def test_no_query_browse_sorts_by_usage_when_usage_counts_given(self):
        popular = make_entry(id="acme.text.popular", name="Zed")
        unpopular = make_entry(id="acme.text.unpopular", name="Alpha")
        index = _index_with(popular, unpopular)

        page = search(index, usage_counts={"acme.text.popular": 500, "acme.text.unpopular": 1})

        assert [i.entry.id for i in page.items] == [
            "acme.text.popular",
            "acme.text.unpopular",
        ]

    def test_unrecorded_skill_defaults_to_zero_usage_not_an_error(self):
        entry = make_entry(id="acme.text.new")
        index = _index_with(entry)

        page = search(index, usage_counts={"some.other.skill": 100})

        assert page.total == 1

    def test_usage_never_surfaces_a_result_that_does_not_match_the_query(self):
        """A high usage count must not leak an irrelevant result into a
        specific-query search — usage only re-ranks within real matches
        (and unconditionally for no-query browsing), never bypasses the
        query-match filter itself."""
        very_popular_but_irrelevant = make_entry(
            id="acme.text.popular", name="Completely Unrelated Thing"
        )
        matches_query = make_entry(id="acme.text.match", name="Special Widget")
        index = _index_with(very_popular_but_irrelevant, matches_query)

        page = search(
            index,
            query="Special Widget",
            usage_counts={"acme.text.popular": 10_000, "acme.text.match": 0},
        )

        assert [i.entry.id for i in page.items] == ["acme.text.match"]

    def test_usage_boosts_ranking_among_multiple_query_matches(self):
        low_usage = make_entry(id="acme.text.low", name="Widget Low")
        high_usage = make_entry(id="acme.text.high", name="Widget High")
        index = _index_with(low_usage, high_usage)

        page = search(
            index,
            query="widget",
            usage_counts={"acme.text.low": 0, "acme.text.high": 100},
        )

        assert [i.entry.id for i in page.items] == ["acme.text.high", "acme.text.low"]
