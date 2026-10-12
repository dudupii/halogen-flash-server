# Token budgets, and why an empty answer means you ran out

**The token budget covers thinking, not just the answer.** This model reasons
before it replies and those tokens count against the budget. Before 0.11.0 a
budget that ran out mid-thought did not shorten the answer, it removed it:
the reply came back with `finish_reason: "length"`, an empty `content`, and
the partial reasoning in `reasoning_content`, which most OpenAI clients do
not display. Since 0.11.0 the server closes the think block with room left
for the answer (the *answer room*, below), so that shape needs a request
that asks for it (`HALOGEN_THINKING_ANSWER_ROOM=0`).

The default is **8192**, which finished every ordinary prompt we measured with
room to spare. Send more when you want more, up to `HALOGEN_MAX_TOKENS_CAP`
(**65536** by default); above the cap you get a 400 rather than a silent
truncation, so ask for what you need and the server will tell you if it is too
much. Hard reasoning problems can genuinely exceed 8192: pass a larger budget,
or `"reasoning_effort": "low"` to make the model think less. Accepted efforts
are `minimal`, `low`, `medium`, `high`, `xhigh` and `max`. The model's own
default is `xhigh`. The chat template itself knows three levels, so the
names fold onto them: `minimal` and `low` are `low`, `medium` is `medium`,
`high`, `xhigh` and `max` are `xhigh` (`max` since 0.15.1), and the startup line and `/health` report the level the
template will see (#71 asked why `high` printed as `xhigh`; #76 asked for
the middle one to be said). `medium` is the one step down from the default. `"reasoning_effort": "none"` turns thinking off for that request
(the same as `chat_template_kwargs: {"enable_thinking": false}`, and
`reasoning: {"effort": "none"}` on `/v1/responses`).

