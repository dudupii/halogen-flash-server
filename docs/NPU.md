# Small models on the NPU

The server can run small models on the Ryzen AI NPU beside the Flash model, behind the same port. Name them in
`HALOGEN_NPU_MODELS`, and a request picks one by its `model`. Every other request goes to the Flash model, as before.
Eight kinds of model run there:

- **Decisions** with `decider-0.8b` (a Qwen3.5-0.8B classifier). Give a text and a question with 2 to 10 options, and
  get a probability for every option from one pass.
- **Embeddings** with `qwen3-embedding-0.6b`, or with `embeddinggemma-2` (EmbeddingGemma 2) for text, pictures and
  sound in one space.
- **Reranking** with `qwen3-reranker-0.6b`. Score documents against a query.
- **Moderation** with `qwen3guard-gen-0.6b` (Qwen3Guard-Gen-0.6B). Is a prompt, or a reply in its conversation, safe?
- **A streaming guard** with `qwen3guard-stream-0.6b` (Qwen3Guard-Stream-0.6B). It labels a reply from the Flash model
  as it is written.
- **Text generation** with `qwen3.5-2b` (Qwen3.5-2B, thinking off). Summaries and other short jobs, beside the Flash
  model.
- **Images** with `flux2-klein-4b` (FLUX.2-klein-4B). Icons, diagrams, illustrations and placeholders from 256x256 up
  to 1024x1024, square or not, on `/v1/images/generations`, and edits of a picture you send on `/v1/images/edits`.
- **Speech to text** with `qwen3-asr-0.6b` or `qwen3-asr-1.7b` (Qwen3-ASR). Recordings up to 20 minutes, on
  `/v1/audio/transcriptions`.

