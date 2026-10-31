"""The two fraud rules, as two pure functions plus the tie-break between them.

Pure means no database, no broker, no clock, no environment reading. Every
input arrives as an argument and the only output is the return value. That is
what lets the unit tests import this file and run without starting anything,
which is the entire reason it is separate from worker.py.

Values and boundary behaviour are fixed by
specs/002-transaction-event-pipeline/contracts/fraud-rules.md. Do not change
one here without changing that document in the same commit.

These rules are placeholders for a pipeline, not fraud detection. Their job is
to be simple, explicit and demonstrable.
"""

AMOUNT_THRESHOLD_RULE = "amount_threshold"
VELOCITY_RULE = "velocity"


def exceeds_amount_threshold(amount, threshold):
    """True when the amount is STRICTLY greater than the threshold.

    Exactly at the threshold is NOT flagged. Two people given "flag large
    amounts" will pick > and >= and both be certain they were right, which is
    why FR-011 requires the boundary to be written down rather than chosen by
    accident.

    Both values must be Decimal, never float. In binary floating point
    0.1 + 0.2 != 0.3, and a comparison exactly at the threshold is the single
    place that error would surface - as a wrong verdict nobody can reproduce.

    Zero and negative amounts are simply not greater than a positive
    threshold, so they return False. They still receive a decision, which is
    what the spec's extreme-amount edge case requires.
    """
    return amount > threshold


def exceeds_velocity(prior_count, count_threshold):
    """True when this transaction, counted with its priors, reaches the threshold.

    prior_count is supplied by the caller. This function queries nothing - the
    Worker runs the SELECT and passes the number in, which is what keeps the
    rule testable without a database.

    The transaction being decided counts toward its own total, hence the + 1.
    With a threshold of 4, three priors plus this one flags. Writing
    prior_count >= count_threshold would need five transactions to flag the
    fourth, which is not what "four transactions in a minute" means to anyone
    reading it.
    """
    return prior_count + 1 >= count_threshold


def decide(amount, prior_count, amount_threshold, velocity_count):
    """Evaluate both rules. Returns (flagged, rule_name).

    rule_name is None when nothing flagged.

    When both rules would flag the same transaction, amount_threshold wins,
    because it is the cheaper and more specific explanation. That tie-break is
    itself a rule with a defined outcome, so it lives here where it can be
    tested without a broker or a database.

    Exactly one rule name is returned, never a list. A list would imply a
    rules framework, and there are two rules - Principle V's threshold is
    three.
    """
    if exceeds_amount_threshold(amount, amount_threshold):
        return True, AMOUNT_THRESHOLD_RULE
    if exceeds_velocity(prior_count, velocity_count):
        return True, VELOCITY_RULE
    return False, None