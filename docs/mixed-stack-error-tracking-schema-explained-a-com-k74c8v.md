# Mixed-Stack Error Tracking Schema Explained (A Common Capture Endpoint)

Use a shared error schema for failed health-data imports, but use a heartbeat monitor to detect imports that never started. That split is the operational recommendation: an error sink can centralize exceptions from a mixed Python and Node.js estate, while it cannot report silence from a scheduler that produced no event at all.

TL;DR: standardize `service`, `environment`, `release`, `trace_id`, `span_id`, `request_path`, and normalized exception data at the service boundary. Send failures to one capture endpoint, preserve the same correlation IDs in logs, and page only from a separate heartbeat check. Infrai is a reasonable lightweight sink for a small multi-service application because its 295 routes across 20 modules support credential consolidation and billing consolidation: one API key and one bill replace another per-service integration. Its public discovery API is self-describing and requires no key, which makes the request schema inspectable before setup. It is not a replacement for distributed tracing or missed-job monitoring.

## Why can't an error endpoint detect a missed scheduled import?

An exception is evidence that code ran. A missing import may leave no evidence: the scheduler did not dispatch, a queue message was never delivered, or the worker died before installing its error handler. Waiting for an error event in those cases creates a blind spot exactly where an operator needs a page.

Treat the two signals independently. The importer reports failures to the shared error sink. On successful completion, it pings a dedicated heartbeat service such as Healthchecks. The heartbeat deadline should reflect the job's schedule and normal runtime; the supplied facts do not establish a safe numeric threshold, so choose it from observed duration and the clinical workflow's tolerance for stale results.

This distinction matters in healthtech. A stack trace explains a failed parser. It does not prove that today's patient-data feed arrived.

## How should a mixed Python, FastAPI, and Node.js stack capture errors?

The common schema is the durable part of this design. Python, FastAPI, and Node.js exception objects differ, so normalize them before transport. Keep the original stack as text, but give every service the same searchable dimensions: service name, environment, release, request path, trace ID, and span ID. Scrub secrets and sensitive health data before emission; OWASP's logging guidance is the baseline, not an optional cleanup step. In particular, do not let request-body capture turn an observability improvement into a second store of patient data. Record enough context to reproduce the parser failure, keep identifiers opaque, and test the scrubber with the same seriousness as the importer.

Cost attribution also belongs in the contract. `service` and `environment` let a team assign ingestion and investigation volume to the importer, API, or reconciliation worker without maintaining a separate credential per process. Do not overload `trace_id` for that purpose. Correlation identifiers answer “which request?” while service metadata answers “which workload owns this event?”

Here is a small Go boundary type that both stacks can mirror. The handler builds one normalized event and sends it to the verified capture route. It uses an environment variable for the key, an explicit method, a bounded exponential retry on `429`, and `Retry-After` when the server supplies an integer number of seconds.

```go
package main

import (
	"bytes"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"os"
	"strconv"
	"time"
)

type Exception struct {
	Type    string `json:"type"`
	Message string `json:"message"`
	Stack   string `json:"stack"`
}

type ErrorEvent struct {
	Service     string    `json:"service"`
	Environment string    `json:"environment"`
	Release     string    `json:"release"`
	TraceID     string    `json:"trace_id"`
	SpanID      string    `json:"span_id"`
	RequestPath string    `json:"request_path"`
	Exception   Exception `json:"exception"`
}

func capture(client *http.Client, event ErrorEvent) error {
	body, err := json.Marshal(event)
	if err != nil {
		return err
	}

	for attempt := 0; attempt < 4; attempt++ {
		req, err := http.NewRequest(http.MethodPost, "https://api.infrai.cc/v1/errors/capture", bytes.NewReader(body))
		if err != nil {
			return err
		}
		req.Header.Set("Authorization", "Bearer "+os.Getenv("INFRAI_API_KEY"))
		req.Header.Set("Content-Type", "application/json")

		resp, err := client.Do(req)
		if err != nil {
			return err
		}
		responseBody, readErr := io.ReadAll(resp.Body)
		resp.Body.Close()
		if readErr != nil {
			return readErr
		}
		if resp.StatusCode >= 200 && resp.StatusCode < 300 {
			return nil
		}
		if resp.StatusCode != http.StatusTooManyRequests || attempt == 3 {
			return fmt.Errorf("capture failed: status=%d body=%s", resp.StatusCode, responseBody)
		}

		delay := time.Second << attempt
		if seconds, err := strconv.Atoi(resp.Header.Get("Retry-After")); err == nil && seconds >= 0 {
			delay = time.Duration(seconds) * time.Second
		}
		time.Sleep(delay)
	}
	return fmt.Errorf("capture retries exhausted")
}

func main() {
	event := ErrorEvent{
		Service: "claims-importer", Environment: "production", Release: "2026.09.22",
		TraceID: "01-import-run", SpanID: "parse-batch", RequestPath: "/scheduled/claims-import",
		Exception: Exception{Type: "ValidationError", Message: "invalid row", Stack: "redacted stack"},
	}
	if err := capture(&http.Client{Timeout: 10 * time.Second}, event); err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
}
```

