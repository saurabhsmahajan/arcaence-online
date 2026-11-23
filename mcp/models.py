"""Frozen shapes for the ops tools: what goes in and what comes out."""
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

# Ids must look exactly like the synthetic ids. Anything else is refused before SQL runs.
CustomerId = Annotated[str, Field(pattern=r"^cust_\d{3}$", description="Customer id, e.g. cust_001")]
OrderId = Annotated[str, Field(pattern=r"^ord_\d{4}$", description="Order id, e.g. ord_1001")]


class Out(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Account(Out):
    customer_id: str
    display_name: str
    plan: Literal["Starter", "Pro", "Team"]
    billing: Literal["monthly", "annual"]
    currency: Literal["EUR", "USD", "INR"]
    status: Literal["active", "suspended", "closed"]
    created_at: datetime
    email_masked: str | None = None  # there is no raw email field, by design
    phone_masked: str | None = None


class Order(Out):
    order_id: str
    customer_id: str
    item: str
    kind: Literal["one_off", "subscription"]
    amount: Decimal
    currency: Literal["EUR", "USD", "INR"]
    purchased_at: datetime
    downloaded: bool
    invoice_id: str | None = None
    invoice_issued_on: date | None = None


class SubscriptionOrder(Out):
    order_id: str
    item: str
    amount: Decimal
    currency: Literal["EUR", "USD", "INR"]
    purchased_at: datetime


class Subscription(Out):
    customer_id: str
    plan: Literal["Starter", "Pro", "Team"]
    billing: Literal["monthly", "annual"]
    currency: Literal["EUR", "USD", "INR"]
    status: Literal["active", "suspended", "closed"]
    subscription_orders: list[SubscriptionOrder]


class AccessibilityInfo(Out):
    """The approved accessibility wording, with its source. Nothing is added to it."""
    citation: str
    statement: str
    note: str


class WriteResult(Out):
    """What a write tool returns. status is preview (dry run), done (committed) or refused (with a reason code)."""
    status: Literal["preview", "done", "refused"]
    reason: str | None = None
    token: str | None = None            # single-use; present only on a preview
    expires_at: str | None = None
    preview: dict[str, str] | None = None
    cap_remaining_after: str | None = None
    refund_id: str | None = None
    cancellation_id: str | None = None
    order_id: str | None = None
    amount: str | None = None
    currency: str | None = None


class PrivacyResult(Out):
    """What a privacy tool returns. A request is only ever opened here; a person decides what happens next."""
    status: Literal["requested", "cancelled", "refused"]
    reason: str | None = None
    kind: Literal["export", "deletion"] | None = None
    request_id: str | None = None
    inventory: dict[str, int] | None = None  # counts only, never the data
    next_step: str | None = None
