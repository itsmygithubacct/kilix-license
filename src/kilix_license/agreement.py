"""Agreement capture. Informational licences need no typed line."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import datetime as _datetime
import os
import pwd
import re
import sys
from typing import Any

from kilix_license.errors import AgreementRequired, ReceiptShapeError
from kilix_license.records import LicenseRecord

# V-ACC-VERIFY F6. A receipt named no person, no moment and no circumstance, so
# one well-formed receipt satisfied every gate, on every machine, for every
# user, for ever -- and a receipt placed in an image would have read exactly
# like consent a user gave. What follows does not fix that: it records, beside
# the acceptance, the three facts this authority can observe for itself at the
# moment the agreement is captured. Read what each field is called literally.
# None of them is an identity claim, and none of them is attested by anything.
INTERACTIVE_TTY = "interactive-tty"
NO_TTY = "no-tty"
CAPTURE_MODES = (INTERACTIVE_TTY, NO_TTY)

_CAPTURED_AT = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
_ACCOUNT = re.compile(r"^[^\x00-\x1f\x7f]{1,256}$")


@dataclass(frozen=True)
class Acceptance:
    """What the authority observed about the process that captured agreement.

    Deliberately narrow names. In particular:

    * ``captured_at`` is the capturing machine's own UTC clock at capture. It
      is not attested, not signed and not compared with anything; a machine
      with a wrong or adjusted clock writes a wrong value and nothing notices.
    * ``captured_by_account`` / ``captured_by_uid`` name the POSIX account the
      capturing **process** ran as. That is not "the person who accepted": an
      account is shared, delegated, automated and reused, and this authority
      has no way to learn who was at the keyboard.
    * ``capture_mode`` is ``interactive-tty`` when that process had a terminal
      on both its standard input and its standard output at capture time, and
      ``no-tty`` otherwise. A terminal is evidence that something could have
      typed; it is not evidence that a person did.

    Nothing here is bound (OD-AI): ``covers()`` never reads it, so recording it
    changes no receipt's coverage and voids no acceptance. It is audit context
    -- the thing a reviewer reads when asking "where did this receipt come
    from?" -- and, for a caller that opts in, a check a consumer can demand.
    """

    captured_at: str
    captured_by_account: str
    captured_by_uid: int
    capture_mode: str

    def __post_init__(self) -> None:
        if not _CAPTURED_AT.match(self.captured_at or ""):
            raise ReceiptShapeError(
                "acceptance.captured_at",
                "captured_at must be RFC 3339 UTC seconds, e.g. "
                f"2026-09-21T20:41:00Z, not {self.captured_at!r}",
            )
        if not isinstance(self.captured_by_account, str) or not _ACCOUNT.match(
            self.captured_by_account
        ):
            raise ReceiptShapeError(
                "acceptance.captured_by_account",
                "captured_by_account must be one printable line",
            )
        if isinstance(self.captured_by_uid, bool) or not isinstance(
            self.captured_by_uid, int
        ):
            raise ReceiptShapeError(
                "acceptance.captured_by_uid", "captured_by_uid must be an integer"
            )
        if self.captured_by_uid < 0:
            raise ReceiptShapeError(
                "acceptance.captured_by_uid", "captured_by_uid must not be negative"
            )
        if self.capture_mode not in CAPTURE_MODES:
            raise ReceiptShapeError(
                "acceptance.capture_mode",
                f"capture_mode must be one of {CAPTURE_MODES}, "
                f"not {self.capture_mode!r}",
            )

    @property
    def was_captured_at_a_terminal(self) -> bool:
        """True only for ``interactive-tty``. Says nothing about who typed."""
        return self.capture_mode == INTERACTIVE_TTY

    def to_jsonable(self) -> dict[str, Any]:
        return {
            "capture_mode": self.capture_mode,
            "captured_at": self.captured_at,
            "captured_by_account": self.captured_by_account,
            "captured_by_uid": self.captured_by_uid,
        }

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any], label: str) -> Acceptance:
        if not isinstance(raw, Mapping):
            raise ReceiptShapeError(label, f"{label} must be an object")
        expected = {"capture_mode", "captured_at", "captured_by_account", "captured_by_uid"}
        unknown = sorted(set(raw) - expected)
        if unknown:
            raise ReceiptShapeError(
                f"{label}.{unknown[0]}", f"{label} has unknown field(s): {unknown}"
            )
        missing = sorted(expected - set(raw))
        if missing:
            raise ReceiptShapeError(
                f"{label}.{missing[0]}", f"{label} is missing {missing[0]}"
            )
        return cls(
            captured_at=raw["captured_at"],
            captured_by_account=raw["captured_by_account"],
            captured_by_uid=raw["captured_by_uid"],
            capture_mode=raw["capture_mode"],
        )


def observe_capture(
    *, now: _datetime.datetime | None = None, interactive: bool | None = None
) -> Acceptance:
    """Observe the capturing process, here, now.

    Every value is taken by this authority from its own process rather than
    accepted from a caller, so a producer cannot assert a nicer story by
    passing one in. ``now`` and ``interactive`` exist for tests and for a
    producer that genuinely knows better about its own terminal (a TUI that
    owns the tty on a different descriptor, say).
    """
    moment = (now or _datetime.datetime.now(_datetime.timezone.utc)).astimezone(
        _datetime.timezone.utc
    )
    if interactive is None:
        interactive = _has_terminal()
    uid = os.getuid()
    try:
        account = pwd.getpwuid(uid).pw_name
    except KeyError:
        account = f"uid-{uid}"
    return Acceptance(
        captured_at=moment.strftime("%Y-%m-%dT%H:%M:%SZ"),
        captured_by_account=account,
        captured_by_uid=uid,
        capture_mode=INTERACTIVE_TTY if interactive else NO_TTY,
    )


def _has_terminal() -> bool:
    for stream in (sys.stdin, sys.stdout):
        try:
            if stream is None or not stream.isatty():
                return False
        except (OSError, ValueError):
            return False
    return True


@dataclass(frozen=True)
class Agreement:
    licence_id: str
    named_binding_ids: tuple[str, ...]
    decision: str
    typed_text: str | None
    # Digests taken from the rendered screen at capture time (OD-AH/AP).
    # receipt_from_agreement refuses when they differ from the record.
    record_digest: str | None = None
    binding_condition_text_digests: dict[str, str] | None = None
    # What was observed about this capture (V-ACC-VERIFY F6). None only for an
    # Agreement a caller built by hand, as every caller did before LIC6.
    acceptance: Acceptance | None = None


def typed_agreement_line(record: LicenseRecord) -> str:
    parts = [record.id]
    parts.extend(
        condition.id
        for condition in record.binding_conditions
        if condition.agreement_required
    )
    return f"accept {' '.join(parts)} from {record.licensor}"


def capture_agreement(
    record: LicenseRecord,
    typed_text: str | None = None,
    *,
    acceptance: Acceptance | None = None,
) -> Agreement:
    """Capture agreement, and record what this process observes about itself.

    ``acceptance`` defaults to :func:`observe_capture` called here, at the
    moment the agreement is taken, so the recorded moment is the acceptance's
    and not the receipt writer's. A caller may pass its own -- a first-use flow
    that captured the agreement earlier, say -- but cannot suppress it.
    """
    observed = acceptance or observe_capture()
    required = tuple(
        condition.id
        for condition in record.binding_conditions
        if condition.agreement_required
    )
    if record.expected_decision == "record":
        if typed_text:
            raise AgreementRequired(
                "informational licence needs no typed agreement"
            )
        return Agreement(
            record.id,
            (),
            "record",
            None,
            record_digest=record.digest,
            binding_condition_text_digests=dict(record.agreement_binding_digests()),
            acceptance=observed,
        )
    expected = typed_agreement_line(record)
    if typed_text != expected:
        raise AgreementRequired(
            "typed agreement must name every binding text shown: "
            f"expected {expected!r}"
        )
    return Agreement(
        record.id,
        required,
        "accept",
        typed_text,
        record_digest=record.digest,
        binding_condition_text_digests=dict(record.agreement_binding_digests()),
        acceptance=observed,
    )
