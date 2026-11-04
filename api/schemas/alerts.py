"""Alertmanager webhook payload models (Alertmanager v2 schema).

Alert labels and annotations come from the monitoring stack and may contain
arbitrary text (including prompt-injection attempts). They are parsed as
plain data and stored verbatim - they are never interpreted as instructions
anywhere in the pipeline.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class Alert(BaseModel):
    model_config = ConfigDict(extra="ignore")

    status: Literal["firing", "resolved"]
    labels: dict[str, str] = Field(default_factory=dict)
    annotations: dict[str, str] = Field(default_factory=dict)
    startsAt: str | None = None
    endsAt: str | None = None
    fingerprint: str | None = None
    generatorURL: str | None = None


class AlertmanagerPayload(BaseModel):
    model_config = ConfigDict(extra="ignore")

    receiver: str | None = None
    status: str | None = None
    alerts: list[Alert] = Field(default_factory=list)
    externalURL: str | None = None
    version: str | None = None
