"""Generate synthetic transaction events and publish them to RabbitMQ.

This file is built in three steps so each can be verified on its own:
  T018 (done)  - configuration and event generation
  T019         - queue topology and durable publishing
  T020         - the main loop, heartbeat and per-event logging

The event shape is fixed by
specs/002-transaction-event-pipeline/contracts/transaction-event.md. That
document is the contract: the Worker parses this format independently, with no
shared code between the two services, so a change here that is not made there
breaks the pipeline silently.
"""

import os
import random
import uuid
from datetime import datetime, timezone
from decimal import Decimal

# Free text, not used by any rule. Carried so a stored decision is readable on
# its own without going back to the original message.
MERCHANTS = (
    "Northwind Electronics",
    "Contoso Grocers",
    "Fabrikam Fuel",
    "Tailspin Travel",
    "Proseware Pharmacy",
    "Wingtip Hardware",
    "Litware Books",
    "Adventure Outfitters",
)


def load_config():
    """Read every setting this service uses from the environment.

    All of these are read as REQUIRED - os.environ[...] rather than .get with a
    fallback - so that defaults live in exactly one place: .env.example and the
    Compose file that interpolates it. A second copy of each default in here
    would be two sources of truth, and the first time they disagreed the
    service would behave in a way neither file explains.

    A missing variable therefore raises KeyError naming it, which is the
    correct outcome: Compose guarantees all of these are set, so if one is
    absent something is wrong that should be loud.
    """
    return {
        "rabbitmq_host": os.environ["RABBITMQ_HOST"],
        "rabbitmq_user": os.environ["RABBITMQ_DEFAULT_USER"],
        "rabbitmq_pass": os.environ["RABBITMQ_DEFAULT_PASS"],
        "rabbitmq_vhost": os.environ["RABBITMQ_DEFAULT_VHOST"],
        "rate_per_second": float(os.environ["PRODUCER_RATE_PER_SECOND"]),
        "fraud_ratio": float(os.environ["PRODUCER_FRAUD_RATIO"]),
        "account_pool_size": int(os.environ["PRODUCER_ACCOUNT_POOL_SIZE"]),
        "amount_threshold": Decimal(os.environ["FRAUD_AMOUNT_THRESHOLD"]),
        "log_level": os.environ["LOG_LEVEL"],
        "retry_max_delay": int(os.environ["RETRY_MAX_DELAY_SECONDS"]),
        "heartbeat_file": os.environ["HEARTBEAT_FILE"],
    }


def account_ids(pool_size):
    """The fixed pool of account identifiers, in the contract's format.

    Deliberately small. A small pool is what makes several transactions land on
    one account inside the velocity window, so the velocity rule fires without
    any special-casing in the generator. Raising PRODUCER_ACCOUNT_POOL_SIZE
    suppresses velocity flags, which is worth knowing before someone raises it
    and reports the rule as broken.
    """
    return [f"card_{n:06d}" for n in range(1, pool_size + 1)]


def generate_event(accounts, fraud_ratio, amount_threshold):
    """Build one transaction event, shaped exactly as the contract specifies.

    A fraud_ratio share of events are given an amount ABOVE amount_threshold,
    so rule 1 fires predictably and the rules can be watched working rather
    than taken on trust (FR-005). The threshold is read from the environment
    rather than hard-coded: a fixed "large" number here would silently stop
    producing flagged transactions the moment anyone raised the threshold.

    The velocity rule is exercised differently - by the small account pool, not
    by this ratio. So setting PRODUCER_FRAUD_RATIO=0 does NOT eliminate flagged
    decisions, and that surprises people.
    """
    fraudulent = random.random() < fraud_ratio

    # Amounts are built in whole cents and then scaled, so every value has
    # exactly two decimal places and no rounding ever happens.
    threshold_cents = int(amount_threshold * 100)
    if fraudulent:
        # Strictly above the threshold: + 1 cent at minimum, so a generated
        # "fraudulent" amount can never land exactly ON the boundary, where the
        # contract says it would NOT be flagged.
        cents = threshold_cents + random.randrange(1, 500_001)
    else:
        # Strictly below. max(2, ...) keeps randrange valid if someone sets a
        # very small threshold.
        cents = random.randrange(1, max(2, threshold_cents))
    amount = (Decimal(cents) / 100).quantize(Decimal("0.01"))

    return {
        "event_id": str(uuid.uuid4()),
        # RFC 3339 with an explicit offset. The contract rejects a naive
        # timestamp, because "14:22" without an offset is ambiguous. The Z form
        # matches the contract's example; millisecond precision is plenty for a
        # velocity window measured in seconds.
        "occurred_at": datetime.now(timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z"),
        "account_id": random.choice(accounts),
        # A STRING, not a JSON number. JSON numbers are binary floats in most
        # parsers, where 0.1 + 0.2 != 0.3, and a threshold comparison exactly
        # at the boundary is the one place that error would surface - as a wrong
        # verdict that cannot be reproduced reliably.
        "amount": str(amount),
        "merchant": random.choice(MERCHANTS),
    }
