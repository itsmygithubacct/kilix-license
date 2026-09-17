"""Fixture licence records and texts for the hermetic harness."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from kilix_license.digest import sha256_hex
from kilix_license.records import (
    Advisory,
    BindingCondition,
    Component,
    LicenseRecord,
    RecordIndex,
    Statement,
)
from kilix_license.texts import TextStore

# Owner-bound Pocket prohibited-use paragraph (OD-AG), not TERMS_SUMMARY.
POCKET_PROHIBITED_USE = (
    "Use of our model must comply with all applicable laws and regulations "
    "and must not result in, involve, or facilitate any illegal, harmful, "
    "deceptive, fraudulent, or unauthorized activity. Prohibited uses include, "
    "without limitation, voice impersonation or cloning without explicit and "
    "lawful consent; misinformation, disinformation, or deception (including "
    "fake news, fraudulent calls, or presenting generated content as genuine "
    "recordings of real people or events); and the generation of unlawful, "
    "harmful, libelous, abusive, harassing, discriminatory, hateful, or "
    "privacy-invasive content. We disclaim all liability for any non-compliant "
    "use."
)

POCKET_LICENCE_TEXT = (
    "CC BY 4.0 fixture text for kilix-license LIC1. Licensor: Kyutai.\n"
)
KRISTIN_STATEMENT = (
    "License: public domain\n"
    "Feel free to use these for any legal and ethical purpose.\n"
)
RESEARCH_ADVISORY = "Research-use advisory fixture. Not a binding condition.\n"
COMPONENT_EXCEPTION = "Tokenizer component exception fixture.\n"

FIXTURE_MANIFEST = sha256_hex(b"kilix-license-fixture-manifest-v1")
FIXTURE_RELEASE = sha256_hex(b"kilix-license-fixture-release-v1")
FIXTURE_CATALOGUE = sha256_hex(b"kilix-license-fixture-catalogue-v1")


@dataclass(frozen=True)
class FixtureSet:
    texts: TextStore
    pocket: LicenseRecord
    kristin: LicenseRecord
    index: RecordIndex
    pocket_licence: bytes
    pocket_prohibited: bytes
    kristin_text: bytes
    advisory: bytes


def build_fixtures(root: Path) -> FixtureSet:
    texts = TextStore(root / "texts")
    pocket_licence = POCKET_LICENCE_TEXT.encode("utf-8")
    pocket_prohibited = POCKET_PROHIBITED_USE.encode("utf-8")
    kristin_text = KRISTIN_STATEMENT.encode("utf-8")
    advisory = RESEARCH_ADVISORY.encode("utf-8")
    exception = COMPONENT_EXCEPTION.encode("utf-8")
    pocket = LicenseRecord(
        id="cc-by-4.0-pocket-tts",
        licensor="Kyutai",
        text_sha256=texts.put(pocket_licence, label="pocket-licence"),
        components=(Component(id="pocket-tts", role="model"),),
        binding_conditions=(
            BindingCondition(
                id="pocket-prohibited-use",
                text_sha256=texts.put(pocket_prohibited, label="pocket-prohibited-use"),
                agreement_required=True,
            ),
        ),
        advisories=(
            Advisory(
                id="research-use",
                text_sha256=texts.put(advisory, label="research-use"),
            ),
        ),
        statements=(),
    )
    kristin = LicenseRecord(
        id="kristin-public-domain",
        licensor="Bryce Beattie",
        text_sha256=texts.put(kristin_text, label="kristin"),
        components=(Component(id="piper-en-us-kristin-medium", role="voice"),),
        binding_conditions=(),
        advisories=(),
        statements=(
            Statement(
                id="trainer-statement",
                text_sha256=texts.put(kristin_text, label="kristin-statement"),
            ),
        ),
    )
    # Keep exception text in the store for screen tests that add a component.
    texts.put(exception, label="component-exception")
    return FixtureSet(
        texts=texts,
        pocket=pocket,
        kristin=kristin,
        index=RecordIndex((pocket, kristin)),
        pocket_licence=pocket_licence,
        pocket_prohibited=pocket_prohibited,
        kristin_text=kristin_text,
        advisory=advisory,
    )
