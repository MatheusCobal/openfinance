"""Password hashing for OpenFinance users.

Argon2id (the default ``argon2-cffi`` ``PasswordHasher`` variant) is the current
OWASP-recommended algorithm. Hashes are PHC strings, so the algorithm and its
parameters travel with the hash and can be upgraded later without a schema
change.
"""

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

# Default parameters are Argon2id with sensible interactive-login costs.
_hasher = PasswordHasher()


def hash_password(password: str) -> str:
    """Return an Argon2id PHC hash for ``password``."""
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    """Return True only if ``password`` matches ``password_hash``.

    Never raises: any malformed hash or mismatch returns False so callers can
    treat verification as a plain boolean.
    """
    try:
        return _hasher.verify(password_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False
