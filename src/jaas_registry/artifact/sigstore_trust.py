"""Sigstore trust policy — verifies a keyless-signed CI release's bundle
against Fulcio's certificate chain and Rekor's transparency log.

Deliberately separate from artifact/trust.py's dev-RSA TrustPolicy, not a
modification of it: the two signature formats are structurally
incompatible (base64 RSA-PSS bytes vs. a Sigstore Bundle JSON object), and
this one is CI-release-only — see IMPLEMENTATION_PLAN.md Phase 1.2 for why
both stay supported indefinitely, not just during a migration window.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import Protocol

from sigstore.hashes import HashAlgorithm, Hashed
from sigstore.models import Bundle
from sigstore.verify import Verifier
from sigstore.verify.policy import OIDCIssuer, VerificationPolicy


class ArtifactVerifier(Protocol):
    """Structural subset of sigstore.verify.Verifier actually used here —
    lets tests inject a fake instead of the real thing, which does real
    network I/O (fetches Sigstore's TUF-distributed trust root) even just
    to construct via Verifier.production()."""

    def verify_artifact(
        self, input_: Hashed, bundle: Bundle, policy: VerificationPolicy
    ) -> None: ...


@dataclass
class SigstoreTrustPolicy:
    verifier: ArtifactVerifier
    identity_policy: VerificationPolicy

    def verify(self, digest: str, signature: str) -> bool:
        """`signature` here is the Sigstore Bundle, JSON-serialized (not a
        base64 signature blob like TrustPolicy.verify) — same method name
        and (digest, signature) -> bool shape as TrustPolicy purely so
        verify.py's dispatch logic can treat both uniformly."""
        try:
            bundle = Bundle.from_json(signature.encode())
        except Exception:
            return False
        algo, hex_digest = digest.split(":", 1)
        hashed = Hashed(
            algorithm=HashAlgorithm[_ALGORITHM_NAMES.get(algo, "SHA2_256")],
            digest=bytes.fromhex(hex_digest),
        )
        try:
            self.verifier.verify_artifact(hashed, bundle, self.identity_policy)
            return True
        except Exception:
            return False


@lru_cache(maxsize=8)
def load_sigstore_trust_policy(*, identity_issuer: str) -> SigstoreTrustPolicy:
    """The real factory used in production — constructs a Verifier against
    Sigstore's public-good instance. Deliberately not called at app
    startup (api/app.py's create_app() never touches this module at all)
    and deliberately memoized: Verifier.production() does real network I/O
    (fetches Sigstore's TUF trust root), so paying that cost on every
    release/high-assurance download would be a real latency/reliability
    regression — same reasoning as semver_resolver.py's _parse_version
    cache. `maxsize=8` is generous headroom for what's realistically one
    or two distinct identity_issuer values per deployment, ever."""
    return SigstoreTrustPolicy(
        verifier=Verifier.production(), identity_policy=OIDCIssuer(identity_issuer)
    )


_ALGORITHM_NAMES = {"sha256": "SHA2_256"}
