"""Agreement capture. Informational licences need no typed line."""

from __future__ import annotations

from dataclasses import dataclass

from kilix_license.errors import AgreementRequired
from kilix_license.records import LicenseRecord


@dataclass(frozen=True)
class Agreement:
    licence_id: str
    named_binding_ids: tuple[str, ...]
    decision: str
    typed_text: str | None


def typed_agreement_line(record: LicenseRecord) -> str:
    parts = [record.id]
    parts.extend(
        condition.id
        for condition in record.binding_conditions
        if condition.agreement_required
    )
    return f"accept {' '.join(parts)} from {record.licensor}"


def capture_agreement(
    record: LicenseRecord, typed_text: str | None = None
) -> Agreement:
    required = tuple(
        condition.id
        for condition in record.binding_conditions
        if condition.agreement_required
    )
    if not required:
        if typed_text:
            raise AgreementRequired(
                "informational licence needs no typed agreement"
            )
        return Agreement(record.id, (), "record", None)
    expected = typed_agreement_line(record)
    if typed_text != expected:
        raise AgreementRequired(
            "typed agreement must name every binding text shown: "
            f"expected {expected!r}"
        )
    return Agreement(record.id, required, "accept", typed_text)
