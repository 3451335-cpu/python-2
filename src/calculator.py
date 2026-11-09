"""Derive a PBKDF2-HMAC-SHA256 hash from file bytes supplied as JSON."""

import base64
import hashlib
import json
import sys

ALGORITHM = "PBKDF2-HMAC-SHA256"
DIGEST_BYTES = 32
MAX_FILE_BYTES = 1024 * 1024
MAX_INPUT_BYTES = 2 * 1024 * 1024
MAX_SALT_BYTES = 64
MIN_ITERATIONS = 1
MAX_ITERATIONS = 2_000_000
FIELDS = {"file_b64", "salt_b64", "iterations"}


def decode_bytes(value, label):
    """Decode standard Base64 and report the field on invalid input."""
    if not isinstance(value, str):
        raise ValueError(f"{label} must be a Base64 string")
    try:
        return base64.b64decode(value, validate=True)
    except ValueError as error:
        raise ValueError(f"invalid Base64 in {label}") from error


def calculate(task):
    """Compute a 32-byte PBKDF2 hash and return its lowercase hex form."""
    if not isinstance(task, dict) or task.keys() != FIELDS:
        raise ValueError("expected file_b64, salt_b64 and iterations")
    file_bytes = decode_bytes(task["file_b64"], "file_b64")
    salt = decode_bytes(task["salt_b64"], "salt_b64")
    iterations = task["iterations"]
    if len(file_bytes) > MAX_FILE_BYTES:
        raise ValueError("file exceeds 1 MiB")
    if not salt or len(salt) > MAX_SALT_BYTES:
        raise ValueError("salt must contain 1 to 64 bytes")
    if (
        type(iterations) is not int
        or not MIN_ITERATIONS <= iterations <= MAX_ITERATIONS
    ):
        raise ValueError("iterations must be an integer in [1, 2000000]")
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        file_bytes,
        salt,
        iterations,
        dklen=DIGEST_BYTES,
    )
    return dict(
        algorithm=ALGORITHM,
        iterations=iterations,
        dklen=DIGEST_BYTES,
        digest=digest.hex(),
    )


def main():
    """Read stdin and write the result to stdout."""
    try:
        source = sys.stdin.buffer.read(MAX_INPUT_BYTES + 1)
        if len(source) > MAX_INPUT_BYTES:
            raise ValueError("input exceeds 2 MiB")
        print(json.dumps(calculate(json.loads(source))))
    except ValueError as error:
        print(error, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
