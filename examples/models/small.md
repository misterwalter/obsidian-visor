Kind: language
Max tokens: 8192

- [x] Thinks (it can think before it answers: a note asks it to with `Thinking:`)
- [ ] Fetch (visor downloads what is missing, when it is next idle)
- [ ] Delete (visor deletes it from this server when it is next idle, and keeps this note)

On this server:

## About

Qwen3 8B: Small enough for a modest machine, it can think and call tools, but it will struggle with larger tasks. Fine for chats, questions and small, well-scoped changes. It has a short context length of 40960. That is short of the 65536 the harnesses are set for, so a long job summarises often. It takes about 11 GB of memory in all, about 5 GB of which is the weights.

## Modelfile

```
FROM qwen3:8b
PARAMETER num_ctx 40960
```
