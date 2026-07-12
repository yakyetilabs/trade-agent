"""Unit tests for the pre-agent escalation guard."""

from src.safeguards.escalation_guard import should_escalate

# --- ESCALATION CASES (one per category) ---


def test_escalates_on_smuggling_contraband() -> None:
    result = should_escalate("Can we smuggle these undeclared firearms past customs?")
    assert result.escalate is True
    assert result.reason == "contraband"


def test_escalates_on_ofac_sanctions() -> None:
    result = should_escalate("Is this consignee on the OFAC SDN list?")
    assert result.escalate is True
    assert result.reason == "sanctions"


def test_escalates_on_federal_seizure() -> None:
    result = should_escalate("The container was seized by customs in a federal seizure.")
    assert result.escalate is True
    assert result.reason == "federal-seizure"


def test_escalates_on_bribery() -> None:
    result = should_escalate("Can I bribe the inspector to release the shipment?")
    assert result.escalate is True
    assert result.reason == "bribery"


def test_escalation_is_case_insensitive() -> None:
    assert should_escalate("CONTRABAND in the container").escalate is True


def test_hyphenated_phrasing_still_escalates() -> None:
    # Live-verified miss before hyphen normalization: "under-the-table" slipped past
    # the spaced "under the table" pattern and reached a real model run.
    result = should_escalate("A broker offered an under-the-table payment to speed things up.")
    assert result.escalate is True
    assert result.reason == "bribery"


# --- NON-ESCALATION CASES (legitimate trade inquiries) ---


def test_routine_flag_question_does_not_escalate() -> None:
    result = should_escalate("Why was shipment S-1005 held at the port of entry?")
    assert result.escalate is False
    assert result.reason is None


def test_tariff_and_license_questions_do_not_escalate() -> None:
    assert should_escalate("What is the duty rate for cotton t-shirts?").escalate is False
    assert should_escalate("Does this import require a license?").escalate is False


def test_restricted_but_legal_goods_do_not_escalate() -> None:
    # A List I precursor is a *restricted import* the agent handles - not a
    # criminal/security escalation. The classifier/lookup deals with it.
    result = should_escalate("Why is my ephedrine shipment flagged for clearance?")
    assert result.escalate is False


# --- NEAR-MISS GUARDS ---


def test_firearms_parts_alone_do_not_escalate() -> None:
    # Only specific phrases ("undeclared firearms", "weapons cache") trigger;
    # a plain reference to firearms parts must not.
    result = should_escalate("What is the HTS code for firearms cleaning parts?")
    assert result.escalate is False


def test_bribe_word_boundary_does_not_false_fire() -> None:
    # "brief" contains "brie" but not the "brib" stem; the regex must not match.
    result = should_escalate("I have a brief question about my brokerage invoice.")
    assert result.escalate is False
