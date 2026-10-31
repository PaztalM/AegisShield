"""Unit tests for the two fraud rules.

These import worker/rules.py directly and need no broker, no database and no
other container - which is the whole reason rules.py is a separate file.

Run with:
    docker compose run --rm --no-deps tests python -m pytest tests/unit -v

--no-deps matters. The tests service declares a dependency on a healthy
worker for the integration suite; these tests need none of it.

Every expected outcome below comes from
specs/002-transaction-event-pipeline/contracts/fraud-rules.md. If a test here
ever disagrees with that document, one of the two is wrong and both have to be
settled together.

NOT COVERED HERE, deliberately: the velocity window's half-open boundary -
whether a transaction exactly 60 seconds old counts. That boundary lives in
the SQL WHERE clause, not in these functions, which receive a count and no
timestamps. It needs an integration test against real rows.
"""

from decimal import Decimal

from worker import rules

THRESHOLD = Decimal("5000.00")
VELOCITY_COUNT = 4


# --- Rule 1: amount threshold -----------------------------------------------

def test_amount_above_threshold_is_flagged():
    assert rules.exceeds_amount_threshold(Decimal("6000.00"), THRESHOLD) is True


def test_amount_below_threshold_is_not_flagged():
    assert rules.exceeds_amount_threshold(Decimal("4999.99"), THRESHOLD) is False


def test_amount_exactly_at_threshold_is_not_flagged():
    """The boundary FR-011 exists to pin down: strictly greater, not >=.

    This is the case that would otherwise be skipped, and the one where two
    implementers would disagree while both felt certain.
    """
    assert rules.exceeds_amount_threshold(Decimal("5000.00"), THRESHOLD) is False


def test_zero_amount_is_not_flagged_and_does_not_raise():
    """The spec requires extreme amounts to get a decision, not a crash."""
    assert rules.exceeds_amount_threshold(Decimal("0.00"), THRESHOLD) is False


def test_negative_amount_is_not_flagged_and_does_not_raise():
    assert rules.exceeds_amount_threshold(Decimal("-50.00"), THRESHOLD) is False


# --- Rule 2: velocity -------------------------------------------------------

def test_velocity_count_reached_is_flagged():
    """Three priors plus this one is four. This is the + 1 in the rule."""
    assert rules.exceeds_velocity(3, VELOCITY_COUNT) is True


def test_velocity_one_short_is_not_flagged():
    assert rules.exceeds_velocity(2, VELOCITY_COUNT) is False


# --- The tie-break, and what actually gets stored ---------------------------

def test_amount_wins_when_both_rules_would_flag():
    """A transaction can break both rules. Only one reason is stored."""
    flagged, rule = rules.decide(Decimal("9000.00"), 10, THRESHOLD, VELOCITY_COUNT)
    assert flagged is True
    assert rule == rules.AMOUNT_THRESHOLD_RULE


def test_velocity_alone_is_recorded_as_velocity():
    flagged, rule = rules.decide(Decimal("100.00"), 3, THRESHOLD, VELOCITY_COUNT)
    assert flagged is True
    assert rule == rules.VELOCITY_RULE


def test_nothing_flagged_records_no_rule():
    """flagged=False with rule=None - the only unflagged state the database
    will accept, because of the CHECK constraint.
    """
    flagged, rule = rules.decide(Decimal("100.00"), 0, THRESHOLD, VELOCITY_COUNT)
    assert flagged is False
    assert rule is None
