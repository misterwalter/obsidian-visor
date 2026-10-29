# small

A language model: name it on a note as `small`. Change a value after its colon; visor reads this note and writes it back in this form a minute after you stop editing it. `On this server` is visor's: what it found. Its recipe goes in a `## Modelfile` section at the end, as a code block: visor registers it in Ollama when it changes. The recipe's `PARAMETER num_ctx` is the model's context length, how much it can see at once, and the one place it is set: visor reads it back from Ollama for the agents, chats and games. Ollama loads no more than the weights were trained for. The agents' harnesses are set for 65536: much less and they spend their time summarising. More takes more memory. With none, Ollama uses its default, 4096. Ticking `Fetch` has visor download the weights through Ollama (directly, not through the VPN).

Kind: language
Ollama: small
Max tokens: 8192

- [x] Thinks (it can think before it answers: a note asks it to with `Thinking:`)
- [ ] Fetch (visor downloads what is missing, when it is next idle)

On this server:

## About

Qwen3 8B: small enough for a modest machine, and able to call tools and to think. Fine for chats, questions and small, well-scoped changes; a bigger model does better on long work in a large codebase. Its recipe below is Qwen3 8B as Ollama has it, with a context length of 40960, the most it was trained for (Ollama loads no more), and about 11 GB of memory in all, 5 GB of it the weights. That is short of the 65536 the harnesses are set for, so a long job summarises often.

## Modelfile

```
FROM qwen3:8b
PARAMETER num_ctx 40960
```
