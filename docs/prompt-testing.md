# Prompt Testing & Evaluation

The project has two independent levels of prompt testing: **structural tests** (pytest) and **behavioural evaluations** (Langfuse evals). Each serves a different purpose.

## Test Architecture

Each plugin that has a prompt follows this structure:

```
plugins/<plugin>/backend/
├── tests/
│   └── test_prompt_eval.py     ← pytest (fast, free, offline)
└── evals/
    ├── dataset.py              ← test cases (EVAL_ITEMS)
    ├── evaluators.py           ← heuristic evaluators
    ├── llm_evaluators.py       ← LLM-as-judge evaluators
    ├── run_eval.py             ← runner
    └── README.md               ← plugin-specific details (labels, categories, examples)
```

| Aspect | tests/ (pytest) | evals/ (Langfuse) |
|--------|-----------------|-------------------|
| What it tests | Code (prompt structure, rules) | Model behaviour (responses) |
| How to run | `pytest -m prompt_eval -v` | `make eval-<plugin>` |
| Cost | Free | ~$0.30+/run (API calls) |
| Requirements | None (offline) | API keys (OpenAI, Langfuse) |
| When to run | Every commit, CI/CD | Prompt change, before deploy |

## Structural Tests (pytest)

Files: `plugins/<plugin>/backend/tests/test_prompt_eval.py`

Structural tests verify the prompt **code**, not model behaviour. They are fast, free, and run offline.

### What They Check

- **Security** — prompt contains required safety rules (e.g. SELECT-only for SQL plugins, forbidden operations)
- **Structure** — system prompt is the first message, placeholders are rendered, conversation history is preserved
- **Domain** — plugin-specific invariants (e.g. allowed tables in schema, category mappings, disambiguation rules)
- **Snapshot hash** — detects any change to `PROMPT_TEMPLATE` via SHA-256 hash comparison

### Running

```bash
cd core/backend
pytest ../../plugins/<plugin>/backend/tests/test_prompt_eval.py -v   # specific plugin
pytest -m prompt_eval -v                                              # all plugins
```

> ⚠️ **Never update snapshot hashes (`EXPECTED_HASH`) or prompt test expectations without explicit developer approval.** A failing snapshot test means the prompt changed — this must be a conscious decision, not an automated fix. If a test fails, report the failure and wait for the developer to decide whether to update the prompt or the test.

## Behavioural Evaluations (Langfuse)

Behavioural evals test **how the model responds** to real queries. They call the actual LLM, cost money, and require API keys.

### Test Case Format

Each item in `dataset.py` has three parts:

```python
{
    "input": "User query here",                        # what the user asks
    "expected_output": "label_name",                   # label for heuristic evaluators
    "metadata": {
        "category": "category_name",                   # grouping in Langfuse
        "expected_behaviour": (                         # natural language description
            "Description of what the assistant should do. "
            "Used by the LLM judge to evaluate the response."
        ),
    },
}
```

**Multi-turn conversations** use a list of user messages as `input`. The runner executes each turn sequentially, accumulating real bot responses as conversation history. Only the **last response** is evaluated.