**A thinking budget, since 0.8.1.** `"max_thinking_tokens": N` on a request
(or `HALOGEN_MAX_THINKING_TOKENS` as the server default; the request wins)
bounds the think block: if the model has not closed it after N generated
tokens, the server closes it (Qwen's own budget sentence, then `</think>`)
and the answer follows in the same stream, on the same state, with no second
request. The `max_tokens` budget still covers both. This exists because
greedy decoding at 100k+ of context can loop inside the block and spend the
whole budget there (issue #56: 32,000 tokens of reasoning and an empty
answer); the model card's sampling settings above are the cure, and the
budget bounds the damage when a client sends none. Unset, nothing changes.

**The closing sentence can be set, since 0.15.1** (#114).
`HALOGEN_THINKING_BUDGET_MESSAGE`, like llama-server's
`--reasoning-budget-message`, replaces Qwen's sentence in the text the
server writes before `</think>` whenever it closes the block itself. That
happens at `max_thinking_tokens`, at the answer room below, and at the
end-of-turn guard. Set and empty, the block closes with `</think>` alone. Unset, it is
Qwen's sentence, as before. The forced tokens count against `max_tokens`.
The server refuses to start on a message that holds a chat marker such as
`</think>` or `<|im_end|>` (the model would read it as a control token),
or on one longer than 512 tokens.

**The answer room, since 0.11.0.** Thinking no longer consumes the whole
budget. When a request sends no thinking budget of its own, the server closes
the think block once `max(1024, 15% of max_tokens)` tokens of the budget
remain (the same close as `max_thinking_tokens`), so a capped request ends
with an answer rather than `finish_reason: "length"` and an empty `content`.
This matters because agent harnesses send no thinking control at all to an
OpenAI-compatible server unless configured to, so the model's own `xhigh`
runs under whatever cap the harness set for the *answer*: a compaction
summary capped at 13,000 tokens that the model thinks past is a compaction
that fails, and the harness retries it. A request's own budget still wins
when it is smaller. `HALOGEN_THINKING_ANSWER_ROOM` sets the room in tokens;
`0` restores the 0.10.x behaviour; `/health` reports it as
`thinking_answer_room`. Only a request whose thinking would have run past
the line is affected; every other reply is untouched.

**When the server closed the block, it says so, since 0.12.2.** A reply whose
think block the server closed (the answer room, or your own
`max_thinking_tokens`) carries `reasoning_closed_at` (the token the block
was closed at) and `reasoning_closed_by` (`"answer_room"` or
`"max_thinking_tokens"`) in `usage.completion_tokens_details`, beside
`reasoning_tokens`; on `/v1/responses` the same two ride
`output_tokens_details`. A reply whose block the model closed itself has
neither. The server's per-request log line says the same (`think on, closed
at 1024 by answer room`) and, on every chat request, whether the prompt
opened a think block at all (`think on` / `think off`). Under a 2,048
budget the room is 1,024 tokens, so a reply that reads as "about a thousand
hidden tokens, then a short answer" is this close, and the fields now name
it.

**The chat template is checked before the server starts, since 0.12.2.**
Every thinking control above works by asking the chat template to render
the block one way or the other, and the server renders whatever template
the tokenizer directory carries. A tokenizer mounted from another
repository can carry a template without that branch, and on 0.12.1 and
earlier it silently accepted `enable_thinking: false`, `reasoning_effort:
"none"` and `HALOGEN_ENABLE_THINKING=0` and rendered thinking anyway. The
server now renders a one-message conversation with thinking off and on at
startup and refuses to start if the two do not differ the way the controls
assume, naming the file in one sentence; `HALOGEN_TEMPLATE_UNCHECKED=1`
serves it anyway, with the same sentence as a warning. The startup line
and `/health.chat_template` say which template loaded (the path and the
sha256 of its text) and whether the check passed, so a report about
thinking can start from that line. The weights repo's own `tokenizer/`
passes, and the entrypoint's fallback to it needs no mount at all.

**Your harness's own name for the thinking controls works, since 0.11.0.**
Besides `reasoning_effort`, `enable_thinking`, `chat_template_kwargs` and
`max_thinking_tokens`, the chat route reads `thinking_budget_tokens`,
`thinking_budget` and `thinking_token_budget` (the three names Pi's
`compat.thinkingTokenBudgetField` can send), the `reasoning` object
(`{"enabled": false}`, `{"effort": "low"}`, `{"max_tokens": 4096}`: the
OpenRouter shape, which hermes-agent and aider send) and the `thinking`
object (`{"type": "disabled"}`, `{"type": "enabled", "budget_tokens": 4096}`:
the Anthropic shape, which aider's `--thinking-tokens` sends to every
non-OpenRouter model). Two names with two different values is a 400, as
with the token budget. `/health` lists them under `supported`.

**Any of three field names works**, and they mean the same thing here:
`max_completion_tokens` (current OpenAI Chat Completions), `max_output_tokens`
(OpenAI Responses), or `max_tokens` (deprecated upstream, still widely sent).
Send one, or send several as long as they agree; two different values is a 400
rather than a guess about which you meant. `/health` lists all three under
`token_budget_aliases` and reports the current default as `max_tokens_default`.
`HALOGEN_MAX_TOKENS_DEFAULT` moves that default for every route. The card's
advice is not to cap the budget at all; here a request reserves its prompt
plus its budget in the KV pool when it is admitted, so a large default costs
concurrency (four slots at 65,536 is a whole 262,144-position pool before a
single prompt token). `-e HALOGEN_MAX_TOKENS_DEFAULT=16384` is the step that
clears an ordinary agentic turn's reasoning without that cost.
`HALOGEN_REASONING_EFFORT` moves the effort a request gets when it names none,
and the card's own guidance is to leave it at `xhigh`: lower effort on
multi-turn agentic tasks "can lead to insufficient analysis, more failures, and
repeated retries." A request that sends either field still wins.

```json
{
  "model": "halogen-qwen3.8-flash-next",
  "messages": [{"role": "user", "content": "..."}],
  "max_completion_tokens": 16384,
  "reasoning_effort": "low"
}
```

If a reply looks empty or cut off, read `finish_reason` first: `"stop"` means
you have the whole answer, `"length"` means you ran out of budget.

**A quoted end-of-turn marker no longer ends the reply, since 0.13.4.** The
tokenizer has one token for `<|im_end|>`, so a model that writes or reads a
ChatML chat template in its reasoning writes the real end-of-turn token, and
through 0.13.3 the reply ended right there: `finish_reason: "stop"`, no
content and no tool call, on 15-25% of one agent's turns (#84). Inside the
thinking block that token is now kept as text and generation goes on;
inside an open tool call it is kept up to four times a reply (a template
written through a file-writing tool). Since 0.14.2 at most 16 are kept in the
thinking block (#112). The 17th closes the block with the thinking budget's
closing text and the model answers, so a sampled reply caught in a loop of
markers does not spend its budget there. `reasoning_closed_by` then reads
`end_of_turn_guard`. The other half of the same report is
a model that writes a complete tool call inside its thinking block and then
ends its turn on it: that call is now made, with `finish_reason:
"tool_calls"`, and its text also stays in `reasoning_content`, where it was
streamed. A kept `<|im_end|>` and a quoted `<|im_start|>` appear in the text
literally (they used to vanish, so a quoted template came back with empty
spans). `usage.completion_tokens_details` carries `end_of_turn_kept` and
`tool_call_from_reasoning` when either happened, the request line in the log
says `end of turn kept as text`, and `HALOGEN_EOS_GUARD=0` restores 0.13.3's
behaviour. An end-of-turn token in the answer itself still ends the reply.

**A document that quotes the chat markers.** A prompt is tokenized whole,
so `<|im_end|>` or `</think>` written in a message reaches the model as the
real control token, as it does on vLLM. A model translating or summarizing
such a document can copy the token and end its reply there (issue #115).
Break each marker in the source text, for example `<| im_end |>`. Since
0.15.1 a request with thinking off counts no reasoning tokens even when its
reply writes `</think>`.
