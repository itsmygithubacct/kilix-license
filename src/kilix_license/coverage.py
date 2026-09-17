"""Binding-scoped receipt coverage (OD-AI, OD-AQ)."""

from __future__ import annotations

from dataclasses import dataclass

from kilix_license.errors import CoverageRefused, ReceiptShapeError
from kilix_license.receipts import Receipt, parse_receipt
from kilix_license.records import LicenseRecord, RecordIndex
from kilix_license.store import ReceiptStore


@dataclass(frozen=True)
class AssetRef:
    id: str
    record_digest: str
    manifest_digest: str


def _compare(field: str, expected: str, actual: str) -> None:
    if expected != actual:
        raise CoverageRefused(field)


def covers(record: LicenseRecord, receipt: Receipt) -> bool:
    """True when receipt covers record binding. Context digests are ignored.

    A one-byte change to any bound field raises CoverageRefused naming the
    field. Catalogue-digest binding (R3 shape) raises ReceiptShapeError.
    """
    parse_receipt(receipt.to_jsonable())
    _compare("licence_id", record.id, receipt.licence_id)
    _compare("licensor", record.licensor, receipt.licensor)
    _compare("licence_text_digest", record.text_sha256, receipt.licence_text_digest)
    expected_binding = record.agreement_binding_digests()
    actual_binding = dict(receipt.binding_condition_text_digests)
    expected_keys = set(expected_binding)
    actual_keys = set(actual_binding)
    if expected_keys != actual_keys:
        missing = expected_keys - actual_keys
        extra = actual_keys - expected_keys
        field = sorted(missing | extra)[0]
        raise CoverageRefused(f"binding_condition_text_digests:{field}")
    for key, digest in expected_binding.items():
        if actual_binding[key] != digest:
            raise CoverageRefused(f"binding_condition_text_digests:{key}")
    _compare("decision", record.expected_decision, receipt.decision)
    _compare("record_digest", record.digest, receipt.record_digest)
    return True


def require(
    asset: AssetRef,
    *,
    records: RecordIndex,
    store: ReceiptStore,
) -> Receipt:
    """Return the covering receipt for asset, scoped to the binding."""
    record = records.by_digest(asset.record_digest)
    receipt = store.lookup(asset.record_digest, asset.manifest_digest)
    if receipt is None:
        others = store.for_record(asset.record_digest)
        if others:
            raise CoverageRefused("manifest_digest")
        raise CoverageRefused("receipt")
    covers(record, receipt)
    if receipt.manifest_digest != asset.manifest_digest:
        raise CoverageRefused("manifest_digest")
    if receipt.record_digest != asset.record_digest:
        raise CoverageRefused("record_digest")
    return receipt


def refuse_catalogue_binding(raw: dict[str, object]) -> None:
    """Refuse a planted R3 receipt that binds catalogue digest."""
    if "catalogue_digest" in raw or "catalog_sha256" in raw:
        field = "catalogue_digest" if "catalogue_digest" in raw else "catalog_sha256"
        raise ReceiptShapeError(field)
    parse_receipt(raw)
