"""Client-side Sigstore keyless signing — jaasctl release's counterpart to
signing.py's dev-RSA sign_digest, used only on the CI/OIDC release path
(cli.py::cmd_release, when --oidc-token is given).

Design ref: design.md §7.1 ("Signature produced through Cosign/Sigstore").
Signing happens here, in the CI runner that holds the ambient OIDC
identity — never on the registry server, which only ever verifies (see
sigstore_trust.py). This mirrors how Sigstore/Trusted Publishing is used
for npm/PyPI: the party with the real identity signs, the registry
verifies against Fulcio/Rekor's public transparency log, no long-lived
secret changes hands either way.
"""

from __future__ import annotations

from sigstore.hashes import HashAlgorithm, Hashed
from sigstore.models import ClientTrustConfig
from sigstore.oidc import IdentityToken, detect_credential
from sigstore.sign import SigningContext


def detect_ambient_identity_token() -> IdentityToken | None:
    """None means no supported CI provider's ambient OIDC identity was
    found (sigstore-python's own detection — GitHub Actions, GitLab CI,
    Buildkite, CircleCI as of this writing). cli.py treats that as a hard
    failure on the --oidc-token path, not a silent fallback."""
    raw_token = detect_credential()
    if raw_token is None:
        return None
    return IdentityToken(raw_token)


def sign_digest_with_sigstore(digest: str, identity_token: IdentityToken) -> str:
    """Returns the resulting Bundle (Fulcio cert chain + signature + Rekor
    log entry) serialized as JSON — attached to ReleaseRequest.sigstoreBundle
    for the registry to verify. `digest` is the same "sha256:<hex>" string
    artifact/packaging.py::compute_digest produces; signs that exact digest,
    not a fresh hash of the archive, so client and server agree on what was
    actually signed even if archive-building details ever drift.
    """
    algo, hex_digest = digest.split(":", 1)
    hashed = Hashed(
        algorithm=HashAlgorithm[_ALGORITHM_NAMES[algo]], digest=bytes.fromhex(hex_digest)
    )
    signing_ctx = SigningContext.from_trust_config(ClientTrustConfig.production())
    with signing_ctx.signer(identity_token) as signer:
        bundle = signer.sign_artifact(hashed)
    return bundle.to_json()


# compute_digest only ever produces "sha256:..." today (artifact/packaging.py) —
# this mapping exists so a future second algorithm is a one-line addition
# here, not a silent KeyError deep in this function.
_ALGORITHM_NAMES = {"sha256": "SHA2_256"}
