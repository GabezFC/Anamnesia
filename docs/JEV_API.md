# TypeSafe JEV / System One API — reference for Memory Gateway

**Researched:** 2026-09-27
**SDK introspected:** `typesafe-sdk==0.7.1` (confirmed via `python -c "import typesafe_sdk; print(typesafe_sdk.__version__)"` → `0.7.1`) as installed in the project's virtualenv (`.venv`).

Every external claim below carries its source URL and the date it was checked. Anything
that could not be confirmed against an official source or the installed code is marked
**NOT VERIFIED**.

---

## 1. Model catalogue

### 1.1 What the account actually exposes

`python scripts/probe_jev_models.py` (run 2026-09-27, `GET /v1/models`) returns exactly two entries:

| `name` | `description` | `release_date` (raw) |
| --- | --- | --- |
| `jev-latest` | `The latest iteration of TypeSafe's System One Model: Jev` | `2026-09-10T18:38:01.391457+00:00` |
| `jev-preview` | `A preview version of \`jev-latest\`: should be better in most ways` | `2026-09-10T18:39:06.057655+00:00` |

Two observations from this probe:

- **`jev-1.13.0` is not in the list.** It is a *pinned versioned ID*, not an alias.
  The official docs state this explicitly: “`GET /v1/models` returns the names your account
  can send in the `model` field … It currently lists the aliases. **Versioned IDs such as
  `jev-1.13.0` are accepted by the `model` field whether or not they appear in the list.**”
  — <https://docs.typesafe.ai/models> (checked 2026-09-27).
  So the repo's config value `jev-1.13.0` is valid and is the *pinned* target of both
  aliases; it simply never shows up in the listing.
- **`release_date` is a full ISO-8601 timestamp, not `YYYY-MM-DD`.** Both the SDK docstring
  (`ModelMetadata.release_date`: “Model release date, formatted as YYYY-MM-DD”) and the
  OpenAPI schema (`examples=["2026-09-15"]`) promise a date-only string; the live API
  returns a timestamp. The field is typed `str`, so nothing breaks, but do **not** parse it
  with `date.fromisoformat` on the 10-char assumption.

### 1.2 Aliases vs pinned version

Per <https://docs.typesafe.ai/models> (checked 2026-09-27):

| Alias | Points to | Meaning |
| --- | --- | --- |
| `jev-latest` | `jev-1.13.0` | Most recent stable, official release. Default in the client SDKs and in the docs' examples. |
| `jev-preview` | `jev-1.13.0` | Most recent release, official or not. Moves ahead of `jev-latest` when a preview build exists. |

The same page: “`jev-preview` currently points to the same model as `jev-latest`. There is
no preview build available right now.” It also warns that “An alias moves when a new
release ships, so the answers behind it can change without a change on your side … If you
have tuned confidence thresholds against a specific version, pin that version's ID instead
of the alias.”

**Implication for Memory Gateway:** pinning `jev-1.13.0` is the documented-correct choice
for a system with tuned thresholds. Today it is behaviourally identical to `jev-latest` and
`jev-preview`; that identity is *not* contractual and will break on the next release.

The response's `model` field reports the versioned ID that actually answered, and “May
differ from the alias supplied in the request” (`_schemas/models.py`, `SystemOneResponse.model`).
Log it.

### 1.3 Capabilities / input

- Text only: “String, JSON object, or array of text values. No image, audio, or video
  input.” — <https://docs.typesafe.ai/models> (2026-09-27).
- English is the primary training language; other languages incl. CJK “are handled but not
  equally well” — <https://docs.typesafe.ai/models#language-support> (2026-09-27).
- Not fine-tuned or LoRA-adapted per account; not trained on customer requests/responses —
  <https://docs.typesafe.ai/models#customizing-jev> and `#data-handling` (2026-09-27).
- Known weaknesses have a dedicated page: <https://docs.typesafe.ai/model-jaggedness/jev-1.13>
  (linked from the Models page; content of that page **NOT VERIFIED** — not read in this pass).

---

## 2. Pricing

From <https://docs.typesafe.ai/models> (checked 2026-09-27), the *only* official per-model
pricing table:

| Jev 1.13 (`jev-1.13.0`) | |
| --- | --- |
| Price (per Btok / per Mtok) | **$42 / $0.042** |

