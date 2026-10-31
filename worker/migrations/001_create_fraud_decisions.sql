-- Migration 001: the fraud_decisions table.
--
-- One row per transaction event, ever. This is the whole output of feature 002.
-- Every type and constraint below is fixed by
-- specs/002-transaction-event-pipeline/data-model.md. Do not change one here
-- without changing that document in the same commit.
--
-- APPEND-ONLY. Once this file has been applied on any machine it must never be
-- edited. A change has to be a new numbered file. Editing it means that
-- machine's database no longer matches this file, and nothing will notice.

CREATE TABLE fraud_decisions (
    event_id    uuid          PRIMARY KEY,
    account_id  text          NOT NULL,
    amount      numeric(12,2) NOT NULL,
    merchant    text          NOT NULL,
    occurred_at timestamptz   NOT NULL,
    decided_at  timestamptz   NOT NULL DEFAULT now(),
    flagged     boolean       NOT NULL,
    rule        text,

    CONSTRAINT fraud_decisions_flagged_rule_agree
        CHECK ((flagged = true  AND rule IS NOT NULL)
            OR (flagged = false AND rule IS NULL))
);

CREATE INDEX fraud_decisions_account_occurred_idx
    ON fraud_decisions (account_id, occurred_at);