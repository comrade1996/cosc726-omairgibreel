"""Pydantic schemas and semantic gates for the Week 3 triage task."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


KNOWN_ORDER_IDS = {
    "A1032", "A1044", "A1051", "A1067", "A1078", "A1080", "A1091", "A1099"
}
POLICY_THRESHOLD_DAYS = 3


class Intent(str, Enum):
    late_delivery = "late_delivery"
    refund = "refund"
    address_change = "address_change"
    cancel_and_refund = "cancel_and_refund"
    other = "other"


class Action(str, Enum):
    check_status = "check_status"
    request_approval = "request_approval"
    escalate_to_human = "escalate_to_human"
    reply_only = "reply_only"


class TriageResult(BaseModel):
    """Shape-level contract generated from one source of truth."""

    model_config = ConfigDict(extra="forbid")

    intent: Intent = Field(description="Classification for exactly one support email.")
    order_id: str | None = Field(
        default=None,
        pattern=r"^A[0-9]{4}$",
        description="Order ID stated in the email, or null when it is not stated.",
    )
    days_late: int | None = Field(
        default=None,
        ge=0,
        le=365,
        description="Whole days late, or null when the delay is not stated.",
    )
    proposed_action: Action = Field(
        description="A proposed workflow action; it does not claim execution."
    )
    evidence_ids: list[str] = Field(
        default_factory=list,
        description="IDs from the supplied evidence block that support the triage.",
    )


class ValidatedTriage(TriageResult):
    """Triage result plus reference and cross-field policy checks."""

    @field_validator("order_id")
    @classmethod
    def order_must_exist(cls, value: str | None) -> str | None:
        if value is not None and value not in KNOWN_ORDER_IDS:
            raise ValueError(f"order_id {value!r} is well-formed but unknown")
        return value

    @model_validator(mode="after")
    def fields_must_cohere(self) -> "ValidatedTriage":
        if (
            self.intent is Intent.late_delivery
            and self.proposed_action is Action.request_approval
        ):
            if self.days_late is None:
                raise ValueError("approval proposed without a counted delay")
            if self.days_late < POLICY_THRESHOLD_DAYS:
                raise ValueError(
                    f"approval proposed at {self.days_late} days; "
                    f"policy requires {POLICY_THRESHOLD_DAYS}+"
                )
        if self.intent is Intent.late_delivery and self.order_id is None:
            raise ValueError("late_delivery without an order_id")
        return self
