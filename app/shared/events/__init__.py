"""Domen event'lari va transactional outbox (05, ADR-033).

    await write_outbox(db, schema="commerce", event_type="commerce.order.confirmed", ...)

Event biznes o'zgarishi bilan bitta tranzaksiyada yoziladi; uni `app.workers` tarqatadi.
"""
