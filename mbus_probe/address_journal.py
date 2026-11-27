"""Durable address-change intent journal; deliberately no serial or registry I/O.

One service owner must hold the shared bus and registry locks around operations.
A pending journal blocks all address-dependent bus work until reconciliation.
"""
import json
import os
import tempfile
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from address_policy import SecondaryIdentity, validate_address


@dataclass(frozen=True)
class Intent:
    identity: SecondaryIdentity
    old_address: int
    new_address: int
    destination_risk: bool = True

    def __post_init__(self):
        if not isinstance(self.identity, SecondaryIdentity):
            raise ValueError("complete identity required")
        if type(self.destination_risk) is not bool:
            raise ValueError("invalid destination risk")
        validate_address(self.old_address)
        validate_address(self.new_address)
        if self.old_address == self.new_address:
            raise ValueError("no-op is not a transaction")


class AddressJournal:
    def __init__(self, path):
        self.path = Path(path)
        self._fresh_id = None

    def _read(self):
        try:
            raw = self.path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return None
        data = json.loads(raw)
        if not isinstance(data, dict) or type(data.get("schema")) is not int or data["schema"] != 2:
            raise ValueError("invalid address journal")
        if set(data) != {"schema", "intent", "transaction_id", "attempted"} or type(data["attempted"]) is not bool:
            raise ValueError("invalid journal state")
        if str(uuid.UUID(data["transaction_id"])) != data["transaction_id"]:
            raise ValueError("invalid transaction ID")
        return data

    def load(self):
        data = self._read()
        if data is None:
            return None
        item = data["intent"]
        return Intent(SecondaryIdentity(**item["identity"]), item["old_address"], item["new_address"], item.get("destination_risk", True))

    def blocked(self):
        try:
            return self.load() is not None
        except (OSError, ValueError, TypeError, KeyError, AttributeError):
            return True

    def _sync_dir(self):
        fd = os.open(self.path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)

    def begin(self, intent):
        if not isinstance(intent, Intent) or self.blocked():
            raise ValueError("pending or invalid transaction")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        transaction_id = str(uuid.uuid4())
        fd, temp = tempfile.mkstemp(prefix=".address-", dir=self.path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump({"schema": 2, "intent": asdict(intent), "transaction_id": transaction_id, "attempted": False}, stream)
                stream.flush()
                os.fsync(stream.fileno())
            # Atomic no-clobber publication, even if another owner races.
            os.link(temp, self.path)
            self._sync_dir()
            self._fresh_id = transaction_id
        finally:
            os.unlink(temp)

    def transaction_id(self):
        data = self._read()
        return data.get("transaction_id") if data else None

    def fresh_write_available(self, intent):
        data = self._read()
        return bool(data and data.get("schema") == 2 and self._fresh_id is not None
                    and data["transaction_id"] == self._fresh_id
                    and not data["attempted"] and self.load() == intent)

    def claim_write(self, intent):
        """Persist attempted before transmission. Requires the single service bus lock."""
        if not self.fresh_write_available(intent):
            raise ValueError("no fresh write authorization")
        data = self._read()
        self._fresh_id = None
        data["attempted"] = True
        fd, temp = tempfile.mkstemp(prefix=".address-", dir=self.path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump(data, stream)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temp, self.path)
            self._sync_dir()
        finally:
            Path(temp).unlink(missing_ok=True)

    def reconcile(self, observed, physical_address, *, exclusive, registry_address, registry_durable):
        """Read-only recovery decision; never issues a write or clears intent."""
        intent = self.load()
        if intent is None:
            return "no_pending"
        if exclusive is not True or observed != intent.identity:
            return "unknown"
        try:
            validate_address(physical_address)
            validate_address(registry_address)
        except ValueError:
            return "unknown"
        if physical_address not in (intent.old_address, intent.new_address):
            return "unknown"
        if registry_address != physical_address or registry_durable is not True:
            return "registry_reconciliation_required"
        return "verified_new" if physical_address == intent.new_address else "verified_old"

    def finish(self, observed, physical_address, *, exclusive, registry_address, registry_durable):
        """Clear only after fresh proof and durable registry reconciliation."""
        result = self.reconcile(observed, physical_address, exclusive=exclusive,
                                registry_address=registry_address, registry_durable=registry_durable)
        if result not in ("verified_old", "verified_new"):
            raise ValueError("transaction not safely reconciled")
        self._fresh_id = None
        self.path.unlink()
        self._sync_dir()
        return result
