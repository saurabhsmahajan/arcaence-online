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
