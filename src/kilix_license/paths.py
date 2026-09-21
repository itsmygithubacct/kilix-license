"""Where receipts live, and the live store this suite must never touch.

Two separate jobs:

* ``receipt_store_root()`` is the **one** answer to "where does an acceptance
  receipt go?", for every producer and every consumer in the stack (OD-AJ);
* ``live_store_root()`` / ``refuse_live_store()`` are the test-harness guard
  that keeps this repository's own suite out of the invoking user's store.
"""

from __future__ import annotations

import os
from pathlib import Path
import pwd

from kilix_license.errors import LiveStoreForbidden, ReceiptStoreRootRefused

# The stack's shared writable root. kilix-voice's voicelib.paths and
# kilix-content both already read this variable; it is the stack's spelling of
# "where our state lives", and the receipt store is stack state, not the
# private state of whichever component happens to write it.
STACK_HOME_ENV = "GPU_TERMINAL_HOME"
# The one override. A deployment that must put receipts elsewhere sets this,
# and every component sees the same answer because every component asks this
# function. A component that invents its own variable re-opens V-ACC F7.
RECEIPT_STORE_ENV = "KILIX_LICENSE_RECEIPTS"
# The directory name under the stack home. Consumers never spell it.
RECEIPT_STORE_LEAF = "license-receipts"


def nss_home() -> Path:
    return Path(pwd.getpwuid(os.getuid()).pw_dir)


def live_store_root() -> Path:
    return nss_home() / ".local" / "gpu_terminal"


def _absolute(value: str, label: str) -> Path:
    expanded = os.path.expanduser(value)
    if not os.path.isabs(expanded):
        raise ReceiptStoreRootRefused(
            f"{label} must be an absolute path, not {value!r}"
        )
    return Path(os.path.normpath(expanded))


def stack_home() -> Path:
    """The stack's shared writable root: ``$GPU_TERMINAL_HOME``.

    Falls back to the NSS home's ``.local/gpu_terminal``, which is what
    kilix-voice's ``voicelib.paths.gpu_terminal_home()`` already does, so the
    default agrees with the consumer that has shipped one longest.
    """
    value = os.environ.get(STACK_HOME_ENV)
    if value:
        return _absolute(value, STACK_HOME_ENV)
    return live_store_root()


def receipt_store_root() -> Path:
    """The directory every acceptance receipt is written to and read from.

    **This is the agreement V-ACC-VERIFY F7 found missing.** The default is
    ``$GPU_TERMINAL_HOME/license-receipts``; ``$KILIX_LICENSE_RECEIPTS``
    overrides it outright. Producers (kilix-content's first-use flow) and
    consumers (the kilix-voice weights gate, the kilix installer, the EnCodec
    converter) must all obtain the path from here and must not compose one of
    their own -- a receipt filed anywhere else is invisible to everyone, and
    presents to the user as a gate that refuses an acceptance they just gave.
    """
    override = os.environ.get(RECEIPT_STORE_ENV)
    if override:
        return _absolute(override, RECEIPT_STORE_ENV)
    return stack_home() / RECEIPT_STORE_LEAF


def _normalised(path: str | os.PathLike[str] | bytes) -> str:
    text = os.fsdecode(path)
    return os.path.realpath(os.path.abspath(os.path.expanduser(text)))


def is_receipt_store_root(path: str | os.PathLike[str] | bytes) -> bool:
    """True when path names the directory receipt_store_root() names."""
    return _normalised(path) == _normalised(str(receipt_store_root()))


def check_receipt_store_root(path: str | os.PathLike[str] | bytes) -> Path:
    """Return path when it is the agreed receipt store root, or refuse.

    The refusal names both paths and the override, because the symptom of
    getting this wrong (V-ACC-VERIFY F7) is a gate that refuses an acceptance
    the user gave, and nothing in that symptom points at the real cause.
    """
    if not is_receipt_store_root(path):
        agreed = receipt_store_root()
        raise ReceiptStoreRootRefused(
            f"receipt store root {os.fsdecode(path)!r} is not the root this "
            f"authority publishes receipts to ({str(agreed)!r}). Every "
            "producer and consumer must take the path from "
            "kilix_license.receipt_store_root(); a receipt written anywhere "
            "else is found by nobody, and the licence gate refuses an "
            f"acceptance the user gave. Set ${RECEIPT_STORE_ENV} to move the "
            f"store, or ${STACK_HOME_ENV} to move the whole stack home."
        )
    return Path(os.fsdecode(path))


def is_under_live_store(path: str | os.PathLike[str] | bytes) -> bool:
    text = os.fsdecode(path)
    if not text:
        return False
    expanded = os.path.abspath(os.path.expanduser(text))
    try:
        candidate = os.path.realpath(expanded)
    except OSError:
        candidate = os.path.normpath(expanded)
    live = os.path.realpath(os.path.abspath(str(live_store_root())))
    return candidate == live or candidate.startswith(live + os.sep)


def refuse_live_store(path: str | os.PathLike[str] | bytes) -> None:
    if is_under_live_store(path):
        raise LiveStoreForbidden(
            f"refusing live receipt store path {os.fsdecode(path)}"
        )
