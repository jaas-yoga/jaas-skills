from jaas_registry.authn.github_connections import GitHubConnectionStore


def test_get_returns_none_when_missing(tmp_path):
    store = GitHubConnectionStore(tmp_path)
    assert store.get("tnt_1") is None


def test_put_then_get_round_trips(tmp_path):
    store = GitHubConnectionStore(tmp_path)
    connection = store.put(
        tenant_id="tnt_1",
        access_token="gho_secret",
        github_login="octocat",
        github_avatar_url="https://avatars.example/octocat.png",
        connected_by="usr_1",
    )

    fetched = store.get("tnt_1")

    assert fetched == connection
    assert fetched.github_login == "octocat"
    assert fetched.access_token == "gho_secret"


def test_put_is_isolated_per_tenant(tmp_path):
    store = GitHubConnectionStore(tmp_path)
    store.put(
        tenant_id="tnt_1",
        access_token="a",
        github_login="alice-gh",
        github_avatar_url=None,
        connected_by="usr_1",
    )

    assert store.get("tnt_2") is None


def test_put_overwrites_an_existing_connection(tmp_path):
    store = GitHubConnectionStore(tmp_path)
    store.put(
        tenant_id="tnt_1",
        access_token="old",
        github_login="old-login",
        github_avatar_url=None,
        connected_by="usr_1",
    )
    store.put(
        tenant_id="tnt_1",
        access_token="new",
        github_login="new-login",
        github_avatar_url=None,
        connected_by="usr_2",
    )

    fetched = store.get("tnt_1")
    assert fetched.access_token == "new"
    assert fetched.github_login == "new-login"


def test_delete_returns_false_when_missing(tmp_path):
    store = GitHubConnectionStore(tmp_path)
    assert store.delete("tnt_1") is False


def test_delete_removes_the_connection(tmp_path):
    store = GitHubConnectionStore(tmp_path)
    store.put(
        tenant_id="tnt_1",
        access_token="a",
        github_login="alice-gh",
        github_avatar_url=None,
        connected_by="usr_1",
    )

    assert store.delete("tnt_1") is True
    assert store.get("tnt_1") is None
