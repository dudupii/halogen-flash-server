# Codex and the Responses API

The server also speaks the **OpenAI Responses API** at `POST /v1/responses`, so
clients that dropped Chat Completions can use it directly. The OpenAI Codex CLI
is the reason it exists: point it at this server and it works, including tool
calls.

```toml
# ~/.codex/config.toml
model = "halogen-qwen3.8-flash-next"
model_provider = "halogen"

[model_providers.halogen]
name = "halogen"
base_url = "http://<your-server>:8731/v1"
wire_api = "responses"
requires_openai_auth = false
```

Streaming and non-streaming both work, `function_call` and
`function_call_output` round trip, and `tools` entries that are not functions
(`web_search`, and the `namespace` wrapper, whose nested functions are used)
are ignored rather than rejected. `instructions` and any `developer` turns are
folded into the system prompt. A `function_call_output` whose output is a
content array with an `input_image` passes the image to the model (since
0.14.2, #113). That needs the vision tower. Without it the request is refused
with a 400.

**Reasoning is returned** (since 0.7.0; #44). The model's thinking goes out
as a `reasoning` output item ahead of the message, its text as a
`reasoning_text` content part streamed in `response.reasoning_text.delta`
events, and `usage.output_tokens_details.reasoning_tokens` says how much of
the output it was (both routes carry that count). When the request asks for
a reasoning summary, as Codex does (`reasoning: {"summary": "auto"}`), the
same text is sent again as the item's `summary_text`, with the
`response.reasoning_summary_*` events: there is no separate summarizer, the
summary is the reasoning. Codex renders summaries by default and shows raw
reasoning content only with `show_raw_agent_reasoning = true` in its config,
so with that setting on you will see the text twice. No `encrypted_content`
is sent, and a `reasoning` item echoed back in a later turn is dropped, as
before. **There is no response store**, so `previous_response_id`, retrieving
a response by id, and cancelling one are not available; send the history with
each request, which is what Codex does. Since 0.18.1 a request that sends
`previous_response_id` and no earlier turn is refused with a 400, so a client
that expects a store finds out at once instead of getting an answer without
its context.

**Statistics for llama-swap** (since 0.7.0; #45): every response, on both
routes, carries a `timings` object in llama-server's shape (`prompt_n`,
`predicted_n`, `prompt_ms`, `predicted_ms`, `prompt_per_second`,
`predicted_per_second`, `cache_n`, `draft_n`, `draft_n_accepted`), on the
non-streamed body and on a stream's last frames, so llama-swap's activity
page shows prefill and decode rates and the draft count. `draft_n` counts the
draft head's proposals and the prompt-lookup chains' together; the numbers
are the engine's own per-request line, copied.

**Prometheus** (since 0.8.0): `GET /metrics` answers in llama-server's
metric names, so a dashboard built for llama.cpp (or for llama-swap's
upstream) reads this server unchanged: `llamacpp:prompt_tokens_total`,
`llamacpp:tokens_predicted_total` and their `_seconds_total` counters (the
engine's own per-request numbers, summed; `prompt_n` is the processed count),
the `prompt_tokens_seconds` / `predicted_tokens_seconds` gauges over the
requests since the last scrape, `requests_processing`, `requests_deferred`,
`kv_cache_tokens` and `kv_cache_usage_ratio` (since 0.11.5 the engine's own
occupancy: the positions its pool holds in every region, busy and held,
over the pool, as of the last completed request; before 0.11.5 they counted
what the requests holding a front-end slot had asked for, admitted or not,
which read 913k against a 655k pool in issue #74). Beside them,
`halogen:requests_total`, `halogen:prompt_tokens_cached_total`,
`halogen:draft_tokens_total`, `halogen:draft_tokens_accepted_total`,
`halogen:structured_requests_total`, and since 0.11.5 `halogen:kv_pool_positions`
and `halogen:kv_pool_reserved_tokens` (the front end's reservation, the old
meaning). Since 0.17.5 (#156) it also carries the prompt cache's main
numbers: `halogen:cache_hits_total`, `halogen:cache_misses_total`,
`halogen:cache_prompt_tokens_saved_total`, `halogen:cache_entries`,
`halogen:cache_bytes`, `halogen:cache_evicted_total`, the disk tier's
`halogen:cache_disk_enabled`, `halogen:cache_disk_bytes`,
`halogen:cache_disk_budget_bytes` and `halogen:cache_disk_hits_total`, and
`halogen:kv_pool_waiting_for_room`. Beside them `halogen:engine_up` (the
probe `/health` reports), `halogen:busy_for_seconds` (how long the oldest
request has run) and `halogen:build_info`. A scrape never stalls on a busy
engine: the cache numbers are the engine's last report, refreshed in the
background, and `halogen:cache_stats_age_seconds` says how old it is.
`GET /cache` keeps the full report. Always on, no flag.
Since 0.18.0 (#158), `halogen:cache_last_message_rewrites_total` counts requests
that resumed inside the previous request's last message (a client that changes
or drops part of it each turn) and continued in that conversation's cache, and
`halogen:cache_disk_cut_back_total` counts the times the disk tier trimmed a
conversation's files back to where its next request resumed instead of writing
a second copy.

**Cache and pool occupancy in the log** (since 0.11.5; #73): every
request's `serve_api:` line carries the cached share of its prompt, the
prefill rate over the tokens actually processed, and the pool's occupancy
as the engine reports it: `prompt 30828 (30803 cached, 99.9%), prefill 0.38s
(25 new) | ... | pool 30976/524288 6%`. Since 0.11.9 the rate is printed
only when at least 2,048 tokens were processed (the cold turn before that
one read `prompt 30803, prefill 27.92s = 1103 t/s`); below that the line
says how many were new and leaves the rate out, because a few hundred
tokens in a second is one prefill chunk's fixed cost and not a speed, and
two reports had read it as one. `timings` in the response is unchanged. `GET /cache` adds `token_hit_rate` (prompt tokens the
cache covered over every prompt token seen since the server started;
`hit_rate` counts requests) and, under `pool`, `positions`, `used`,
`usage_ratio`, `busy_regions` (a request decoding), `held_regions` (a warm
conversation between turns, not a full pool), `room_clamped` and `moved`.
Since 0.11.9 `dropped` counts the entries a follow-up dropped to take its
region over (they went under `evicted` in 0.11.8), and a `/cache` polled
while the engine is inside a long cold prefill answers the last counters it
had with `stale_s` set, where it used to answer 500 after ten seconds.

**Structured output** (since 0.8.0; #14, #43). `response_format:
{"type": "json_schema", "json_schema": {"name": ..., "schema": {...}}}` and
`{"type": "json_object"}` on `/v1/chat/completions` and `/v1/completions`,
`text: {"format": {"type": "json_schema", "name": ..., "schema": {...}}}`
and `{"type": "json_object"}` on `/v1/responses` (the shape Codex sends; its
approvals reviewer sends one on every auto-reviewed tool call, which is what
#43 hit). The engine enforces the schema while it decodes: every token is
chosen from the tokens the schema allows next, so the reply parses and
validates by construction, with no retry and no repair. It is decoding
under a mask, greedy or sampled, and nothing else changes: the same request
without the schema is bitwise what it was, and a greedy constrained request
is identical whether it decoded serially, with the draft head, with prompt lookup, or
beside other requests. It costs nothing measurable: the schema is compiled
once (a millisecond) and every state's mask lives on the GPU, so the decode
loop reads a pointer.

What is enforced: `type` (object, array, string, number, integer, boolean,
null, and `["string", "null"]`), `properties` with keys emitted in schema
order, `required` (an optional key may be skipped), `additionalProperties`
(`false`, `true`, or a schema: extra keys only after the listed ones),
`items`, `minItems`, `maxItems`, `minLength`, `maxLength`, `enum`, `const`,
`anyOf` (`oneOf` is treated as `anyOf`), `$ref` and `$defs` including
recursive ones. Accepted and not enforced: `minimum`, `maximum`,
`exclusiveMinimum`, `exclusiveMaximum`, `multipleOf`, and the annotation
keywords. Refused with a 400 naming the keyword: `pattern`, `format`,
`allOf`, `not`, `if`/`then`/`else`, `patternProperties`, `dependentRequired`,
`dependentSchemas`, `uniqueItems`, `contains`, `propertyNames`,
`unevaluated*`, `minProperties`, `maxProperties`, `prefixItems`. `/health`
lists all three under `structured_output`.

The reasoning block is not constrained: with thinking on the model thinks
freely and the JSON starts after `</think>`. A request with tools may open a
tool call instead of the JSON (the schema binds the final text, not a call),
which is how the Codex reviewer's own read-only tool checks keep working.
Since 0.16.3 such a reply starts unconstrained, so the model chooses between
a call and the answer as it would with no schema. The schema holds from the
JSON's first `{`, the text written before it is dropped, and a reply that
would end first starts the JSON instead. That text may run to half of what
`max_tokens` leaves after thinking, at most 1024 tokens; past that the JSON
starts and a tool call is no longer offered. A sampled request that would
answer in plain text usually runs that text to the limit before the JSON
starts, so with tools and a temperature above 0 expect a slower reply where
the greedy one would answer at once. This applies to schemas whose root
is an object. `HALOGEN_SCHEMA_ESCAPE=off` binds the schema from the first
token again. Whitespace between tokens is allowed, so a pretty-printed reply is fine, but
at most two whitespace-only tokens in a row (a forbidden preference
otherwise falls to a newline, and then another). Only the end-of-turn token
is legal once the value is complete, so the reply is exactly the JSON.
Since 0.18.1 a request with a schema may sample (temperature above 0):
every token is drawn from the tokens the schema allows, and a `seed` repeats
the reply on the terms of *Sampling* above (alone, and both runs cold or both
read from the prompt cache). A schema with an image, or with `logprobs`, is a
400. `HALOGEN_GRAMMAR=0` turns the feature off (the 400 of 0.7.0 comes
back).

Verified against the Codex CLI driving real tasks end to end, and separately
against the official `openai` Python SDK, which parses every event into its own
typed models.

**Prompt progress** (since 0.17.5). `"return_progress": true` on a streamed
`/v1/chat/completions` or `/v1/completions` request adds chunks with an
empty `choices` list and a `prompt_progress` object while the prompt is
read, before the first token, in the shape llama.cpp's server sends:

- `total`: the prompt's tokens;
- `cache`: how many of them came from the prompt cache;
- `processed`: how many are read so far, the cached ones included;
- `time_ms`: milliseconds since prompt processing started.

The first chunk opens at the cached count and the last has `processed`
equal to `total`. A bar of the work left is `(processed - cache) /
(total - cache)`. Without `stream` the field is ignored; the Messages and
Responses routes have no such field. It never changes the reply.
