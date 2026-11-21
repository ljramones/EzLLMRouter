"""Service-volume provider credentials; never mounted in the isolated worker."""

from __future__ import annotations

from collections.abc import Iterable
from .records import Record

import hashlib
import json
from pathlib import Path
import re
import threading

from .private_files import read_private, write_private
from .secret_box import (
    SecretBox,
    SecretBoxError,
    decode_envelope,
    private_directory,
    validate_secret,
)


def credential_context(connection_id: str, version: int) -> bytes:
    return json.dumps(
        {"connection_id": connection_id, "version": version}, sort_keys=True, separators=(",", ":")
    ).encode()


class ProviderVault:
    def __init__(self, root: str | Path, *, require_existing: bool = False) -> None:
        self.root = Path(root)
        private_directory(self.root)
        self.key_path = self.root / "provider.keys.json"
        required_ids = set()
        for path in self.root.glob("*.sealed"):
            required_ids.add(self._read(path)["key_id"])
        self.box = SecretBox(
            self.key_path,
            "provider-credentials",
            required_ids=required_ids,
            required=require_existing,
        )
        self._gate = threading.RLock()

    def _path(self, connection_id: str, version: int) -> Path:
        name = hashlib.sha256(connection_id.encode()).hexdigest() + f".{version}.sealed"
        return self.root / name

    def request_digest(self, value: bytes) -> str:
        return self.box.request_digest(value)

    @staticmethod
    def _read(path: Path) -> Record:
        try:
            return decode_envelope(read_private(path))
        except (OSError, ValueError, TypeError) as exc:
            raise SecretBoxError("PROVIDER_CREDENTIAL_UNAVAILABLE") from exc

    def seal(
        self, connection_id: str, version: int, secret: str, *, committed_version: int | None = None
    ) -> Path:
        validate_secret(secret)
        if committed_version is not None and (
            type(committed_version) is not int
            or committed_version < 0
            or type(version) is not int
            or version != committed_version + 1
        ):
            raise ValueError(
                "staging requires the version immediately after the committed credential"
            )
        envelope = self.box.seal(secret, credential_context(connection_id, version))
        path = self._path(connection_id, version)
        with self._gate:
            # Registry holds the exclusive service/send gates and supplies the
            # committed version. Only that uncommitted successor may be replaced.
            write_private(
                path,
                json.dumps(envelope, sort_keys=True).encode(),
                replace=committed_version is not None,
            )
        return path

    def resolve(self, connection_id: str, version: int) -> str:
        with self._gate:
            envelope = self._read(self._path(connection_id, version))
            return self.box.open(envelope, credential_context(connection_id, version))

    def remove(self, connection_id: str, version: int) -> None:
        if version:
            with self._gate:
                self._path(connection_id, version).unlink(missing_ok=True)

    def key_references(self) -> set[str]:
        with self._gate:
            return {self._read(path)["key_id"] for path in self.root.glob("*.sealed")}

    def reencrypt_secrets(self, connection_ids: Iterable[str], *, verify_only: bool = False) -> int:
        """Atomically replace each file; a partial run can resume with old keys retained."""
        names = {hashlib.sha256(value.encode()).hexdigest(): value for value in connection_ids}
        changed = 0
        with self._gate:
            for path in sorted(self.root.glob("*.sealed")):
                match = re.fullmatch(r"([0-9a-f]{64})\.([1-9][0-9]*)\.sealed", path.name)
                if not match or match[1] not in names:
                    raise SecretBoxError("PROVIDER_CREDENTIAL_IDENTITY_UNAVAILABLE")
                context = credential_context(names[match[1]], int(match[2]))
                envelope = self._read(path)
                value = self.box.open(envelope, context)
                if not verify_only and envelope["key_id"] != self.box.active_id:
                    write_private(
                        path,
                        json.dumps(self.box.seal(value, context), sort_keys=True).encode(),
                        replace=True,
                    )
                    changed += 1
        return changed

    def rotate_encryption_key(self, connection_ids: Iterable[str]) -> Record:
        with self._gate:
            identifier = self.box.rotate()
            return {"key_id": identifier, "rewritten": self.reencrypt_secrets(connection_ids)}
