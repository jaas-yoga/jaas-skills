"""Trust policy: the registry's set of trusted signer public keys.

Design ref: design.md §7.1 ("Registry verifies signature against organizational
trust policy"), §7.2, implementation-plan.md Phase 2 task 3.

Deliberately separate from signing.py: the registry verifies against configured
trusted keys, never by calling back into the signer.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass, field
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

_PADDING = padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=padding.PSS.MAX_LENGTH)


@dataclass
class TrustPolicy:
    trusted_public_keys_pem: list[bytes] = field(default_factory=list)

    def verify(self, digest: str, signature_b64: str) -> bool:
        try:
            signature = base64.b64decode(signature_b64)
        except Exception:
            return False
        for pem in self.trusted_public_keys_pem:
            public_key = serialization.load_pem_public_key(pem)
            try:
                public_key.verify(signature, digest.encode(), _PADDING, hashes.SHA256())
                return True
            except InvalidSignature:
                continue
        return False


def load_trust_policy(policy_dir: Path) -> TrustPolicy:
    """Load trusted signer public keys from `<policy_dir>/trusted_keys/*.pem`."""
    keys_dir = policy_dir / "trusted_keys"
    if not keys_dir.is_dir():
        return TrustPolicy(trusted_public_keys_pem=[])
    return TrustPolicy(
        trusted_public_keys_pem=[p.read_bytes() for p in sorted(keys_dir.glob("*.pem"))]
    )


def ensure_key_registered(policy_dir: Path, public_key_pem: bytes, *, name: str = "ci") -> None:
    """Idempotently registers a signer's public key as trusted, so subsequent
    `load_trust_policy` calls (possibly from a different process) pick it up."""
    keys_dir = policy_dir / "trusted_keys"
    keys_dir.mkdir(parents=True, exist_ok=True)
    key_path = keys_dir / f"{name}.pem"
    if not key_path.exists():
        key_path.write_bytes(public_key_pem)
