from datetime import datetime, timezone

from src.course_error_service import CourseDeliveryFailure, build_capture_payload


def test_overdue_deadline_makes_report_urgent_and_preserves_grouping() -> None:
    failure = CourseDeliveryFailure.model_validate(
        {
            "event_id": "evt-101",
            "course_id": "course-python",
            "delivery_stage": "quiz-release",
            "educator_id": "teacher-7",
            "error_type": "QuizReleaseError",
            "error_message": "Quiz release was interrupted",
            "occurred_at": datetime(2026, 8, 14, 10, tzinfo=timezone.utc),
            "deadlines": [
                {"learner_id": "a", "due_at": "2026-08-14T09:00:00Z"},
                {"learner_id": "b", "due_at": "2026-08-15T09:00:00Z"},
            ],
        }
    )

    payload, result = build_capture_payload(failure)

    assert payload["fingerprint"] == ["course-python", "quiz-release"]
    assert payload["exception"] == {
        "type": "QuizReleaseError",
        "value": "Quiz release was interrupted",
    }
    assert payload["context"]["overdue_learners"] == 1
    assert result.report_priority == "urgent"
