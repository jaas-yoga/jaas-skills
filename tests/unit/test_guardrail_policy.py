import pytest

from jaas_registry.common.errors import JaasError
from jaas_registry.guardrails.policy import GuardrailPolicyStore, default_policy
from tests.fixtures.fake_guardrails_client import FAKE_CATALOG

CATALOG = FAKE_CATALOG
MANDATORY_IDS = {d.id for d in CATALOG if d.mandatory}
DEFAULT_ENABLED_CONFIGURABLE_IDS = {d.id for d in CATALOG if not d.mandatory and d.default_enabled}


def test_default_policy_enables_mandatory_and_default_enabled_ids():
    policy = default_policy("tnt_1", CATALOG)
    assert MANDATORY_IDS <= policy.enabled_check_ids
    assert DEFAULT_ENABLED_CONFIGURABLE_IDS <= policy.enabled_check_ids


def test_store_get_falls_back_to_default_when_no_file_exists(tmp_path):
    store = GuardrailPolicyStore(tmp_path)
    policy = store.get("tnt_1", CATALOG)
    assert policy == default_policy("tnt_1", CATALOG)


def test_store_put_then_get_round_trips(tmp_path):
    store = GuardrailPolicyStore(tmp_path)
    ids = frozenset({"pii-pattern-scan"})
    store.put(tenant_id="tnt_1", enabled_check_ids=ids, catalog=CATALOG)

    fetched = store.get("tnt_1", CATALOG)
    assert fetched.enabled_check_ids == ids


def test_store_put_silently_drops_mandatory_ids(tmp_path):
    store = GuardrailPolicyStore(tmp_path)
    ids = frozenset({"secret-scan", "pii-pattern-scan"})
    result = store.put(tenant_id="tnt_1", enabled_check_ids=ids, catalog=CATALOG)

    assert "secret-scan" not in result.enabled_check_ids
    assert "pii-pattern-scan" in result.enabled_check_ids


def test_store_put_rejects_unknown_id(tmp_path):
    store = GuardrailPolicyStore(tmp_path)
    with pytest.raises(JaasError, match="unknown guardrail check id"):
        store.put(
            tenant_id="tnt_1", enabled_check_ids=frozenset({"not-a-real-check"}), catalog=CATALOG
        )


def test_store_is_isolated_per_tenant(tmp_path):
    store = GuardrailPolicyStore(tmp_path)
    store.put(tenant_id="tnt_1", enabled_check_ids=frozenset({"pii-pattern-scan"}), catalog=CATALOG)
    other = store.get("tnt_2", CATALOG)
    assert other == default_policy("tnt_2", CATALOG)
