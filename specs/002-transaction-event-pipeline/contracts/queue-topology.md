# Contract: Queue topology

The exact names, arguments and durability settings of everything declared in the broker. **These values are immutable in practice** — see the warning at the end — so they are fixed here rather than left to implementation.

## What is declared

| Object | Name | Type | Durable | Purpose |
|---|---|---|---|---|
| Queue | `transactions` | classic | yes | Carries transaction events from the Producer to the Worker. |
| Exchange | `transactions.dlx` | direct | yes | The dead-letter exchange the `transactions` queue nominates. |
| Queue | `transactions.dead` | classic | yes | Where rejected messages land, to be counted and inspected. |
| Binding | `transactions.dlx` → `transactions.dead` | — | — | Routing key `transactions`, matching the dead-lettered message's original routing key. |

All of it lives in the `aegisshield` virtual host from feature 001, not the default `/`.

## Arguments on `transactions`

```
x-dead-letter-exchange: "transactions.dlx"
```

No other arguments. In particular:

- **No `x-message-ttl`.** Messages must wait indefinitely for a Worker; expiring them would be a silent form of the data loss FR-019 forbids.
- **No `x-max-length`.** A bounded queue drops or dead-letters messages when full, which would turn "the Worker is slower than the Producer" — a condition the spec expects to tolerate — into lost transactions.
- **No `x-queue-type: quorum`.** Quorum queues exist for replication across a cluster; there is one broker node. Principle V.

## Publishing and consuming settings

| Setting | Value | Why |
|---|---|---|
| Message delivery mode | `2` (persistent) | Required by Principle II. With a durable queue, this is what makes a message survive a broker restart. Durable queue without persistent messages loses the messages; persistent messages on a transient queue lose the queue. Both are needed. |
| Publisher confirms | enabled on the Producer channel | So the Producer knows the broker accepted the message instead of assuming it. See research.md §11. |
| Consumer prefetch | `1` (`basic_qos(prefetch_count=1)`) | One unacknowledged message at a time. Keeps the ack-after-commit window as small as possible, prevents a crash from losing a batch, and keeps `pika`'s single-threaded heartbeat servicing predictable. |
| Auto-acknowledge | **off** | Auto-ack acknowledges on delivery, before the Worker has done anything. It would make FR-017 unachievable by construction. |
| Rejection | `basic_nack(requeue=False)` | Routes to the dead-letter exchange. `requeue=True` would redeliver a poison message forever. |

## Who declares what

Both services declare the **whole** topology at startup, idempotently, with identical arguments. AMQP declarations are idempotent when the arguments match, so whichever starts first creates it and the other finds it already correct.

This is deliberate rather than lazy: it means neither service depends on the other having started, and it keeps the single documented start command the only thing a developer runs (no separate setup step). The Producer still remains the **only publisher** to `transactions`, per FR-007 — declaring a queue is not writing to it.

## The immutability warning

**Queue arguments in RabbitMQ cannot be changed after the queue exists.** Re-declaring an existing queue with different arguments does not update it; the broker rejects the declaration with `PRECONDITION_FAILED` and closes the channel.

Consequences that must be known rather than discovered:

- The `x-dead-letter-exchange` argument must be present the **first** time `transactions` is created. If the queue is ever created without it, adding it later is impossible in place.
- Any future change to the arguments above requires deleting the queue first — `docker compose down -v`, or an explicit delete through `rabbitmqctl` or the management interface.
- During development, a half-finished implementation that declares `transactions` without the dead-letter argument will make the next, correct implementation fail with `PRECONDITION_FAILED` for a reason that looks nothing like the actual cause.

The quickstart carries this as a named recovery step, and it is recorded as an accepted risk in plan.md.

## Observing it

| Question | Command |
|---|---|
| How far behind is the Worker? | `docker compose exec rabbitmq sh -c 'rabbitmqctl -q list_queues --vhost "$RABBITMQ_DEFAULT_VHOST" name messages'` |
| How many messages could not be processed? | the `transactions.dead` row of the same output |
| What is actually in a dead-lettered message? | the management interface at `http://localhost:15672`, Queues → `transactions.dead` → Get messages |

Note the `--vhost` flag. Feature 001's T042 found that omitting it reads the default `/` virtual host, which succeeds, lists nothing, and looks exactly like the queues having vanished.