Verbatim notes on that page: “**Price:** Charged per input token. **Output tokens are
free.** A Btok is a billion tokens and an Mtok is a million tokens.”

Corroborated by the vendor blog: “Input tokens: $0.042 / MTok ($42 per billion tokens).
Output tokens: FREE (too cheap to meter).” —
<https://typesafe.ai/blog/introducing-system-one-models-and-jev> (checked 2026-09-27).
The same post adds: “we expect [pricing] to go down, not up.”

The SDK's generated wire schema agrees on the billing model:
`Usage.input_tokens` = “Number of **billable** input tokens used to evaluate the request”;
`Usage.output_tokens` = “Output tokens are **currently free of charge**.”
(`typesafe_sdk/_schemas/models.py`).

**The repo's recorded price of $0.042 per 1M input tokens with free output is CONFIRMED
as of 2026-09-27.**

- There is **no per-model price differentiation documented**: the Models page lists one
  price row, for Jev 1.13. Whether `jev-preview` would ever be priced differently is
  **NOT VERIFIED** (not addressed by any official page found).
- `https://typesafe.ai/pricing` returns **404 Page Not Found** (checked 2026-09-27). The
  Models page is the pricing source of record.
- Higher rate limits (not different prices) are offered on “custom and enterprise plans”
  via sales@typesafe.ai — <https://docs.typesafe.ai/models> (2026-09-27). Enterprise pricing
  is **NOT VERIFIED**.

### 2.1 Is there a pricing endpoint? — No.

Checked directly, not inferred. `GET https://api.typesafe.ai/openapi.json` (HTTP 200,
14,158 bytes, fetched 2026-09-27) declares exactly two paths:

```
paths: ['/v1/systemone', '/v1/models']
info.title: "TypeSafe", info.version: "0.2.0"
```

Grepping the whole spec for `price`, `cost`, `limit`, `rate`, `64`, `32` yields **zero**
hits for price/cost/limit — the only `token` hits are the `usage.input_tokens` /
`usage.output_tokens` fields, and the only `rate` hits are prose about the Score primitive
(“What the model should rate”).

Correspondingly, the SDK has no pricing surface: `typesafe_sdk.__all__` exposes only
clients, question types, answer/response types, `RetryPolicy`, errors, and `constants`.
`ModelMetadata` carries only `name`, `description`, `release_date` — **no price, no context
limit, no rate limit**.

**Conclusion: neither the API nor the SDK exposes pricing or limits programmatically. Any
price or limit in Memory Gateway's config is a hardcoded transcription of the docs page and
must be re-checked manually. There is nothing to poll.**

---

## 3. Token / context limits

From <https://docs.typesafe.ai/models> (checked 2026-09-27), for `jev-1.13.0`:

| | |
| --- | --- |
| Context length | **64k tokens per request; 32k tokens for `state` plus the longest question** |
| Rate limits | **250,000 tokens per second / 1,200 requests per minute** |

Verbatim elaboration from that page:

> **Context length:** Jev ingests the `state` once and evaluates every question against it
> in parallel. The 64k budget covers the `state` plus **all questions combined**; the 32k
> budget applies to the `state` plus the **single longest** question.

> **Rate limits:** Measured in tokens per second and requests per minute. A request over
> either limit returns `429 Too Many Requests`. Our client SDKs retry with backoff by
> default and honor the `retry-after` header when the response carries one.

> **Rate limits are adjusting dynamically.** We are serving a very large volume of demand,
> and the limits above can change without notice while we do … Higher limits are available
> on custom and enterprise plans.

**The repo's assumption (64k per request, 32k for state + longest question) is CONFIRMED
as of 2026-09-27**, with the caveat that the 64k figure covers state + *all* questions
summed, so a fan-out of many questions consumes the 64k budget even when each individual
question is small.

