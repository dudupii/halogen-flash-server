# Sampling

**Greedy is the default and the guarantee: temperature absent or 0 is
byte-identical serial decode.** Above 0 the request samples, and speculation
stays on.

`temperature`, `top_p`, `top_k`, `min_p`, `seed`,
`presence_penalty`, `frequency_penalty`, `repetition_penalty`, `logit_bias`
and `logprobs` are supported. `temperature` absent or 0 is greedy decode. Above 0, the request
samples from the filtered distribution on the same drafter it would otherwise
get, so speculation stays on. A sampled request that omits `top_k` or `top_p`
gets the model's own values, 20 and 0.95 (since 0.14.2, #112). Before, an
omitted filter meant no filter. A `seed` reproduces a request served alone
on the same server configuration. Beside other requests, or when one run
reads its prompt from the prompt cache and the other does not, a seeded reply
can differ; each is still a sample from the same distribution. A sampled
request (temperature above 0) with `logprobs: true`
carries the chosen token's logprob on every token. For scoring, `logprobs` at
`temperature: 0` and `top_logprobs` (1 to 20, at any temperature) cover the
first generated token, so those requests set `max_tokens: 1`. `logprobs` with
`stream: true`, logprobs past the first token at temperature 0, and `n > 1`
are not implemented and are refused with a 400, as is any value outside its
defined range, rather than clamped. `/health` lists what the running build
supports. To read the probability of a few labels, see [Using it as a
classifier](classifier.md#using-it-as-a-classifier).

**`repetition_penalty`, since 0.15.1.** It follows vLLM's rule. Every token
that already appears in the prompt or in the reply so far has its logit
divided by the factor when the logit is positive, and multiplied by it
otherwise. This runs after `logit_bias` and before the presence and
frequency penalties, which count the reply only. `1` is off, and a value
above 1 discourages repeats. It applies to sampled requests. A greedy
request that sends a value other than 1 is a 400, because greedy decoding
here is byte-identical to serial decode and a penalty would change that
(vLLM applies it to greedy decoding too). `1` is accepted on a greedy
request, since the model card lists it. Before 0.15.1 the field was
accepted and ignored.

**The penalties count the reasoning too.** `presence_penalty` and
`frequency_penalty` count every token of the reply, the thinking block
included, as vLLM and the OpenAI API do (llama.cpp counts only the last 64
tokens, so the same values are much milder there). With
`frequency_penalty` 1.0 a long reasoning reply loses its punctuation within
about a thousand tokens and turns into word lists (issue #112). The model
card's thinking settings use no penalty.

**Server-side defaults, and the model card's settings.** This image decodes
greedy unless a request says otherwise, because greedy is what every
byte-identical guarantee below is made on. The model's authors recommend
sampling: the card's thinking-mode settings are `temperature=1.0`,
`top_p=0.95`, `top_k=20`, and every benchmark in it was run at that point.
Most agent clients send no sampling fields at all, so the server can supply
them:

```
-e HALOGEN_TEMPERATURE=1.0 -e HALOGEN_TOP_P=0.95 -e HALOGEN_TOP_K=20
```

`HALOGEN_TEMPERATURE`, `HALOGEN_TOP_P`, `HALOGEN_TOP_K`, `HALOGEN_MIN_P`,
`HALOGEN_PRESENCE_PENALTY`, `HALOGEN_FREQUENCY_PENALTY` and
`HALOGEN_REPETITION_PENALTY` each set the value a
request gets when it omits that field. Without them, a sampled request that
omits `top_k` or `top_p` gets the model's 20 and 0.95, and `HALOGEN_TOP_K=0` or
`HALOGEN_TOP_P=1` turns that filter off. The rule is one sentence: a field the
request sends always wins, a default fills only a field the request omits, and
a request that sends `temperature: 0` decodes greedy and takes none of the
sampling defaults. With a temperature default set, a request that sends no
temperature is sampled, so its output differs run to run unless it sends a
`seed`, and the byte-identical claims below apply only to requests that send
`temperature: 0`. That is why the image does not set these itself: it is your
call which default you want, and this is the switch. `/health` reports what is
set under `server_defaults`, and a value outside its range refuses to start,
before the model loads, naming the variable. (The card's non-thinking settings
are `temperature=0.7`, `top_p=0.80`, `top_k=20`, `presence_penalty=1.5`; they
apply when a request disables thinking, which these defaults cannot tell
apart, so send them from the client in that case.)
