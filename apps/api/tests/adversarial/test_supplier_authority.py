"""Who is allowed to move a delivery date.

Invariant 7: what authorises an automatic change is deterministic — and
crucially, the authorising fact must be something the sender could not simply
write down. A purchase order number is not a secret; the sign-off at the
bottom of an email is not identification.

The defect these tests were written for: ``message.supplier_id`` was set from
``claim.supplier_name_text`` — the supplier name a model read *out of the
untrusted body* — and the authority check then short-circuited on that field.
Signing an email "Regards, Sri Balaji Spinning" was therefore enough to be
treated as Sri Balaji Spinning.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest

from tests.conftest import make_purchase_order
from textileops.ingestion import pipeline, resolution
from textileops.models.enums import SourceChannel
from textileops.models.org import Supplier

D = Decimal

DELAY_BODY = (
    "Dear sir, regarding order {number}: despatch will be delayed by 10 days. "
    "We will now despatch on 30 June 2026.\nRegards,\n{signature}"
)


def _snapshot(po):
    return (po.status, po.expected_date, po.revised_expected_date)


def test_signing_an_email_with_the_suppliers_name_does_not_make_you_the_supplier(
    session, supplier, yarn
):
    """The critical one. A stranger who guesses a PO number must change nothing."""
    po = make_purchase_order(
        session, supplier, yarn, quantity=D("1000"), expected_in=5,
        number=f"PO-{uuid.uuid4().int % 90000 + 10000}",
    )
    session.flush()
    before = _snapshot(po)

    message = pipeline.receive_message(
        session,
        body=DELAY_BODY.format(number=po.number, signature=supplier.name),
        sender="attacker@totally-unrelated.example",
        channel=SourceChannel.EMAIL,
    )
    pipeline.process_message(session, message)
    session.flush()
    session.refresh(po)

    assert _snapshot(po) == before, (
        "a delivery date moved on the strength of a name typed in the message body"
    )


def test_a_body_derived_supplier_link_is_marked_as_such(session, supplier, yarn):
    """The link may still be made — it just must not carry authority.

    Attaching the message to a supplier is useful for finding it later. What
    the attribution field records is *how* we came to believe it.
    """
    po = make_purchase_order(
        session, supplier, yarn, quantity=D("1000"), expected_in=5,
        number=f"PO-{uuid.uuid4().int % 90000 + 10000}",
    )
    session.flush()

    message = pipeline.receive_message(
        session,
        body=DELAY_BODY.format(number=po.number, signature=supplier.name),
        sender="attacker@totally-unrelated.example",
        channel=SourceChannel.EMAIL,
    )
    pipeline.process_message(session, message)
    session.flush()

    if message.supplier_id is not None:
        assert message.supplier_attribution == pipeline.SUPPLIER_ATTRIBUTION_EXTRACTED
        assert (
            message.supplier_attribution not in pipeline.AUTHORITATIVE_ATTRIBUTIONS
        ), "body-derived attribution must never be in the authoritative set"


def test_the_real_supplier_address_still_works(session, supplier, yarn):
    """The fix must not close the legitimate path.

    Without this, a test suite could 'pass' by refusing everything.
    """
    po = make_purchase_order(
        session, supplier, yarn, quantity=D("1000"), expected_in=5,
        number=f"PO-{uuid.uuid4().int % 90000 + 10000}",
    )
    session.flush()
    before = _snapshot(po)

    message = pipeline.receive_message(
        session,
        body=DELAY_BODY.format(number=po.number, signature=supplier.name),
        sender=supplier.contact_email,
        channel=SourceChannel.EMAIL,
    )
    pipeline.process_message(session, message)
    session.flush()
    session.refresh(po)

    assert _snapshot(po) != before, (
        "the supplier's own address no longer authorises a date change"
    )


def test_an_operator_attributing_the_message_still_authorises_it(
    session, supplier, yarn
):
    """A signed-in person saying "this is from them" is a decision, not a claim."""
    po = make_purchase_order(
        session, supplier, yarn, quantity=D("1000"), expected_in=5,
        number=f"PO-{uuid.uuid4().int % 90000 + 10000}",
    )
    session.flush()
    before = _snapshot(po)

    message = pipeline.receive_message(
        session,
        body=DELAY_BODY.format(number=po.number, signature=supplier.name),
        sender="whatsapp:+919840000000",
        channel=SourceChannel.WHATSAPP,
        supplier_id=supplier.id,
    )
    assert message.supplier_attribution == pipeline.SUPPLIER_ATTRIBUTION_CALLER
    pipeline.process_message(session, message)
    session.flush()
    session.refresh(po)

    assert _snapshot(po) != before


def test_a_shared_public_mail_domain_is_not_evidence(session, supplier, yarn):
    """Suppliers on gmail are ordinary in this trade.

    Matching on domain would mean any gmail address authorises any supplier
    whose contact is a gmail address.
    """
    supplier.contact_email = "sribalaji.mills@gmail.com"
    session.flush()
    po = make_purchase_order(
        session, supplier, yarn, quantity=D("1000"), expected_in=5,
        number=f"PO-{uuid.uuid4().int % 90000 + 10000}",
    )
    session.flush()
    before = _snapshot(po)

    message = pipeline.receive_message(
        session,
        body=DELAY_BODY.format(number=po.number, signature=supplier.name),
        sender="someone.else@gmail.com",
        channel=SourceChannel.EMAIL,
    )
    pipeline.process_message(session, message)
    session.flush()
    session.refresh(po)

    assert _snapshot(po) == before, "any gmail account could move this supplier's dates"


def test_a_private_company_domain_is_still_evidence(session, supplier, yarn):
    """dispatch@ and accounts@ at the same mill are the same mill."""
    supplier.contact_email = "dispatch@sribalaji.example"
    session.flush()
    po = make_purchase_order(
        session, supplier, yarn, quantity=D("1000"), expected_in=5,
        number=f"PO-{uuid.uuid4().int % 90000 + 10000}",
    )
    session.flush()
    before = _snapshot(po)

    message = pipeline.receive_message(
        session,
        body=DELAY_BODY.format(number=po.number, signature=supplier.name),
        sender="accounts@sribalaji.example",
        channel=SourceChannel.EMAIL,
    )
    pipeline.process_message(session, message)
    session.flush()
    session.refresh(po)

    assert _snapshot(po) != before


# --- Entity resolution --------------------------------------------------------


@pytest.mark.parametrize(
    "wildcard",
    ["%", "%%", "Sri%", "_ri Balaji Spinning Mills", "%Spinning%", "S%s"],
    ids=["percent", "double", "prefix", "underscore", "surround", "middle"],
)
def test_a_wildcard_in_an_extracted_name_does_not_resolve_to_anything(
    session, supplier, wildcard
):
    """``ilike`` was handed extracted text unescaped.

    "%" on its own matched the first supplier in the table and came back as an
    *exact name match*, score 1.0, no review — while the honest partial name it
    stands in for would have gone to a person as ambiguous. The text comes out
    of a message body, so this was a way to be told you are whoever the
    database happens to list first.
    """
    session.flush()
    match = resolution.resolve_supplier(session, wildcard)
    assert not (match.resolved and match.method == "exact_name"), (
        f"{wildcard!r} was accepted as an exact name match for "
        f"{getattr(match.entity, 'name', None)!r}"
    )


def test_an_exact_name_still_resolves(session, supplier):
    """The escaping must not break the case it exists to protect."""
    session.flush()
    match = resolution.resolve_supplier(session, supplier.name)
    assert match.resolved
    assert match.entity.id == supplier.id
    assert match.method == "exact_name"


def test_a_name_containing_a_literal_percent_matches_only_itself(session):
    """Escaping means a real "%" in a name is searchable, not a wildcard."""
    odd = Supplier(
        code="S-ODD01",
        name="100% Cotton Traders",
        contact_email="sales@hundredpercent.example",
        default_lead_time_days=10,
    )
    other = Supplier(
        code="S-ODD02",
        name="Anything At All",
        contact_email="sales@anything.example",
        default_lead_time_days=10,
    )
    session.add_all([odd, other])
    session.flush()

    match = resolution.resolve_supplier(session, "100% Cotton Traders")
    assert match.resolved and match.entity.id == odd.id
