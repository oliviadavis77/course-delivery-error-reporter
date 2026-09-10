"""FastAPI boundary for course-delivery failures and educator reporting."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from .infrai_client import InfraiClient, InfraiError


class LearnerDeadline(BaseModel):
    learner_id: str
    due_at: datetime


class CourseDeliveryFailure(BaseModel):
    event_id: str = Field(min_length=1)
    course_id: str = Field(min_length=1)
    delivery_stage: str = Field(min_length=1)
    educator_id: str = Field(min_length=1)
    error_type: str = Field(min_length=1)
    error_message: str = Field(min_length=1)
    occurred_at: datetime
    deadlines: list[LearnerDeadline]


class CaptureResult(BaseModel):
    event_id: str
    error_group_id: str | None = None
    affected_learners: int
    overdue_learners: int
    report_priority: str


def build_capture_payload(failure: CourseDeliveryFailure) -> tuple[dict[str, Any], CaptureResult]:
    now = failure.occurred_at.astimezone(timezone.utc)
    overdue = sum(deadline.due_at.astimezone(timezone.utc) <= now for deadline in failure.deadlines)
    priority = "urgent" if overdue else "normal"
    upcoming = min((item.due_at for item in failure.deadlines), default=None)
    payload = {
        "title": f"Course delivery failed during {failure.delivery_stage}",
        "message": failure.error_message,
        "level": "error",
        "fingerprint": [failure.course_id, failure.delivery_stage],
        "exception": {
            "type": failure.error_type,
            "value": failure.error_message,
        },
        "context": {
            "course_id": failure.course_id,
            "educator_id": failure.educator_id,
            "delivery_stage": failure.delivery_stage,
            "affected_learners": len(failure.deadlines),
            "overdue_learners": overdue,
            "next_deadline": upcoming.isoformat() if upcoming else None,
            "report_priority": priority,
        },
    }
    result = CaptureResult(
        event_id=failure.event_id,
        affected_learners=len(failure.deadlines),
        overdue_learners=overdue,
        report_priority=priority,
    )
    return payload, result


def create_app(client: InfraiClient | None = None) -> FastAPI:
    app = FastAPI(title="Course delivery error service")

    @app.post("/course-delivery/errors", response_model=CaptureResult)
    def capture_course_error(failure: CourseDeliveryFailure) -> CaptureResult:
        payload, result = build_capture_payload(failure)
        try:
            capture_client = client or InfraiClient()
            captured = capture_client.capture_error(payload, idempotency_key=failure.event_id)
        except InfraiError as exc:
            client_status = exc.status_code if 400 <= exc.status_code < 500 else 502
            raise HTTPException(
                status_code=client_status,
                detail={"code": exc.code, "message": str(exc)},
            ) from exc
        return result.model_copy(
            update={"error_group_id": captured.get("error_group_id")}
        )

    return app


app = create_app()