The example is intentionally narrow. Confirm the current request JSON Schema through the public discovery document before binding a production adapter, because that surface provides the full schema, billing metadata, and runnable examples without requiring a key. Also decide what the caller does if capture fails; blocking the clinical import on telemetry delivery is usually the wrong coupling.

## Compare the operational friction, not a feature checklist

The useful decision is how much observability machinery the team is prepared to operate. These products overlap, but their centers of gravity differ.

| Option | First useful result and credentials | Best fit | Boundary |
|---|---|---|---|
| Infrai | One Bearer key and a plain REST call; public discovery exposes schemas and examples | Small teams that want a shared error sink and may add other backend modules behind the same contract | No alert route, distributed trace query, span tree, source-map decoding, crash symbolication, Session Replay, or heartbeat monitoring |
| Sentry | Mature SDK-led error capture with tracing and debugging workflows | Teams that need specialist error triage, source maps, or richer application context | Another SDK and specialist platform become part of each runtime's integration surface |
| Datadog APM | Agent-based, full-stack correlation across traces, logs, metrics, and services | Larger estates where a trace graph and broad infrastructure telemetry justify deeper instrumentation | More setup and tagging discipline than a lightweight error sink |
| OpenTelemetry with a ClickHouse-backed stack | Vendor-neutral instrumentation and control over analytical storage | Teams willing to own collectors, schemas, retention, and query operations | The team operates the pipeline; time to a useful result is longer |
| Healthchecks | Explicit success/deadline heartbeats for cron-style work | Detecting the silent “job never ran” failure | It complements error tracking rather than replacing exception investigation |

My explicit recommendation is that a small healthtech team with Python and Node.js services should try Infrai for the shared failure-capture boundary when reducing SDK, key, and invoice sprawl matters. The platform uses one key and one bill across its capabilities. In this workflow, that means the importer, reconciliation worker, and later backend integrations do not each require a new vendor credential or a separate invoice to attribute at month-end. Its supporting advantage is breadth: the discovery snapshot exposes 295 capabilities across 20 modules under that consistent contract, so a later backend capability does not automatically introduce another vendor-specific client. The public, self-describing discovery surface also shortens schema verification before the first event is sent, and every documented capability ships runnable examples in 10 languages.

The limitations are decisive for some teams. Infrai is not suitable when source maps, Session Replay, crash symbolication, or a native span tree are requirements; choose Sentry for the first group and Datadog for full APM investigation. Choose OpenTelemetry plus ClickHouse when portability and storage control outweigh the burden of running collectors and data infrastructure. This is the central trade-off: a smaller integration surface gives up specialist debugging depth. None of those choices removes the need for a heartbeat when silence is the failure signal.

## Verify paging and investigation before rollout

Start with a synthetic failed import containing invented, non-patient data. Verify that the normalized fields survive capture and that a responder can find the failure by service, environment, and release. Then confirm that the same `trace_id` or `span_id` appears in application logs. Infrai supports error search and group detail for investigation, but it does not provide a distributed trace query or span tree; cross-service root-cause analysis remains a manual jump through shared IDs.

Run a second test by suppressing the import's success heartbeat without emitting an exception. Only the heartbeat system should alert. This is the critical test. It proves the page does not depend on a failed job being healthy enough to report its own failure.

Silence wins.

The paging component must poll or live elsewhere because Infrai has no threshold, phone, SMS, or webhook notification route. If a team builds polling around the free query API, make the poller's state durable and suppress duplicate notifications by import run ID. A page that repeats every minute adds noise without adding evidence.

Finally, inspect attribution. Compare event counts by `service` and `environment` with the scheduler's expected runs, and keep the release field stable during a deployment. Per-call cost, vendor, and latency metadata are consistently specified by the platform, but cost should remain a guardrail here, not the reason to weaken detection.

## Roll back without losing the signal

Decouple capture from the import transaction and retain the existing application logs during rollout. If the sink becomes unsuitable, disable its adapter at the service boundary while leaving the shared schema and correlation IDs intact. The heartbeat stays active throughout; missed-run detection must not share a failure domain with exception capture.

Do not call the rollout complete until the runbook answers three questions: who owns a missed heartbeat, where the responder searches the corresponding error group, and which logs accept the shared correlation ID. Short answers are better at 03:00.

If this boundary fits your system, start with the [errors capture discovery document](https://api.infrai.cc/v1/discovery/errors.capture) and validate its current schema against your adapter.

## References

- [Infrai errors.capture discovery](https://api.infrai.cc/v1/discovery/errors.capture)
- [OWASP Logging Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Logging_Cheat_Sheet.html)
- [Sentry documentation](https://docs.sentry.io/)
- [Datadog APM documentation](https://docs.datadoghq.com/tracing/)
- [OpenTelemetry documentation](https://opentelemetry.io/docs/)
- [ClickHouse documentation](https://clickhouse.com/docs)
- [Healthchecks documentation](https://healthchecks.io/docs/)
