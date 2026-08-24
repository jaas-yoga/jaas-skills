from jaas_registry.authn.pat import PatStore


def test_create_and_get(tmp_path):
    store = PatStore(tmp_path)

    pat = store.create(owner_user="usr_1", name="laptop CLI", ttl_seconds=3600)

    assert pat.id.startswith("pat_")
    assert store.get(pat.id) == pat


def test_list_for_user_only_returns_that_users_tokens(tmp_path):
    store = PatStore(tmp_path)
    store.create(owner_user="usr_1", name="a", ttl_seconds=3600)
    store.create(owner_user="usr_2", name="b", ttl_seconds=3600)

    tokens = store.list_for_user("usr_1")

    assert len(tokens) == 1
    assert tokens[0].name == "a"


def test_revoke_removes_the_token(tmp_path):
    store = PatStore(tmp_path)
    pat = store.create(owner_user="usr_1", name="a", ttl_seconds=3600)

    revoked = store.revoke(pat_id=pat.id, owner_user="usr_1")

    assert revoked is True
    assert store.get(pat.id) is None


def test_revoke_by_a_different_user_fails_and_does_not_delete(tmp_path):
    store = PatStore(tmp_path)
    pat = store.create(owner_user="usr_1", name="a", ttl_seconds=3600)

    revoked = store.revoke(pat_id=pat.id, owner_user="usr_2")

    assert revoked is False
    assert store.get(pat.id) is not None


def test_revoke_unknown_token_returns_false(tmp_path):
    store = PatStore(tmp_path)
    assert store.revoke(pat_id="pat_ghost", owner_user="usr_1") is False
