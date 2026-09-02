from jaas_registry.authn.users import UserStore, derive_user_id


def test_find_or_create_creates_new_user(tmp_path):
    store = UserStore(tmp_path)

    user = store.find_or_create(
        google_sub="google-sub-1", email="a@example.com", name="Alice", picture="http://x/a.png"
    )

    assert user.id == derive_user_id("google-sub-1")
    assert store.get(user.id) == user
    assert store.find_by_google_sub("google-sub-1") == user


def test_find_or_create_is_idempotent_for_same_google_sub(tmp_path):
    store = UserStore(tmp_path)

    first = store.find_or_create(
        google_sub="sub-1", email="a@example.com", name="Alice", picture=None
    )
    second = store.find_or_create(
        google_sub="sub-1", email="a@example.com", name="Alice", picture=None
    )

    assert first.id == second.id


def test_find_or_create_refreshes_profile_fields_on_later_sign_in(tmp_path):
    store = UserStore(tmp_path)
    store.find_or_create(google_sub="sub-1", email="a@example.com", name="Alice", picture=None)

    updated = store.find_or_create(
        google_sub="sub-1", email="a@example.com", name="Alice Smith", picture="http://x/new.png"
    )

    assert updated.name == "Alice Smith"
    assert updated.picture == "http://x/new.png"
    assert store.get(updated.id).name == "Alice Smith"


def test_different_google_subs_never_collide(tmp_path):
    store = UserStore(tmp_path)

    a = store.find_or_create(google_sub="sub-a", email="a@example.com", name="A", picture=None)
    b = store.find_or_create(google_sub="sub-b", email="b@example.com", name="B", picture=None)

    assert a.id != b.id


def test_get_unknown_user_returns_none(tmp_path):
    store = UserStore(tmp_path)
    assert store.get("usr_does_not_exist") is None


def test_set_display_name_overrides_effective_name(tmp_path):
    store = UserStore(tmp_path)
    created = store.find_or_create(
        google_sub="sub-1", email="a@example.com", name="Alice", picture=None
    )
    assert created.effective_name == "Alice"

    updated = store.set_display_name(created.id, "Ali")

    assert updated is not None
    assert updated.display_name == "Ali"
    assert updated.effective_name == "Ali"
    assert store.get(created.id).effective_name == "Ali"


def test_set_display_name_none_resets_to_google_name(tmp_path):
    store = UserStore(tmp_path)
    created = store.find_or_create(
        google_sub="sub-1", email="a@example.com", name="Alice", picture=None
    )
    store.set_display_name(created.id, "Ali")

    reset = store.set_display_name(created.id, None)

    assert reset is not None
    assert reset.display_name is None
    assert reset.effective_name == "Alice"


def test_set_display_name_for_unknown_user_returns_none(tmp_path):
    store = UserStore(tmp_path)
    assert store.set_display_name("usr_does_not_exist", "Someone") is None


def test_find_or_create_preserves_display_name_override_across_sign_ins(tmp_path):
    store = UserStore(tmp_path)
    created = store.find_or_create(
        google_sub="sub-1", email="a@example.com", name="Alice", picture=None
    )
    store.set_display_name(created.id, "Ali")

    refreshed = store.find_or_create(
        google_sub="sub-1", email="a@example.com", name="Alice Smith", picture="http://x/new.png"
    )

    assert refreshed.name == "Alice Smith"
    assert refreshed.display_name == "Ali"
    assert refreshed.effective_name == "Ali"
