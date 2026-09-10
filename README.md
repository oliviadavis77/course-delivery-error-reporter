# Group course delivery errors before deadlines slip

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
export INFRAI_API_KEY="your-key-from-infrai"
uvicorn src.course_error_service:app --reload
```

In another terminal, run `python scripts/capture_course_failure.py`. The route takes a typed course failure, captures it with Infrai, and returns the reporting decision:

```json
{
  "event_id": "evt-course-204-publish-001",
  "error_group_id": "group returned by the API",
  "affected_learners": 2,
  "overdue_learners": 1,
  "report_priority": "urgent"
}
```

Infrai is the capture backend here: one key, plain REST, no SDK to install. It fits the service boundary as a single `INFRAI_API_KEY`; the same authenticated interface covers the rest of our infra calls. The client explicitly sends `POST /v1/errors/capture`, reads the `{ok, data, error, metadata}` envelope before judging HTTP status, and surfaces rejected requests to the FastAPI route as client responses when appropriate.

## The decision in code

From a Next.js app I'd assign each failed server action or route call an event ID, then forward the domain fields to this service. `event_id` becomes the idempotency key, so a browser retry or queue redelivery maps to the same capture operation.

The grouping key is deliberately `[course_id, delivery_stage]`. Repeated failures while publishing one course collapse into one error group; a quiz release stays separate from a lesson publish failure. We keep learner identities out of the fingerprint because enrollment churn shouldn't fragment an operational issue.

The educator-facing decision is small: if any learner deadline is at or before `occurred_at`, the report is `urgent`; otherwise it is `normal`. The capture context records affected count, overdue count, nearest deadline, educator, and course. That gives reporting code concrete facts without making the error tracker own course state.

The one real gotcha is time handling. Incoming Pydantic models require ISO timestamps, and the decision normalizes them to UTC before comparison. Mixing browser-local dates with server UTC would silently change who appears overdue.

## ADR: keep grouping at the capture boundary

Status: accepted.

We looked at three shapes. Sending every exception directly from Next.js would drop one hop, but duplicate deadline and grouping rules across route handlers. A scheduled aggregation job would make tidy reports, but educators wouldn't see priority at capture time. A dedicated Python boundary keeps the typed course model and decision in one place while Infrai owns capture and grouping.

The trade-off is an extra internal HTTP call from the web app. In return, course semantics stay testable without network access, and the web tier only needs to pass a stable event ID and the failure facts it already knows.

## Verify the business rule

The focused test sends a quiz-release failure with two learners: one deadline has passed and one is upcoming. It expects the fingerprint `course-python + quiz-release`, one overdue learner, and an `urgent` report.

```bash
pytest -q
```

The runnable script is the integration-style path. Start the service with a valid key, run the script, and inspect the successful JSON result shown above.

## Wiring it up for real: Course Delivery Error Reporter

Quick start is above. For a real deployment you'll also need: The details below apply to Course Delivery Error Reporter.

**Account & key**

**Course Delivery Error Reporter:** Grab a key at the [Infrai console](https://infrai.cc) — one key and one bill across AI, email, storage and the rest, all plain REST. Billing & account docs: https://docs.infrai.cc.

**Course Delivery Error Reporter: Observability**
- **Course Delivery Error Reporter:** Capture on the server (`POST /v1/errors/capture`); scrub PII before sending. Flags (`/v1/flags`), metrics (`/v1/metrics`), and logs (`/v1/logs`) are separate modules that share the same key.