Other documented per-question caps (from <https://docs.typesafe.ai/api>, checked 2026-09-27):

- **Choice:** “You can have a maximum of **255 options** per Choice.”
- **Score:** “A Score should have at least two levels; the API accepts up to **10**.”
  (The SDK enforces only ≥1 locally — see §4.4.)

Not found anywhere and therefore **NOT VERIFIED**:

- Maximum number of questions per request (only the 64k token budget bounds it).
- Any monthly/daily quota, spend cap, or concurrency limit distinct from the TPS/RPM figures.
- Whether rate limits are per-account, per-key, or per-org.
- Any documented tokenizer or way to count tokens client-side before sending.

---

## 4. Python SDK 0.7.1 — exact shapes

All of §4 is from reading the installed source at
`.venv/Lib/site-packages/typesafe_sdk/`. This is authoritative for this repo.

### 4.1 Package layout

```
typesafe_sdk/__init__.py           public re-exports (__all__)
typesafe_sdk/constants.py          public env-var names + defaults
typesafe_sdk/_version.py           __version__ from importlib.metadata
typesafe_sdk/_core/constants.py    internal protocol constants (paths, headers)
typesafe_sdk/_core/config.py       Config.resolve + validation
typesafe_sdk/_core/endpoints.py    prepare_system_one / prepare_models (body construction)
typesafe_sdk/_core/transport.py    prepare/send, headers, logging
typesafe_sdk/_core/question_types.py   Noul / Choice / Score + TypedDict forms
typesafe_sdk/_core/questions.py    normalize_questions (client-side validation)
typesafe_sdk/_core/response_types.py   SystemOneResponse / *Answer / Usage / ModelMetadata
typesafe_sdk/_core/retry.py        RetryPolicy
typesafe_sdk/_core/errors.py       exception hierarchy + retry-after parsing
typesafe_sdk/_schemas/models.py    generated from https://api.typesafe.ai/openapi.json
typesafe_sdk/_core/client/sync/    TypeSafeClient, Models
typesafe_sdk/_core/client/aio/     AsyncTypeSafeClient, AsyncModels
```

`_schemas/models.py` header: `# generated by datamodel-codegen: filename: https://api.typesafe.ai/openapi.json`
— i.e. the SDK's wire models are a direct codegen of the live OpenAPI spec.

### 4.2 `typesafe_sdk.constants` (full dump)

```python
API_KEY_ENV        = "TYPESAFE_API_KEY"        # env var for the API key
BASE_URL_ENV       = "TYPESAFE_BASE_URL"       # env var for the API base URL
DEFAULT_MODEL_ENV  = "TYPESAFE_DEFAULT_MODEL"  # env var for the default model
LOG_LEVEL_ENV      = "TYPESAFE_LOG_LEVEL"      # env var for the logging level
DEFAULT_BASE_URL   = "https://api.typesafe.ai"
DEFAULT_MODEL      = "jev-latest"
DEFAULT_TIMEOUT    = 10.0                      # seconds, per HTTP operation
```

**There are no token, context, price, or size constants in the SDK.** `_core/constants.py`
(internal) holds only `MAX_ERROR_BODY_LENGTH = 200`, the two paths
(`SYSTEM_ONE_PATH = "/v1/systemone"`, `MODELS_PATH = "/v1/models"`), and header names.

Notable headers the SDK sets/reads (`_core/constants.py`, `_core/transport.py`):
`Authorization: Bearer <key>`, `Accept: application/json`, `User-Agent: typesafe-sdk/<ver>`,
`X-TypeSafe-SDK`, `X-TypeSafe-Runtime`, `X-TypeSafe-Retry-Count` (set on retries only),
and it reads `x-typesafe-request-id`, `retry-after`, `retry-after-ms`.
Secret headers redacted from logs: `authorization`, `proxy-authorization`, `x-api-key`,
`api-key`, `cookie`, `set-cookie`. **Request and response bodies are NOT redacted** — the
docstring says so explicitly, so `TYPESAFE_LOG_LEVEL=debug` will log state contents.

### 4.3 `TypeSafeClient` constructor

```python
TypeSafeClient(
    *,
    api_key: str | None = None,          # else TYPESAFE_API_KEY; required
    model: str | None = None,            # else TYPESAFE_DEFAULT_MODEL, else "jev-latest"
    retry: RetryPolicy | None = None,    # None -> RetryPolicy() defaults
    timeout: float | httpx2.Timeout | None = None,   # None -> http_client.timeout, else 10.0
    headers: Mapping[str, str] | None = None,
    transport: httpx2.BaseTransport | None = None,   # mutually exclusive with http_client
    http_client: httpx2.Client | None = None,
    base_url: str | None = None,         # else TYPESAFE_BASE_URL, else https://api.typesafe.ai
)
```

- Explicit args win over env vars; empty/whitespace-only env values are ignored.
- API key validation (`_core/config.py`): stripped; rejected if empty, non-ASCII,
  non-printable, or containing a space → `TypeSafeError`.
- `transport` + `http_client` together → `ValueError`.
- Non-finite or ≤0 timeout → `TypeSafeError`.
- Context manager (`with TypeSafeClient() as client:`); `close()` closes the underlying
  httpx2 client **including a user-supplied one**.
- `client.models` is a `cached_property` returning `Models`.
- The SDK uses **`httpx2`**, not `httpx` (both are installed in this venv).
- Async twin: `AsyncTypeSafeClient` / `AsyncModels`, same signatures.

### 4.4 `TypeSafeClient.system_one` — full signature

```python
def system_one(
    self,
    state: JSONContent,
    questions: Mapping[str, Question],
    *,
    model: str | None = None,
    retry: RetryPolicy | None = None,
    timeout: float | httpx2.Timeout | None = None,
    extra_headers: Mapping[str, str] | None = None,
    extra_body: Mapping[str, JSONValue | None] | None = None,
    response_model: type[ResponseT] | None = None,
) -> SystemOneResponse | ResponseT
```

`state` and `questions` are **positional-or-keyword**; everything else is keyword-only.
Two `@overload`s: `response_model=None` → `SystemOneResponse`; `response_model=SomeModel`
→ `SomeModel`.

Parameter semantics (from the docstring):

| Param | Meaning |
| --- | --- |
| `state` | Text, a JSON object, or an array to evaluate. Type `JSONContent = str \| Mapping[str, JSONValue \| None] \| Sequence[JSONValue \| None]`. |
| `questions` | **Nonempty** mapping of names → question objects or raw dicts. |
| `model` | Model override; `None` inherits the client default. |
| `retry` | `RetryPolicy` override **for this call only**. |
| `timeout` | Per-call HTTP timeout override, in seconds (or `httpx2.Timeout`). |
| `extra_headers` | Extra request headers. (Auth, SDK-identification and `Accept` are re-applied afterwards in `transport.prepare`, so they cannot be overridden.) |
| `extra_body` | Extra **top-level** body fields, shallow-merged **over** the body after `state`/`model`/`questions` are set. Last-write-wins: a colliding key overrides, objects are replaced not deep-merged. |
| `response_model` | Optional Pydantic `BaseModel` describing the JSON body, including nested answer models. |

**Exact wire body** built by `_core/endpoints.prepare_system_one`:

```python
body = {
    "state": state,
    "model": config.default_model if model is None else model,
    "questions": normalize_questions(questions),
}
if extra_body is not None:
    body.update(extra_body)
# POST {base_url}/v1/systemone, Content-Type: application/json
```

Note: `model` is **always** sent, even when the caller passes `model=None` — the client
default is substituted. Matches the OpenAPI `SystemOneRequest`, where `model` is required.

Client-side validation before the request (`_core/questions.normalize_questions`):

- Empty `questions` → `TypeSafeError("At least one question is required.")`
- A dict question without a nonempty string `"type"` → `TypeSafeError`
- `type in ("choice", "score")` without `"criteria"` → `TypeSafeError('Question "X" requires "criteria".')`
- `score` with empty `criteria` → `TypeSafeError('Score question "X" has no criteria; at least one score is required.')`
- **The SDK does NOT enforce** the documented API caps (Score ≤10 levels / ≥2 levels,
  Choice ≤255 options) nor any token budget. Those are server-side → expect `422`.

Declared raises:

| Exception | When |
| --- | --- |
| `TypeSafeError` | Questions empty, or a Score's criteria list empty (raised locally, before any HTTP call) |
| `TypeSafeAPIError` | Unsuccessful HTTP response after retries |
| `TypeSafeAPIConnectionError` | Cannot connect / times out after retries |
| `TypeSafeAPIResponseValidationError` | Response body does not match the response model |

### 4.5 Question types — Noul / Choice / Score

Each exists in **two** forms, both accepted by `questions`: a Pydantic object (`Noul`,
`Choice`, `Score`) and a `TypedDict` (`NoulModel`, `ChoiceModel`, `ScoreModel`).
`Question = Noul | Choice | Score | QuestionModel`; `Questions = Mapping[str, Question]`.

The Pydantic forms share `_Question`: `extra="forbid"` (unknown kwargs rejected) plus a
wrap-serializer that **omits top-level fields left at `None`** from the wire body, while
preserving user-supplied `None` values *nested inside* `criteria`/`instructions`.

#### `Noul` — yes/no. Use when the answer is a single true/false proposition.

```python
class Noul:
    type: Literal["noul"] = "noul"
    instructions: JSONContent | None = None
    criteria: NoulCriteria | None = None

class NoulCriteria(TypedDict, total=False, closed=True):
    true:  JSONContent | None   # description of the yes outcome
    false: JSONContent | None   # description of the no outcome
```

Docs: <https://docs.typesafe.ai/primitives/noul> (2026-09-27) — “Use a Noul when the answer
is yes or no.” The answer is a single probability; **a Noul has no `confidence` field**
because “A Noul's probability distribution has only two outcomes, yes and no, so the single
`noul` value describes it completely.” A Noul value is *not* a magnitude scale — if you
want degree, use a Score.

#### `Choice` — pick one of a named set. Unordered options.

```python
class Choice:
    type: Literal["choice"] = "choice"
    criteria: Mapping[str, JSONContent | None]   # REQUIRED
    instructions: JSONContent | None = None
```

`criteria` maps option label → description, or `None` for “interpreted by its name alone”.
Docs: <https://docs.typesafe.ai/primitives/choice> (2026-09-27) — use when “the answer is one
of a fixed set of options”; max 255 options; add an `other` / `none of the above` option
when the list may not cover every input; both option names *and* descriptions are sent to
the model.

#### `Score` — position on an ordered rubric.

```python
class Score:
    type: Literal["score"] = "score"
    criteria: Sequence[JSONContent]   # REQUIRED, nonempty, ORDERED
    instructions: JSONContent | None = None
```

“A nonempty, ordered list of text, object, or array descriptions, one per score **from
zero**” — the index in the list *is* the score level. Docs:
<https://docs.typesafe.ai/primitives/score> (2026-09-27) — use when the answer is “a
position on a spectrum you can describe in steps”; ≥2 levels recommended, API accepts ≤10.

#### Which to use

| Situation | Type |
| --- | --- |
| Single true/false proposition | `Noul` |
| One of N unordered labels | `Choice` |
| Ordered rubric / magnitude | `Score` |

All three can be mixed in one request; every question is evaluated **independently and in
parallel against the same state**, so adding questions barely changes latency but does cost
input tokens and consumes the 64k budget
(<https://docs.typesafe.ai/> and <https://docs.typesafe.ai/concepts/state>, 2026-09-27).

`instructions` and every `criteria` value may be a string, a JSON object, or an array —
useful to attach data the question refers to (referenced by backticked field name)
(<https://docs.typesafe.ai/api#question-types>, 2026-09-27).

**Doc/SDK discrepancy on `instructions`:** the HTTP API reference marks `instructions`
**required** for all three question types (<https://docs.typesafe.ai/api>, 2026-09-27),
whereas both the SDK (`instructions: JSONContent | None = None`) and the generated OpenAPI
model (`Field(None, ...)`) treat it as optional — and the SDK *omits* it from the body when
it is `None`. Treat `instructions` as effectively required in practice; sending a question
without it is **NOT VERIFIED** as working.

### 4.6 Response shapes

```python
class SystemOneResponse(Response):     # Response = Schema + _ResponseMixin
    model: str                                      # versioned ID that answered
    usage: Usage                                    # required field, not Optional
    answers: dict[str, Answer] = {}                 # default_factory=dict

    # cached_property views over `answers`:
    nouls:   dict[str, NoulAnswer]
    choices: dict[str, ChoiceAnswer]
    scores:  dict[str, ScoreAnswer]

    # from _ResponseMixin:
    request_id: str            # cached_property; x-typesafe-request-id
                               # raises TypeSafeError if the header was absent
    raw_http_response: httpx2.Response   # status, headers, raw body
```

`Schema` config: `extra="ignore"`, **`frozen=True`** (immutable), `strict=True`.
So unknown future fields are dropped silently, and you cannot mutate a response.

```python
class NoulAnswer:
    type: Literal["noul"] = "noul"
    noul: float          # 0..1 probability that the answer is yes. NO confidence field.

class ChoiceAnswer:
    type: Literal["choice"] = "choice"
    choice: str                        # highest-probability option name
    confidence: float                  # 0..1, derived from the distribution
    probabilities: dict[str, float]    # every option -> probability, sums to ~1

class ScoreAnswer:
    type: Literal["score"] = "score"
    score: float                       # probability-weighted mean; may sit between levels
    confidence: float                  # 0..1
    legend: dict[int, str | dict | list]   # level -> its description  (INT keys in SDK)
    probabilities: dict[int, float]        # level -> probability      (INT keys in SDK)

Answer = Annotated[NoulAnswer | ChoiceAnswer | ScoreAnswer, Field(discriminator="type")]
```

**Wire vs SDK key type:** on the wire, `legend` and `probabilities` on a Score are keyed by
*string* level (`{"0": ..., "1": ...}`); the SDK coerces them to **`int`** keys. Confirmed
in both the code (`dict[int, str | dict | list]` with the comment “JSON object keys are
strings; `dict[int, ...]` tells Pydantic to coerce them”) and the docs: “The SDK keys
`probabilities` and `legend` by integer level rather than by string.”
(<https://docs.typesafe.ai/primitives/score>, 2026-09-27). Index them with `0`, not `"0"`.

#### `Usage` — and whether it can be `None`

```python
class Usage(wire.Usage):
    model_config = ConfigDict(extra="ignore", frozen=True, strict=True)
    input_tokens:  int | None = None
    output_tokens: int | None = None
```

Precise answer to “can usage be None?”:

- **`SystemOneResponse.usage` is a required, non-Optional field.** It is always a `Usage`
  instance. A response body missing `usage` entirely raises
  `TypeSafeAPIResponseValidationError` (field_path `"usage"`).
- **`usage.input_tokens` and `usage.output_tokens` CAN each be `None`.** The SDK widens the
  generated wire model (where both are required `int`) to `int | None = None`, with the
  docstring “or `None` when the API did not report it.”

**Therefore, for cost accounting: guard on the fields, not on the object.**

```python
tokens_in = resp.usage.input_tokens or 0   # never `if resp.usage is None`
cost_usd = tokens_in / 1_000_000 * 0.042   # output tokens are free
```

#### Forward-compatibility behaviour (`_prepare_system_one_response`)

- An answer whose `type` is not in `{"noul","choice","score"}` is **dropped** from
  `answers` with a `logger.warning("Ignoring answer %r with unrecognized type %r", ...)`.
  The raw payload stays reachable via `response.raw_http_response`.
- An answer that is not a dict, or whose `type` is not a string →
  `TypeSafeAPIResponseValidationError` at `answers.<name>.type`.
- If you pass a custom `response_model` that declares extra fields named after your
  question ids, those answers are *also* lifted to top-level keys of the same name. This is
  how you get statically-typed per-question attributes.

`ListModelsResponse` / `ModelMetadata`:

```python
class ModelMetadata(Schema):
    name: str; description: str; release_date: str     # no price, no limits

class ListModelsResponse(Response):
    models: tuple[ModelMetadata, ...]
```

`client.models.list(*, retry=None, timeout=None, extra_headers=None) -> ListModelsResponse`.
Note `ListModelsResponse.models` is a **tuple**, and the object is frozen.
(`scripts/probe_jev_models.py` uses `getattr(ms, "data", ms)`, which falls through to the
response object itself since there is no `.data` — the printed `('models', (...))` tuple is
an artifact of that fallback, not the SDK's shape.)

### 4.7 `RetryPolicy` — retry & timeout behaviour

```python
@dataclass(frozen=True)
class RetryPolicy:
    max_retries: int = 2                  # retries AFTER the initial attempt; 0 disables
    backoff_initial: float = 0.5          # seconds; doubled each attempt; 0 disables backoff
    backoff_max: float = 5.0              # seconds; 0 disables backoff
    backoff_jitter: float = 0.25          # fraction of each delay randomly SUBTRACTED, 0..1
    http_statuses: set[int] = {408, 429, *range(500, 600)}
    respect_retry_after: bool = True       # honour `Retry-After` / `retry-after-ms`
    api_connection_error: bool = True      # retry TypeSafeAPIConnectionError
    api_timeout_error: bool = True         # retry TypeSafeAPITimeoutError
    exceptions: set[type[BaseException]] = set()   # extra retryable types
    predicate: Callable[[BaseException], bool] | None = None
    timeout: float | None = 30.0           # TOTAL retry budget per SDK call, incl. delays
```

Behaviour details, read from the code:

- **Two independent timeouts.** `TypeSafeClient(timeout=...)` / `system_one(timeout=...)`
  is the **per-HTTP-operation** timeout, default `DEFAULT_TIMEOUT = 10.0`s.
  `RetryPolicy.timeout` (default `30.0`s) is the **total budget for the whole SDK call**,
  including the initial attempt and all backoff delays. `None` disables the budget.
  Worst case with defaults: 3 attempts × 10s + delays, capped by the 30s budget.
- Stop condition: `stop_after_attempt(max_retries + 1) | stop_before_delay(timeout)` — it
  “Stops **before** a retry whose delay would reach or exceed the budget, re-raising the
  last error.” `reraise=True`, so you get the underlying `TypeSafe*` error, never a
  tenacity `RetryError`.
- Wait: if `respect_retry_after` and the error carries `retry-after-ms` (ms) or
  `retry-after` (seconds, or an HTTP-date), that value wins. Otherwise exponential:
  `min(exponential, exponential * (1 - random()*jitter))` where
  `exponential = ldexp(backoff_initial, attempt-1)` capped at `backoff_max`.
- `retry-after-ms` is checked **before** `retry-after`. A negative `retry-after` is treated
  as "no value"; an HTTP-date is converted to a non-negative ms delay.
- Retryable by default: connection errors, timeouts, and HTTP `408`, `429`, `500–599`.
  `529 Overloaded` (documented at <https://docs.typesafe.ai/api>, 2026-09-27) falls inside
  `range(500, 600)`, so it **is** retried by default. `400/401/403/404/422` are **not**.
- Each retry sets header `X-TypeSafe-Retry-Count: <n>` and logs
  `"<METHOD> <url> retry <n>"` at INFO. Any caller-supplied `X-TypeSafe-Retry-Count` in
  `extra_headers` is stripped.
- Validation in `__post_init__`: `max_retries` must be a non-negative int; backoff values
  non-negative & finite; `0 <= backoff_jitter <= 1`; `timeout` positive & finite —
  otherwise `TypeSafeError`.
- Override precedence: `system_one(retry=...)` builds a fresh tenacity policy for that call
  only; otherwise the client-level policy (`RetryPolicy()` defaults if none given) is used.
  Policies are `.copy()`-ed per send, so state is not shared across calls.

The docs confirm the intent: “Our client SDKs retry with backoff by default and honor the
`retry-after` header” (<https://docs.typesafe.ai/models>, 2026-09-27) and “Our client SDKs
handle this automatically, so no extra handling is needed if you use one of our SDKs with
its default retry policy” (<https://docs.typesafe.ai/api#handling-rate-limits>, 2026-09-27).

### 4.8 Error classes

```
TypeSafeError                                (base; also local validation failures)
└── TypeSafeAPIError                         (.status, .body, .headers, .endpoint, .request_id)
    ├── TypeSafeBadRequestError              400
    ├── TypeSafeAuthenticationError          401
    ├── TypeSafePermissionDeniedError        403
    ├── TypeSafeNotFoundError                404
    ├── TypeSafeUnprocessableEntityError     422
    ├── TypeSafeRateLimitError               429   (+ .retry_after_ms: float | None)
    ├── TypeSafeInternalServerError          any >= 500
    └── TypeSafeAPIResponseValidationError   2xx body failed schema (+ .field_path)

TypeSafeError, ConnectionError
└── TypeSafeAPIConnectionError               no HTTP response at all
    └── TypeSafeAPITimeoutError              (+ .timeout)   also subclasses TimeoutError
```

Mapping (`STATUS_ERROR_TYPES` in `_core/errors.py`): 400, 401, 403, 404, 422, 429 are
mapped explicitly; **anything ≥500 → `TypeSafeInternalServerError`** (so `529 Overloaded`
arrives as `TypeSafeInternalServerError`, not a dedicated class); any other unmapped status
→ bare `TypeSafeAPIError`.

Practical notes:

- `TypeSafeAPIError.request_id` reads `x-typesafe-request-id`; `str(error)` includes
  `endpoint: status message (request_id=...)`. Log it for vendor support.
- Server messages are extracted from `error` / `error.message` / `message` / `detail`
  (string, object, or FastAPI-style list of `{loc, msg}` → `"questions.urgency.criteria: Field required"`).
  Bodies longer than 200 chars are elided with `…`.
- `TypeSafeAPITimeoutError` subclasses `TimeoutError`, and `TypeSafeAPIConnectionError`
  subclasses `ConnectionError` — a broad `except (ConnectionError, TimeoutError)` will
  catch them, which may be surprising.
- The SDK deliberately detaches the unredacted original exception
  (`sdk_error.__context__ = None`) so secret headers do not leak into tracebacks.

### 4.9 Minimal call, exactly as the SDK documents it

```python
from typesafe_sdk import Choice, Noul, Score, TypeSafeClient

with TypeSafeClient() as client:                      # reads TYPESAFE_API_KEY
    result = client.system_one(
        state={"message": "I was charged twice. Please help."},
        questions={
            "billing": Noul(instructions="Is this about billing?"),
            "tone": Choice(instructions="What is the tone?",
                           criteria={"calm": None, "angry": None}),
            "urgency": Score(instructions="How urgent is this?",
                             criteria=["Can wait", "This week", "Today"]),
        },
        model="jev-1.13.0",                            # pinned; not listed by /v1/models
    )

result.model                          # e.g. "jev-1.13.0" — the version that answered
result.nouls["billing"].noul          # float 0..1
result.choices["tone"].choice         # "calm" | "angry"
result.choices["tone"].confidence     # float 0..1
result.scores["urgency"].score        # float, may be between levels
result.scores["urgency"].probabilities[2]   # INT key, not "2"
result.usage.input_tokens             # int | None  <- may be None
result.request_id                     # raises TypeSafeError if the header was absent
```

---

## 5. Explicitly NOT VERIFIED

- Per-model price differences between `jev-latest`, `jev-preview` and `jev-1.13.0` — only
  one price row exists in the docs (for Jev 1.13); nothing states preview pricing.
- Any pricing/limits API endpoint — actively checked against the live
  `https://api.typesafe.ai/openapi.json` on 2026-09-27; only `/v1/systemone` and
  `/v1/models` exist. None found. (This is a verified *negative*.)
- Enterprise / custom plan prices, quotas and higher rate limits — gated behind
  sales@typesafe.ai.
- Maximum number of questions per request (only the 64k combined token budget is documented).
- Whether rate limits apply per API key, per account, or per organisation.
- Any official client-side tokenizer or token-counting utility.
- Whether a question with `instructions` omitted is actually accepted by the server (the
  HTTP API reference marks it required; the SDK and OpenAPI model allow `None`).
- Whether `release_date`'s ISO-timestamp format (observed) or `YYYY-MM-DD` (documented) is
  the intended contract.
- Contents of <https://docs.typesafe.ai/model-jaggedness/jev-1.13> (known accuracy caveats)
  — not read in this pass.
- Historical price changes; the vendor blog says it expects prices “to go down, not up”.

---

## 6. Summary table

| model | price in | price out | context limit | verified? | source URL |
| --- | --- | --- | --- | --- | --- |
| `jev-1.13.0` | **$0.042 / Mtok** ($42 / Btok), input tokens only | **FREE** | 64k tok/request (state + all questions); 32k tok (state + longest question) | **YES** — 2026-09-27 | <https://docs.typesafe.ai/models> |
| `jev-latest` (alias → `jev-1.13.0`) | same as `jev-1.13.0` (inherited via alias) | FREE | same as `jev-1.13.0` | Alias target **YES**; separate price row **NOT VERIFIED** (none published) | <https://docs.typesafe.ai/models#aliases> |
| `jev-preview` (alias → `jev-1.13.0`, "no preview build available right now") | same as `jev-1.13.0` (inherited via alias) | FREE | same as `jev-1.13.0` | Alias target **YES**; separate price row **NOT VERIFIED** (none published) | <https://docs.typesafe.ai/models#aliases> |

Rate limits (all three, same model behind them): **250,000 tokens/second and 1,200
requests/minute**, explicitly subject to change without notice — verified 2026-09-27 at
<https://docs.typesafe.ai/models>.

Corroborating pricing source: <https://typesafe.ai/blog/introducing-system-one-models-and-jev>
(checked 2026-09-27). `https://typesafe.ai/pricing` → 404 (checked 2026-09-27).

**Repo config verdict:** `model = "jev-1.13.0"` and `$0.042 / 1M input tokens, output free`
are both **correct and confirmed** as of 2026-09-27; the 64k / 32k context assumptions are
**correct** as of 2026-09-27. None of these are machine-readable from the API — re-check
<https://docs.typesafe.ai/models> manually whenever the pin moves.
