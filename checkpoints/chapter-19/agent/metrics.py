"""Metrics: numbers about the service, counted in memory and read by Prometheus from /metrics.

Three kinds. A Counter only goes up (requests answered); Prometheus computes the rate.
A Gauge goes up and down (is the circuit open now?). A Histogram counts observations in
buckets (how many requests took under 0.1 s, under 0.25 s, ...), so percentiles can be
computed later.

Labels split a metric (by route, by status). Every combination of label values is a
separate series, so labels take a few known values only: a route template, never a URL
with a conversation id in it.
"""

from prometheus_client import Counter, Gauge, Histogram, disable_created_metrics

# Without this, every counter also gets a *_created series (when it started). We don't use it.
disable_created_metrics()  # type: ignore[no-untyped-call]  # the library left it untyped

# Buckets in seconds. Chosen around what matters here: a chat answers in well under a
# second in mock mode, the notes client gives up after about 7 s, a real model may take 10+.
BUCKETS = (0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0)

# The golden signals of the HTTP API: traffic, errors (by status) and latency.
REQUESTS = Counter(
    "http_requests", "HTTP requests answered.", ["method", "route", "status"]
)  # exposed as http_requests_total
REQUEST_SECONDS = Histogram(
    "http_request_duration_seconds",
    "Time to answer an HTTP request.",
    ["method", "route"],
    buckets=BUCKETS,
)

# The model: how long it takes, what it costs (tokens), and why it fails.
LLM_SECONDS = Histogram(
    "llm_request_duration_seconds", "Time the model took to reply.", buckets=BUCKETS
)
LLM_TOKENS = Counter("llm_tokens", "Tokens sent to and received from the model.", ["kind"])
LLM_ERRORS = Counter("llm_errors", "Model calls that failed, by reason.", ["reason"])

# The notes service, seen from the chat.
NOTES_CALLS = Counter(
    "notes_calls",
    "Calls to the notes service: ok, failed, or rejected by the breaker.",
    ["outcome"],
)
NOTES_CIRCUIT_OPEN = Gauge(
    "notes_circuit_open", "1 while the circuit breaker in front of the notes service is open."
)

# The agent loop (chapter 16): how runs end, and every tool call it made.
AGENT_RUNS = Counter(
    "agent_runs", "Agent loop runs, by how they ended (end_turn, max_steps, ...).", ["stop"]
)
AGENT_STEPS = Histogram(
    "agent_steps", "Model calls in one agent run.", buckets=(1, 2, 3, 4, 5, 10, 20)
)
AGENT_TOOL_CALLS = Counter(
    "agent_tool_calls", "Tool calls the model asked for, by tool and outcome.", ["tool", "outcome"]
)

# Events: published to Kafka, then confirmed (delivered) or lost.
EVENTS = Counter("chat_events", "Events, by what happened to them.", ["outcome"])

# Sagas: done, compensated (undone cleanly), or compensation_failed (needs a person).
SAGAS = Counter("sagas", "Sagas run, by how they ended.", ["saga", "outcome"])


def observe_request(method: str, route: str, status: int, seconds: float) -> None:
    """Count one answered HTTP request and its duration."""
    REQUESTS.labels(method, route, str(status)).inc()
    REQUEST_SECONDS.labels(method, route).observe(seconds)


# Context (chapter 19): older turns summarised so the context stays within its budget.
COMPACTIONS = Counter("context_compactions", "Times older turns were summarised (compaction).")
