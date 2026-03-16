# Amy Brain

Amy's cognitive architecture. Four layers of intelligence from reflexive to deliberative.

## Key Files

- `thinking.py` — L4 deliberation: LLM-powered inner monologue and reasoning
- `sensorium.py` — L3 awareness: temporal sensor fusion, narrative generation
- `instinct.py` — L2 instinct: automatic threat response rules
- `memory.py` — Persistent long-term memory (JSON file)
- `agent.py` — LLM agent with tool use capabilities

## Cognitive Layers

1. **Reflex** — Immediate response (handled in commander.py)
2. **Instinct** — Pattern-matched threat rules (instinct.py)
3. **Awareness** — Sensor fusion narrative (sensorium.py)
4. **Deliberation** — LLM reasoning and planning (thinking.py)

## Related

- Amy commander: `src/amy/commander.py`
- Amy actions: `src/amy/actions/`
- Amy API: `src/amy/router.py`
