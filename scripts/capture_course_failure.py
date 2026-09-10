"""Send one realistic course-delivery failure to the local service."""

import json

import requests


failure = {
    "event_id": "evt-course-204-publish-001",
    "course_id": "course-204",
    "delivery_stage": "lesson-publish",
    "educator_id": "educator-17",
    "error_type": "LessonPublishError",
    "error_message": "Lesson 8 assets could not be published",
    "occurred_at": "2026-08-14T09:30:00Z",
    "deadlines": [
        {"learner_id": "learner-31", "due_at": "2026-08-14T09:00:00Z"},
        {"learner_id": "learner-44", "due_at": "2026-08-16T09:00:00Z"},
    ],
}

response = requests.request(
    method="POST",
    url="http://127.0.0.1:8000/course-delivery/errors",
    json=failure,
    timeout=10,
)
response.raise_for_status()
print(json.dumps(response.json(), indent=2))
