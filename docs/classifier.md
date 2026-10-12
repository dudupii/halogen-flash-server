# Using it as a classifier

The model can score a fixed set of labels in one forward pass. End the prompt
where the label goes, ask for `max_tokens: 1` with `logprobs` and
`top_logprobs`, and read the probability the model gives each label. There is
no text to parse and nothing is generated past that one token.
[docs/CLASSIFY.md](CLASSIFY.md) has a complete request, a Python
function that returns each label's probability, how to choose labels, and how
to lay out the prompt so the cache reuses everything but the item.