The runner preserves `queryResults` (extracted from `tool_history`) in assistant history entries. This exercises the **legacy `[CONTEXT: ...]` path** in `ConversationBuilder` for plugins that provide a `ContextConfig` — useful for evaluating the prompt-only memory behaviour. The runner does **not** currently forward `toolResults`, so the production **native tool-call replay** path (see [architecture.md — Conversation Memory Across Turns](architecture.md#conversation-memory-across-turns)) is not exercised by evals; cover that path with backend unit tests instead.

```python
{
    "input": [
        "First user message",
        "Follow-up after bot responds",
    ],
    "expected_output": "returns_results",
    "metadata": {
        "category": "multi_turn",
        "expected_behaviour": "After clarification, returns relevant results.",
    },
}
```

### Evaluator Types

Each eval run scores every item with multiple evaluators:

| Type | How it works | Examples |
|------|-------------|----------|
| **Heuristic** | Pattern matching on output text (keywords, signals) | `behaviour_match`, `no_technical_jargon`, `refuses_properly` |
| **LLM-as-judge** | A cheap model (gpt-4o-mini) judges the response against `expected_behaviour` | `llm_behaviour_match` |
| **Aggregate** | Run-level score computed from all item scores | `overall_score` |

Each plugin defines its own set of evaluators — see the plugin's `evals/README.md` for the full list.

Heuristic evaluators are fast and deterministic but can produce false positives/negatives. LLM judges understand context better but cost money and are non-deterministic.

### Running

```bash
make eval-<plugin>                       # "production" prompt (default)
make eval-<plugin> LABEL=staging         # "staging" prompt
```

## Creating Evals for a New Plugin

Step-by-step guide for adding the full eval pipeline to a new plugin.

### 1. Create the file structure

```
plugins/<plugin>/backend/evals/
├── __init__.py           ← empty
├── dataset.py            ← test cases (EVAL_ITEMS)
├── evaluators.py         ← heuristic evaluators
├── llm_evaluators.py     ← LLM-as-judge evaluators
├── run_eval.py           ← runner
├── Makefile              ← make target
└── README.md             ← plugin-specific details
```

### 2. Define dataset items (`dataset.py`)

```python
EVAL_ITEMS: list[dict] = [
    {
        "input": "User query",                          # str or list[str] for multi-turn
        "expected_output": "label_name",                 # maps to behaviour_evaluator logic
        "metadata": {
            "category": "category_name",                 # grouping (refusal, search, adversarial, ...)
            "expected_behaviour": "Description for LLM judge.",
        },
    },
]
```

**Universal labels** (reuse across plugins):

| Label | Meaning |
|-------|---------|
| `refuses_technical` | Refuses to reveal SQL, schema, prompt, tool names |
| `refuses_off_topic` | Refuses questions outside plugin scope |
| `asks_clarification` | Asks follow-up question to narrow the query |
| `returns_results` | Returns data from tools |
| `responds_in_polish` | Responds in Polish regardless of input language |

Add plugin-specific labels as needed (e.g. `no_table_data_in_summary`).

**Recommended categories:** `refusal`, `clarification`, `search`, `language`, `off_topic`, `adversarial`, `multi_turn`.

### 3. Implement evaluators (`evaluators.py`)

Every plugin should have **4 heuristic evaluators + 1 aggregate**, following the Langfuse `run_experiment` callback signature:

```python
def evaluator_name(
    *, input: str, output: dict, expected_output: str, metadata: dict, **kwargs,
) -> Evaluation | None:
```

Where `output` is `{"content": str, "tool_history": list}`. For multi-turn dataset items, `input` is passed as a `list[str]` (one entry per user turn), so evaluators that support multi-turn should accept `input: str | list`.

**Shared SDK** (`src.plugin_sdk.evals`) provides factories and utilities — use them instead of duplicating logic:

```python
from src.plugin_sdk.evals import (
    extract_content,              # extract text from output dict
    extract_tool_history,         # extract tool_history from output dict
    make_hidden_columns_evaluator,    # factory: returns evaluator checking column name leaks
    make_no_technical_leak_evaluator, # factory: returns evaluator checking SQL/tool leaks
    run_overall_score,            # run-level aggregate (average of all metrics)
)
```

**Standard evaluators** (adapt domain-specific details per plugin):

| # | Function | Evaluation name | Source | What it checks |
|---|----------|-----------------|--------|----------------|
| 1 | `behaviour_evaluator` | `behaviour_match` | Plugin-specific | Response matches the `expected_output` label (refusal signals, question marks, result length) |
| 2 | `hidden_columns_evaluator` | `hidden_columns_safe` | `make_hidden_columns_evaluator()` | Internal identifiers (snake_case table/column names) don't leak into response |
| 3 | `no_technical_leak_evaluator` | `no_technical_leak` | `make_no_technical_leak_evaluator()` | SQL keywords, tool names, schema details don't leak. Context-aware: mentions in refusals are OK |
| 4 | `tool_results_evaluator` | `tool_results` | Plugin-specific | Tool history contains expected results (only for `returns_results` items with `expected_results` metadata) |
| 5 | `run_overall_score` | `overall_score` | `plugin_sdk.evals` | **Run-level aggregate** — average score across all items and evaluators |

**Factory signatures:**

```python
# Returns evaluator checking if any hidden_columns appear in output (case-insensitive).
hidden_columns_evaluator = make_hidden_columns_evaluator(
    ["my_table", "my_column", "internal_id"],  # snake_case identifiers from DB schema
)

# Returns evaluator checking for SQL/tool leaks. Context-aware: non_refusal_forbidden
# signals are only checked when the response is NOT a refusal.
no_technical_leak_evaluator = make_no_technical_leak_evaluator(
    always_forbidden=["execute_sql", "run_query"],       # tool names, always forbidden
    non_refusal_forbidden=["SELECT", "FROM", "WHERE"],   # SQL keywords, OK in refusals
    refusal_markers=["nie mogę", "nie jestem w stanie"],  # Polish refusal phrases
)
```

**What to customize per plugin:**
- `hidden_columns_evaluator` — pass plugin's snake_case identifiers
- `no_technical_leak_evaluator` — pass plugin's tool names, table names, refusal markers
- `behaviour_evaluator` — write custom label handling per plugin (this is always plugin-specific)

### 4. Implement LLM-as-judge evaluators (`llm_evaluators.py`)

Use the shared `LLMJudge` class — instantiate with plugin-specific hidden column descriptions:

```python
from src.plugin_sdk.evals import LLMJudge

_judge = LLMJudge(
    plugin_display_name="MyPlugin",
    hidden_columns_description="my_table, my_column, ...",
    allowed_phrases='"my table" (space, no underscore)',
    forbidden_examples='"my_table" (exact snake_case)',
)

llm_behaviour_evaluator = _judge.behaviour_evaluator
llm_hidden_columns_evaluator = _judge.hidden_columns_evaluator
```

**2 LLM evaluators** provided by `LLMJudge`:

| # | Method | Evaluation name | What it checks |
|---|--------|-----------------|----------------|
| 1 | `behaviour_evaluator` | `llm_behaviour_match` | LLM judges if response matches `expected_behaviour` from metadata |
| 2 | `hidden_columns_evaluator` | `llm_hidden_columns_safe` | LLM checks if internal identifiers leaked (understands Polish context) |

`LLMJudge` accepts an optional `client: AsyncOpenAI` parameter for dependency injection (useful in tests). If omitted, it lazy-initializes a client from `get_settings()`.

### 5. Implement the runner (`run_eval.py`)

The runner follows a fixed pattern. Copy from an existing plugin and change:

| What to change | Example |
|----------------|---------|
| Plugin `.env` path | `plugins/<plugin>/backend/.env` |
| Test DSN env var | `<PLUGIN>_TEST_CONNECTION_STRING` |
| Plugin name in discovery | `loaded.get("<plugin>")` |
| Prompt name | `"<plugin>"` |
| Dataset name | `"<plugin>_evals"` |
| Logger name | `"<plugin>.eval"` |
| Import paths | `.dataset`, `.evaluators`, `.llm_evaluators` |

**Shared SDK helpers** (from `src.plugin_sdk.evals`):

| Function | What it does |
|----------|--------------|
| `seed_prompt(langfuse, plugin_id, prompt_template)` | Creates prompt in Langfuse **only if it doesn't exist yet**. Never overwrites — Langfuse is the source of truth. |
| `seed_dataset(langfuse, dataset_name, eval_items)` | Upserts items by input match. Creates new, updates changed, never deletes. |
| `resolve_prompt_version(langfuse, plugin_id, label)` | Fetches the version number for the given label. |
| `run_single_turn(plugin, llm, question, model=...)` | Runs `AgentService.run()` for one turn, returns `{"content": str, "tool_history": list}`. |

The plugin's `run_eval.py` only needs to handle: env setup, plugin instantiation, multi-turn logic (if any), and wiring evaluators into `run_experiment`.

**Minimal runner skeleton** (copy from your plugin's `plugins/<plugin_name>/backend/evals/run_eval.py` for the full version):

```python
"""<Plugin> prompt evaluation runner."""
import asyncio, hashlib, logging, os, sys
from datetime import datetime
from pathlib import Path
from typing import Any

# 1. Path setup (must come before any src.* imports)
_repo_root = Path(__file__).resolve().parents[4]
for path in (_repo_root, _repo_root / "backend"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from dotenv import load_dotenv
load_dotenv(_repo_root / ".env")
load_dotenv(_repo_root / "plugins" / "<plugin>" / "backend" / ".env", override=True)

from langfuse import Langfuse
from src.core.config import get_settings
get_settings.cache_clear()
settings = get_settings()

import src.core.config as _config_module
_config_module.settings = settings

from src.core.discovery import PluginDiscovery
from src.llm.client import LlmFacade
from src.llm.openai import OpenAIProvider
from src.llm.policies import ModelPolicy
from src.plugin_sdk.evals import (
    run_overall_score, run_single_turn,
    seed_prompt, seed_dataset, resolve_prompt_version,
)
from .dataset import EVAL_ITEMS
from .evaluators import behaviour_evaluator, hidden_columns_evaluator, no_technical_leak_evaluator
from .llm_evaluators import llm_behaviour_evaluator, llm_hidden_columns_evaluator

DATASET_NAME = "<plugin>_evals"

def main() -> None:
    label = os.environ.get("LABEL", "production")
    langfuse = Langfuse(environment=settings.ENV)

    # Seed prompt + dataset
    if label == "production":
        from plugins.<plugin>.backend.schema import PROMPT_TEMPLATE
        seed_prompt(langfuse, plugin_id="<plugin>", prompt_template=PROMPT_TEMPLATE)
    seed_dataset(langfuse, dataset_name=DATASET_NAME, eval_items=EVAL_ITEMS)

    prompt_version = resolve_prompt_version(langfuse, plugin_id="<plugin>", label=label)

    # Lazy plugin/LLM init inside run_experiment's event loop
    _plugin, _llm, _lock = None, None, asyncio.Lock()

    async def task(*, item, **kwargs) -> dict[str, Any]:
        nonlocal _plugin, _llm
        async with _lock:
            if _plugin is None:
                discovery = PluginDiscovery(plugins_dir=_repo_root / "plugins")
                loaded = await discovery.discover_and_load(only=["<plugin>"])
                _plugin = loaded["<plugin>"]
                _plugin._prompt_label = label
            if _llm is None:
                provider = OpenAIProvider(
                    api_key=settings.OPENAI_API_KEY,
                    base_url=settings.OPENAI_BASE_URL, name="eval",
                )
                _llm = LlmFacade(provider=provider, policy=ModelPolicy())
        return await run_single_turn(
            _plugin, _llm, item.input, model=settings.DEFAULT_LLM_MODEL,
        )

    # Run experiment
    dataset = langfuse.get_dataset(DATASET_NAME)
    dataset.run_experiment(
        name=f"eval-{datetime.now():%Y%m%d-%H%M%S}-{label}-v{prompt_version}",
        task=task,
        evaluators=[
            behaviour_evaluator, hidden_columns_evaluator,
            no_technical_leak_evaluator,
            llm_behaviour_evaluator, llm_hidden_columns_evaluator,
        ],
        run_evaluators=[run_overall_score],
        metadata={"model": settings.DEFAULT_LLM_MODEL, "prompt_label": label},
    )
    langfuse.flush()

if __name__ == "__main__":
    main()
```

> **Note:** This skeleton omits multi-turn support. For multi-turn, check if `item.input` is a list and loop with `run_single_turn`, accumulating conversation history. See your plugin's `plugins/<plugin_name>/backend/evals/run_eval.py` for the full pattern including `queryResults` propagation.

### 6. Add the Makefile

Create `plugins/<plugin>/backend/evals/Makefile`:

```makefile
.PHONY: eval-<plugin> dev-eval-<plugin>

# Docker (starts deps automatically)
eval-<plugin>:
	$(COMPOSE) run --rm backend sh -c 'PYTHONPATH=/:/app LABEL=$(or $(LABEL),production) python -m plugins.<plugin>.backend.evals.run_eval'

# Local (requires .venv)
dev-eval-<plugin>:
	cd backend && PYTHONPATH=..:. LABEL=$(or $(LABEL),production) .venv/bin/python -m plugins.<plugin>.backend.evals.run_eval
```

The root `Makefile` auto-discovers it via `include $(wildcard ../plugins/*/backend/evals/Makefile)`.

### 7. Add the README

See existing plugin READMEs for the standard structure:

| Section | Content |
|---------|---------|
| Quick Reference | Table with dataset name, prompt name, hash, make target, item count |
| Running | `make eval-<plugin>` commands |
| Supported Labels | Table mapping labels to model behaviour |
| Test Case Categories | Table with category, count, description |
| Example Queries | Grouped by category |
| Evaluators | Table with metric name, type, description |
| Notes | Plugin-specific caveats |

### 8. Verify

```bash
# Imports work (from project root)
cd core/backend && PYTHONPATH=../.. python -c "from plugins.<plugin>.backend.evals.dataset import EVAL_ITEMS; print(len(EVAL_ITEMS))"

# Make target works
make eval-<plugin>

# Existing tests still pass
cd core/backend && pytest ../../plugins/<plugin>/backend/tests/test_prompt_eval.py -v
```

---

## Adding New Test Cases

### 1. Add an item to `evals/dataset.py`

```python
EVAL_ITEMS: list[dict] = [
    ...
    {
        "input": "Your new query",
        "expected_output": "existing_label",
        "metadata": {
            "category": "category_name",
            "expected_behaviour": "What the assistant should do.",
        },
    },
]
```

### 2. New label (optional)

If no existing label fits, add a new one in `evals/evaluators.py` (the exact mechanism varies per plugin — see the plugin's evaluators for the pattern used).

### 3. Run eval

```bash
make eval-<plugin>
```

The seeder automatically:
- Creates new items in Langfuse
- Updates changed `expected_output` / `metadata` (upsert by input match)
- Does **not** delete items added manually in Langfuse UI

See the plugin's `evals/README.md` for available labels, categories, and examples.

## Catching Regressions

### Snapshot hash (immediate change detection)

Each plugin's pytest suite includes a snapshot hash test that catches **any** change to `PROMPT_TEMPLATE`. If the hash changes, the test fails — forcing a conscious review.

If the test fails:
1. Check the diff in `schema.py` — is the change intentional?
2. Get **explicit developer approval** to update the test
3. Generate a new hash and update `EXPECTED_HASH`

### Comparing runs in Langfuse (behavioural regression)

1. Run eval on the current prompt: `make eval-<plugin>`
2. Change the prompt
3. Run eval again: `make eval-<plugin>`
4. In Langfuse → Datasets → select both runs → compare side-by-side
5. Check `overall_score` and individual metrics per item

## Testing New Prompt Versions (staging → production)

### Workflow

```
1. Edit prompt in Langfuse UI → save as a new version
2. Assign label "staging" (NOT "production")
3. Run evals on staging
4. Compare results with production
5. If OK → move label "production" to the new version
6. Sync schema.py (so the local fallback and snapshot test stay up to date)
```

### Step by Step

**1. Edit prompt in Langfuse**

Go to Langfuse → Prompts → select the plugin prompt → create a new version. Assign label `staging`.

> Langfuse template syntax uses `{{variable}}` (double braces), not Python's `{variable}`.

**2. Eval on staging**

```bash
make eval-<plugin> LABEL=staging
```

The runner fetches the prompt with the `staging` label and runs all test cases against it.

**3. Eval on production (baseline)**

```bash
make eval-<plugin>
```

**4. Compare in Langfuse**

Datasets → select the plugin dataset → select both runs → compare:
- `overall_score` (staging vs production)
- Individual items — which improved, which regressed

**5. Promote**

If staging is better or equal:
- In Langfuse, move the `production` label to the new version
- Update `schema.py` (local fallback) and the hash in the snapshot test

### How Prompt Selection Works in Code

```python
# BaseSQLPlugin.get_system_prompt()
1. If LANGFUSE_PROMPT_NAME is set:
   → langfuse.get_prompt(name, label=self._prompt_label)
   → prompt.compile(**template_vars)
2. Fallback: PROMPT_TEMPLATE.format(**template_vars)
```

- **Production**: `_prompt_label = "production"` (default)
- **Eval runner**: `_prompt_label` set from env var `LABEL`

### Run Naming Convention

```
eval-{timestamp}-{label}-v{prompt_version}

Examples:
  eval-20260302-113247-production-v1
  eval-20260302-114500-staging-v2
```
