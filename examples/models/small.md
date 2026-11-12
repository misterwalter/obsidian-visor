A language model: name it on a note as `small`. Change a value after its colon; visor reads this note and writes it back in this form a minute after you stop editing it. `On this server` is visor's: what it found. Its recipe goes in a `## Modelfile` section at the end, as a code block: visor registers it in Ollama when it changes. The recipe's `PARAMETER num_ctx` is the model's context length, how much it can see at once, and the one place it is set: visor reads it back from Ollama for the agents, chats and games. Ollama loads no more than the weights were trained for. The agents' harnesses are set for 65536: much less and they spend their time summarising. More takes more memory. With none, Ollama uses its default, 4096. Ticking `Fetch` has visor download the weights through Ollama (directly, not through the VPN).

Kind: language
Ollama: small
Max tokens: 8192

- [x] Thinks (it can think before it answers: a note asks it to with `Thinking:`)
- [ ] Fetch (visor downloads what is missing, when it is next idle)

On this server:

## About

Qwen3 8B: Small enough for a modest machine, it can think and call tools, but it will struggle with larger tasks. Fine for chats, questions and small, well-scoped changes. It has a short context length of 40960. That is short of the 65536 the harnesses are set for, so a long job summarises often. It takes about 11 GB of memory in all, about 5 GB of which is the weights.

## Modelfile

```
FROM qwen3:8b
PARAMETER num_ctx 40960
```