Larger sizes of the first three are named the same way (see [Larger sizes](#larger-sizes)). Your own fine-tune of any of the first four runs too. See [Your own model](#your-own-model).

## What the host needs

- The NPU driver, XRT with its NPU plugin, the NPU firmware, and the IOMMU on. See [the host](#host).
- **The GPU's fabric clock held at its top speed.** On Strix Halo, GPU work and NPU work at the same time can hang the
  machine and corrupt the NPU's results while that clock changes speed. Held, they run together cleanly. It is a
  setting of the host's GPU driver that only the host's root may change, so how it gets held depends on how you run
  the container:

  - **As root** (`docker run`, or `sudo podman run`): add `-v /sys:/host/sys`. The server then holds the clock itself
    while it runs and gives it back when it stops. Nothing to install.
  - **Rootless podman** (the Quickstart's form): the container cannot change it. Install the unit in
    [`deploy/host/`](https://github.com/peonist-ai/halogen-flash-server/tree/main/deploy/host) once, and it holds the clock at every boot:

    ```
    sudo install -m 755 deploy/host/halogen-fabric-clock /usr/local/sbin/
    sudo install -m 644 deploy/host/halogen-fabric-clock.service /etc/systemd/system/
    sudo systemctl daemon-reload && sudo systemctl enable --now halogen-fabric-clock.service
    halogen-fabric-clock status
    ```

  It costs about a watt while held. If the clock is not held and the server cannot hold it, it refuses to start and
  prints the commands for your machine. This applies to any NPU program beside a GPU program, not only to this server.

Check the NPU with `ls -l /dev/accel/accel0`.

## Start it

The Quickstart's command, with the NPU added (the device, the host's XRT, and the models):

```bash
podman run --rm -p 8731:8731 \
  --device /dev/kfd --device /dev/dri --device /dev/accel/accel0 --group-add keep-groups \
  --ipc=host --ulimit memlock=-1:-1 \
  -v /opt/xilinx/xrt:/opt/xilinx/xrt:ro \
  -e HALOGEN_DOWNLOAD=peonist-ai/halogen-qwen3.8-flash-next \
  -e HALOGEN_NPU_MODELS=decider-0.8b,qwen3-embedding-0.6b,qwen3-reranker-0.6b,qwen3guard-gen-0.6b,qwen3.5-2b \
  -v ~/halogen-models:/models \
  ghcr.io/peonist-ai/halogen-flash-server:0.18.5
```

`HALOGEN_DOWNLOAD` fetches the files of the NPU models that `HALOGEN_NPU_MODELS` names, into `/models/npu`, and the
server checks each one's size and checksum. A model you leave out of the list is not fetched. The five names above are
the folder names, and the guard and the reranker share the embedder's device files. If your XRT came from your distribution, mount it as [the host section](#host) shows. Leave
`HALOGEN_NPU_MODELS` out and the server is exactly what it was without it.

With compose, use `docker-compose.npu.yml`, which runs this same single container. The two-container `docker-compose.yml`
starts no NPU engine.

The NPU models' files stay in memory beside the Flash model's, a few GB in all, about 8 GB more with
`flux2-klein-4b`, about 1.6 GB more with `qwen3-asr-0.6b`, about 4 GB with `qwen3-asr-1.7b`, about 1.1 GB with
`embeddinggemma-2` and about 0.8 GB with `qwen3guard-stream-0.6b`. The Flash model runs somewhat slower
while the NPU works, since the two share the memory bus and the chip's power budget.

## Larger sizes

Three more models run on the NPU. They are not in the default list: name them in `HALOGEN_NPU_MODELS`, and they are
fetched and served like the others.

- `decider-4b` (a Qwen3.5-4B classifier) answers decisions as `decider-0.8b` does, with a better answer on harder questions.
  It takes a little longer to decide.
- `qwen3-embedding-4b` (Qwen3-Embedding-4B) for embeddings, and `qwen3-reranker-4b` (Qwen3-Reranker-4B) for reranking.
  The reranker shares the embedder's device files.

Each holds about 5 GB in memory beside the Flash model. A fine-tune of either Qwen3 model, from a path under
`/models`, loads the same way as at the smaller size.

## Decisions

Send the text to judge as the messages. Put the question in `response_format.json_schema.description` and the options
in its `schema`. Ask for `logprobs` to get every option's probability.

```python
from openai import OpenAI

client = OpenAI(base_url="http://localhost:8731/v1", api_key="none")
r = client.chat.completions.create(
    model="decider-0.8b",
    messages=[{"role": "user", "content": "WIN a FREE iPhone now!!! Click http://bit.ly/x to claim your prize before midnight."}],
    response_format={"type": "json_schema", "json_schema": {
        "name": "spam",
        "description": "Is this email spam?",
        "schema": {"enum": ["no", "yes"]}}},
    logprobs=True, top_logprobs=2)
print(r.choices[0].message.content)                   # the most likely option, as JSON in the schema's shape
for t in r.choices[0].logprobs.content[0].top_logprobs:
    print(t.token, t.logprob)                           # each option's log probability
```

The options can be an `enum`, a `oneOf` of `{"const": ..., "description": ...}` items, `{"type": "boolean"}`, or an
object with one property holding one of those. The answer is the most likely option, in the schema's shape. A decision
is not sampled: `temperature`, `top_p`, `seed` and the penalties are accepted and ignored. A conversation works too:
every message becomes part of the text to judge, and a system message can carry the question instead of the schema.

## System One questions

`POST /v1/systemone` takes TypeSafe's System One request, so a client written for it can point at `decider-0.8b`.
Send a `state` (a string, or an object or array that is sent as JSON) and `questions`, each with a `type`,
`instructions` and `criteria`. There is no API key. `model` can be `decider-0.8b` or any other name, and it runs the
decision model loaded.

```bash
curl -s localhost:8731/v1/systemone -H 'content-type: application/json' -d '{
  "model": "decider-0.8b",
  "state": "Customer: I was charged twice and nobody answers my emails.",
  "questions": {
    "team": {"type": "choice", "instructions": "Which team should handle this",
             "criteria": {"billing": "Payment issues", "technical": "Bugs", "other": null}},
    "anger": {"type": "score", "instructions": "How frustrated does the customer appear",
              "criteria": ["Calm and neutral", "Concerned but civil", "Very angry"]},
    "refund": {"type": "noul", "instructions": "Does the customer request a refund?"}}}'
```

Each question is one pass. A `choice` answers with `choice`, `probabilities` and `confidence`; a `score` with its
expected level (`score`), `legend`, `probabilities` keyed by level number from 0, and `confidence`; a `noul` with the
probability of yes. A choice or score takes 2 to 10 options here, where System One takes up to 255. A bad request
answers 422.

Several questions about one long text: start the server with `HALOGEN_NPU_DEC_RESUME=1`. A request with several
questions then reads the text once. With `HALOGEN_NPU_DEC_RESUME=2`, a later request whose text only adds to an earlier
one also reuses that work (a text that arrives with one question is kept from its second time on). The answers are the
same as without it. It is off by default. It keeps up to `HALOGEN_NPU_DEC_ENTRIES` texts (6), and each kept text holds
memory on the host until it is replaced.

## Embeddings

```python
r = client.embeddings.create(model="qwen3-embedding-0.6b",
                             input=["Instruct: Given a question, retrieve passages that answer it\nQuery:What is the NPU?",
                                    "The NPU is the neural processing unit on Ryzen AI chips."])
vectors = [d.embedding for d in r.data]                 # 1024 floats each, unit length
```

A query carries the task instruction in the model's own form, `Instruct: <task>\nQuery:<query>`. A document carries
none. `dimensions` (32 to 1024) keeps the first dimensions and normalizes them again. `encoding_format` can be `float`
or `base64`. Send text, not token ids. With LangChain's `OpenAIEmbeddings`, set `check_embedding_ctx_length=False`.

## Text, pictures and sound in one space

Name `embeddinggemma-2` (EmbeddingGemma 2) in `HALOGEN_NPU_MODELS` and it is fetched and served on `/v1/embeddings`.
It puts texts, pictures and audio clips in one 768-dimension space, so a text query can find a photo or a voice memo.

```python
r = client.embeddings.create(
    model="embeddinggemma-2",
    input=["a dog catching a frisbee on the beach",
           {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,..."}},
           {"type": "input_audio", "input_audio": {"data": "<base64 of a WAV file>", "format": "wav"}}],
    extra_body={"prompt_name": "query"})
vectors = [d.embedding for d in r.data]                 # 768 floats each, unit length
```

- `prompt_name`: `query` for what you search with, `document` for what is searched. The server writes the model's own
  prompt in front of each text. Without it, each text is embedded as sent, so you can write the prompt yourself. It
  applies to texts only.
- A text is up to 8,192 tokens, the prompt included. A longer one is refused with a 400.
- A picture is an `image_url` item with the image inline, as a base64 `data:` URL or bare base64. The server fetches no
  URLs. PNG, JPEG, WebP, GIF and BMP are taken, up to 32 MiB of base64. Every picture is resized the way the model's
  own processor does it: its shape kept, to about 800x800 pixels' worth (at most 2,520 squares of 16x16 pixels, each
  side a multiple of 48), larger pictures scaled down and smaller ones up.
- An audio clip is an `input_audio` item holding a WAV file in base64: PCM (8 to 32-bit) or float, any sample rate,
  mono or more channels. A clip is up to 30 seconds. A longer one is refused with a 400.
- One request can mix texts, pictures and clips, up to 64 pictures and clips. Each picture and each clip takes a pass
  of its own on the NPU.
- `dimensions` (32 to 768) keeps the first dimensions and normalizes them again. The model was trained for 768, 512,
  256 and 128. `encoding_format` can be `float` or `base64`.

## Reranking

```
curl -s localhost:8731/v1/rerank -H 'Content-Type: application/json' -d '{
  "model": "qwen3-reranker-0.6b",
  "query": "How do I check that the NPU driver is loaded?",
  "documents": ["To see whether the NPU driver is loaded, list the device nodes with ls /dev/accel. If accel0 appears, the driver is loaded.",
                "The GPU has 40 compute units and shares memory with the CPU."],
  "top_n": 1, "return_documents": true}'
```

The request and the answer follow the Cohere and Jina shape: `results` sorted by `relevance_score`, each with its
`index` in your list. Documents can be strings or objects with a `text` field. An optional `instruction` replaces the
model's default task line.

## Moderation

Name `qwen3guard-gen-0.6b` in `HALOGEN_NPU_MODELS` (the Start command above does) and it is fetched and served.

```
curl -s localhost:8731/v1/moderations -H 'Content-Type: application/json' -d '{
  "model": "qwen3guard-gen-0.6b",
  "input": ["How do I bake bread?", "How do I make a weapon at home?"]}'
```

The answer follows OpenAI's `/v1/moderations`, so its client libraries work as they are: one result per input, each
with `flagged`. Each result also carries `label` (`Safe`, `Unsafe` or `Controversial`) and `label_scores`, the three
labels' probabilities. `flagged` is true for `Unsafe`. Send `"strict": true` to flag `Controversial` too. The model
does not sort content into OpenAI's categories, so every category reads `false` and every score `0`.

`input` is a string, a list of strings (one result each), or a list of text parts. To check a reply in its
conversation, send `messages` instead of `input`, in the chat shape. When the last message is the assistant's, its
reply is judged. Otherwise the last user message is. A request that names OpenAI's own model, or no model, goes to the
moderation model loaded here.

## Streaming guard

`qwen3guard-stream-0.6b` labels a reply from the Flash model while it is being written, a stretch at a time, and the
user's message before it: Safe, Unsafe or Controversial, with a probability and a category. Name it in
`HALOGEN_NPU_MODELS` (it runs on the embedder's device files, which are fetched with it). Then turn it on for a
request on `/v1/chat/completions`:

```
curl -sN localhost:8731/v1/chat/completions -H 'Content-Type: application/json' -d '{
  "messages": [{"role": "user", "content": "How do I pick a lock?"}],
  "stream": true, "guard": true}'
```

- `"guard": true`, the model's name, or an object such as `{"model": "qwen3guard-stream-0.6b", "chunk": 16, "flag": 0.8}`
  turns it on. The header `X-Halogen-Guard: watch` does the same for a client that cannot add a field. A request with
  neither is served exactly as before.
- It watches. It never stops, holds or changes the reply: the reply's own chunks are the same as without it.
- Streamed, its verdicts are extra chunks with no `choices` and a `halogen_guard` object. `event` is `user` (the user's
  last message: `risk`, `prob`, `category`), `chunk` (a stretch of the reply: its `tokens`, `risk`, `prob`, `unsafe`,
  `category` and `flagged`, sent when the label is not Safe or changes), or `end`, a summary just before `[DONE]`
  (`peak_unsafe`, `flagged_chunks`, `first_flag_token`). Not streamed, the response carries `halogen_guard` with the
  `events` and the `summary`, made once the reply is finished.
- `chunk` is how many tokens of the reply each verdict covers, 4 to 128 (16 by default). `flag` is the Unsafe
  probability at which a stretch is marked `flagged` (`HALOGEN_GUARD_FLAG`, 0.8 by default).
- The categories for a reply are Violent, Sexual Content, Self-Harm, Political, PII, Copyright, Illegal Acts and
  Unethical. The user's message can also be Jailbreak.
- It reads the reply's text, not its reasoning or tool calls, and the user's last message (up to 1,024 tokens: its
  start and end when it is longer). It watches the first 2,048 tokens of the two together, then says it has stopped.
- Up to `HALOGEN_GUARD_STREAMS` replies (4) are watched at once. One more is served without the guard, and its stream
  says so. Text the guard has not reached yet waits, up to `HALOGEN_GUARD_LAG` characters (4,096). Past that the
  oldest is skipped and a `skipped` event says how much. The end of a streamed reply waits up to
  `HALOGEN_GUARD_FINAL_S` seconds (3) for the last verdicts.
- `/v1/chat/completions` only for now, not `/v1/responses` or `/v1/messages`. A `guard` field this server cannot honour
  (another mode, a model that is not loaded or is not a streaming guard, a `chunk` out of range) is refused with a 400
  before the reply starts.
- It is not a moderation model: `/v1/moderations` and `/classify` refuse it with a 400. Use `qwen3guard-gen-0.6b` to
  judge a finished prompt or reply.

## Classification

A fine-tune saved as a sequence classifier (`Qwen3ForSequenceClassification`) of Qwen3-0.6B or Qwen3-Embedding-0.6B loads by path, as under "Your own model" below, and answers `POST /classify` in vLLM's shape. Name it in `HALOGEN_NPU_MODELS` and use the directory's name as the model.

```
curl -s localhost:8731/classify -H 'Content-Type: application/json' -d '{
  "model": "my-classifier",
  "input": ["Win a free prize now", "Lunch at noon?"]}'
```

Each input gets an entry in `data` with its `index`, the most likely `label` (from the checkpoint's `id2label`), `probs` (one probability per label) and `num_classes`, and `usage` counts the prompt tokens. `input` is a string, a list of strings, token ids, or a list of token-id lists. Send `"use_activation": false` to get the raw scores in `probs`. `truncate_prompt_tokens` and `add_special_tokens` work as in vLLM. Chat `messages` are not taken.

## Generation

Name `qwen3.5-2b` in `HALOGEN_NPU_MODELS` (the Start command above does) and it is fetched and served.

```
curl -s localhost:8731/v1/chat/completions -H 'Content-Type: application/json' -d '{
  "model": "qwen3.5-2b",
  "messages": [{"role": "user", "content": "Summarize this in three sentences: ..."}]}'
```

A chat request that names `qwen3.5-2b` runs on the NPU. Every other chat request goes to the Flash model. The answer
follows OpenAI's chat completions, streamed or not, with `stop` strings and usage. The model reads text only, calls no
tools, and answers without thinking. A request that sets no sampling fields gets the model card's (temperature 1.0,
`top_k` 20, `presence_penalty` 2.0), and any of them can be set per request. `max_tokens` defaults to 2,048.

## Images

Name `flux2-klein-4b` in `HALOGEN_NPU_MODELS` and it is fetched and served. It draws an image from a prompt, on
`/v1/images/generations` in OpenAI's shape:

```
curl -s localhost:8731/v1/images/generations -H 'Content-Type: application/json' \
  -d '{"model": "flux2-klein-4b", "prompt": "a flat vector icon of a cloud with a lightning bolt",
       "size": "512x512", "n": 1, "seed": 7}'
```

- `size`: `WxH`, one of `256x256`, `512x512`, `768x768`, `1024x1024`, `768x512`, `512x768`, `1024x768`, `768x1024`,
  `1024x576`, `576x1024`, `640x512`, `512x640`, `896x512`, `512x896`, `1024x448`, `448x1024`, `1024x512`, `512x1024`,
  `1024x640`, `640x1024`. `auto` is `512x512`. Any other size is refused with the list.
- `steps` (or `num_inference_steps`): FLUX.2-klein draws in four steps. Any other value is refused.
- `n`: one to four images. They are drawn one after another.
- `response_format`: `b64_json` (the default) or `url`, a `data:` URL of the PNG.
- `output_format`: `png` only.
- `seed`: an extension. Image `i` of a request draws at `seed + i`, so the same request gives the same images. Without
  it each request draws its own.
- `quality`: `low` is refused for now. Every other value draws the same image.
- The prompt is written into the model's chat template and cut to 512 tokens.

The model holds about 8 GB of the host's memory while it is loaded. One image request runs at a time on the NPU,
queued with the other NPU models' work.

A 512x512 image takes about 3 seconds and a 1024x1024 image about 10. A 1024x1024 image uses about 0.7 GB of working
memory while it draws.

## Image edits

With `flux2-klein-4b` loaded, `/v1/images/edits` changes a picture you send as you describe, and `/v1/images/variations`
draws a new take on one. Both use OpenAI's multipart shape:

```
curl -s localhost:8731/v1/images/edits -F model=flux2-klein-4b -F image=@photo.png \
  -F prompt="turn it into a pencil sketch" -F seed=7
```

- `image`: one picture, PNG, JPEG, WebP, GIF or BMP, up to 25 MiB. It is cropped to a square at its centre and scaled
  to 512x512. Transparent parts become white.
- `prompt`: the change, in words. An edit needs one. A variation takes none: it is the picture under an empty
  instruction, and each `seed` gives another one.
- `mask` is refused. The model edits by instruction, so describe the part to change in the prompt.
- `size`: `512x512` or `auto`. Every edit comes out at 512x512.
- `n` (one to four), `response_format` (`b64_json` or `url`), `output_format` (`png`) and `seed` work as they do for
  generations. A `model` that is not one of the server's own (OpenAI's `gpt-image-1`, say) reaches the loaded image
  model.

## Speech to text

Name `qwen3-asr-0.6b` or `qwen3-asr-1.7b` in `HALOGEN_NPU_MODELS` and it is fetched and served. It transcribes a
recording on `/v1/audio/transcriptions`, in OpenAI's multipart shape:

```
curl -s localhost:8731/v1/audio/transcriptions -F model=qwen3-asr-1.7b -F file=@meeting.wav
```

- `file`: a WAV file, PCM (8 to 32-bit) or float, any sample rate, mono or more channels. Other formats are refused
  for now.
- Recordings of up to 20 minutes or 25 MiB, whichever comes first, in one request. A longer one is refused with both
  limits named.
- `model`: any name reaches the loaded speech model, so a client that sends `whisper-1` works unchanged. One speech
  model is served at a time. Name `qwen3-asr-0.6b` or `qwen3-asr-1.7b` in `HALOGEN_NPU_MODELS`, not both.
- `language`: optional, a name (`Italian`) or a two-letter code (`it`). Without it the model names the language
  itself.
- `prompt`: optional context for the model, such as names or terms the recording uses.
- `response_format`: `json` (the default, `{"text": ...}`) or `text`. `stream` is refused.

The 1.7B is the more accurate of the two, and the 0.6B the lighter. One transcription runs at a time on the NPU,
queued with the other NPU models' work.

A speech model, the image sizes above 512x512, `embeddinggemma-2`, and `wemm-embedding-4b`'s pictures each need a
large share of the NPU's memory, which every NPU model of the server shares. When a request does not fit beside what the
other NPU models hold, the server closes their idle parts and tries again. They reopen at their next request, which then
takes a little longer, so alternating these models is slower than using one at a time. A request that still does not fit
answers 503 with an error that says so, and the server keeps running. 256x256 and 512x512 images always fit.

While the models take turns, the kernel log (`dmesg`) can show `amdxdna` error lines such as
`Failed to alloc dev bo memory, ret -28`. They mean the driver turned down a first try. The server recovers by itself,
and the answers are unaffected.

<a id="your-own-model"></a>
## Your own model

A fine-tune of the decision, embedding, reranking or moderation model runs on the NPU too. Put it on the models volume as your trainer saved it (a
directory with `config.json`, `model.safetensors` and `tokenizer.json`), and name its path:

```
-e HALOGEN_NPU_MODELS=decider-0.8b,/models/my-guard
```

At the first start the server converts it for the NPU and keeps the result in the same directory
(`halogen-npu.hnpw`), so the next start skips that step. If you change the checkpoint, the next start converts it
again. It is served under the directory's name, here `my-guard`. What it does comes from the checkpoint:

- a fine-tune of Qwen3.5-0.8B answers decisions. Start from `decider-0.8b` to keep its prompt layout, which the server
  builds from your messages and schema.
- a fine-tune of Qwen3-Embedding-0.6B answers `/v1/embeddings`.
- a fine-tune of Qwen3-Reranker-0.6B answers `/v1/rerank`.
- a Qwen3-0.6B or Qwen3-Embedding-0.6B fine-tune saved as a sequence classifier answers `/classify`.
- a fine-tune of Qwen3Guard-Gen-0.6B answers `/v1/moderations`. It must keep that model's chat template: the server
  writes the prompt the way the template does, so a changed policy would not be what runs.

It runs on the NPU program of the model it was tuned from, so that program is fetched too under `HALOGEN_DOWNLOAD`
(the program only, not that model's weights). Anything else is refused at start with a line that says what it found
and what runs: another size or architecture, or a LoRA adapter on its own (merge it into the model first). A read-only
volume works, but then the conversion runs at every start.

## Batching

When one request carries several short inputs (embedding texts, rerank documents, or moderation inputs), they run
together in one pass.
Each result is exactly what it would be alone. `HALOGEN_NPU_EMB_BATCH=0` turns this off.

A batch holds up to 8 inputs of up to 512 tokens each, padded to the bucket, so it costs the same (about 0.38 s) for 2
inputs as for 8. A single input takes about 0.07 s up to 128 tokens and 0.09 s above. The server batches a group only
when running its inputs one by one would take longer: from 6 inputs of up to 128 tokens, from 5 of up to 512. Smaller
groups, and the leftover of a larger request, run one pass each.

## Many requests at once

The NPU runs one pass at a time. A request takes one pass per input, or one per batch of short inputs. Up to
`HALOGEN_NPU_QUEUE` passes (64) wait on the NPU. Passes past that wait in the server, so a burst, such as a whole
knowledge base sent for embedding at once, is answered more slowly, not refused. A request that cannot start within
`HALOGEN_QUEUE_TIMEOUT` gets `503` with the code `engine_busy` and a `Retry-After` header. Raising `HALOGEN_NPU_QUEUE`
changes no result.

## Limits

- A decision is up to 8,192 tokens, its questions and the model's own template included, and so is an
  `embeddinggemma-2` text, its prompt included. Every other input is up to 4,096 tokens, a rerank pair or a moderation
  prompt included (the model's own template counts). A longer one is refused with a 400 that says so.
- An `embeddinggemma-2` audio clip is up to 30 seconds. An image edit takes one picture and comes out at 512x512.
- The streaming guard watches the first 2,048 tokens of the user's last message and the reply.
- A generation prompt is up to 16,384 tokens (its template counts). The prompt and its answer share 18,432 positions,
  so an answer stops there at the latest.
- A decision takes 2 to 10 options.
- A transcription takes a WAV file of up to 20 minutes or 25 MiB.
- With several large NPU models loaded (a speech model, `embeddinggemma-2`, `wemm-embedding-4b`, images above
  512x512), they take turns at the NPU's memory. Alternating them is slower, and a request that cannot fit answers 503.
- The NPU models are served in the default mode only, not in the two-container setup (`engine` and `api`).

<a id="host"></a>
## The host

- **The NPU driver, `amdxdna`.** Recent kernels carry it. Otherwise, install AMD's xdna-driver package. We test the
  kernel's own driver on Ubuntu 26.04 (kernel 7.0), and AMD's driver 2.25 on kernel 6.17.
- **XRT with its NPU plugin**, from AMD's packages or from your distribution. The container uses the host's XRT, so it
  matches the host's driver. We test AMD's XRT 2.25 and Ubuntu 26.04's XRT 2.21 (`libxrt2`, `libxrt-npu2`).
- **The NPU firmware.** The driver package or `linux-firmware` installs it.
- **The IOMMU on.** The NPU driver needs it. `amd_iommu=off`, which the README measures for GPU prefill, turns the NPU
  off. `iommu=pt` keeps it.

**Where your XRT lives.** The container needs three XRT libraries from the host: `libxrt_coreutil.so.2`,
`libxrt_core.so.2` and the NPU plugin `libxrt_driver_xdna.so.2`. AMD's packages put XRT in `/opt/xilinx/xrt`, and the
command above mounts that directory. A distribution's packages put it in the system library directory
(`/usr/lib/x86_64-linux-gnu` on Ubuntu, `/usr/lib` on Arch and CachyOS, whose packages are `xrt` and
`xrt-plugin-amdxdna`). Those libraries look for each other at that path, so mount each one twice: once where the image
looks for XRT, and once at its own path. Use these mounts in place of the `-v /opt/xilinx/xrt:/opt/xilinx/xrt:ro`
line, with `L=/usr/lib` on Arch and CachyOS:

```
L=/usr/lib/x86_64-linux-gnu; X=""
for f in libxrt_coreutil.so.2 libxrt_core.so.2 libxrt_driver_xdna.so.2; do
  X="$X -v $(readlink -f "$L/$f"):/opt/xilinx/xrt/lib/${f}:ro -v $(readlink -f "$L/$f"):$L/${f}:ro"
done
# then: podman run ... $X ...
```

Do not mount an `/opt/xilinx/xrt` that holds only links into the system library directory. Inside the container those
links point at nothing. The server names such a link at start and prints the mounts to use.

**The device flags.** `--device /dev/accel/accel0` passes the NPU in. `--ulimit memlock=-1:-1` lets the NPU engine lock
the memory the NPU reads. With podman, `--group-add keep-groups` covers it (your user must be in the device's group on
the host, usually `render`). A tool that drives rootless podman through its API socket cannot pass `keep-groups`. It
can pass `--annotation run.oci.keep_original_groups=1` instead. With docker and `--user`, add `--group-add` with the
device's group as a number (`stat -c %g /dev/accel/accel0`).

**The C++ runtime.** The host's XRT libraries run inside the image, so they must not need a newer C library or C++
runtime than the image carries (the image is Debian 13: glibc 2.41, `GLIBCXX_3.4.33`). Ubuntu 26.04's XRT and AMD's
XRT 2.25 both load. If yours does not, the server says so at start and names the library.
