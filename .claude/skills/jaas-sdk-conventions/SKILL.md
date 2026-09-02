---
name: jaas-sdk-conventions
description: Conventions and known gotchas for the framework SDK packages under sdks/ (jaas-client, jaas-langgraph, jaas-crewai, jaas-autogen) — package layout, the real-vs-mocked framework testing split, and the httpx2/TestClient interop trap. Use when reading, writing, reviewing, or committing any code under sdks/.
metadata:
  type: project
---

# JaaS SDK packages (`sdks/`, Phase 4.1)

Four independent Python packages, each with its own `pyproject.toml` and
`.venv`, NOT a uv workspace (kept deliberately simple — see IMPLEMENTATION_
PLAN.md Phase 4.1 for why a formal `[tool.uv.workspace]` wasn't used).
Cross-package dependencies (`jaas-langgraph`/`jaas-crewai`/`jaas-autogen`
all depend on `jaas-client`) are wired via `[tool.uv.sources]` path
entries, editable. Each package's dev extras also carry a path dependency
on `jaas-registry` itself (this repo's root package) — test-time only, for
real end-to-end interop tests; never a runtime dependency, so installing
any SDK package alone never pulls in FastAPI/boto3/sigstore/etc.

**Working in one of these packages:** `cd sdks/<package> && uv sync --extra
dev && uv run pytest -q`. Each has its own `.venv` — don't expect the root
repo's `uv run pytest` to see or run these tests, and vice versa
(`testpaths` in the root `pyproject.toml` is `["tests"]`, which doesn't
reach `sdks/`).

## `jaas-client` — the shared core

Thin `httpx`-based client wrapping exactly the routes `jaasctl search/pull/
install` already use (`cli.py::_download_skill_files`), reimplemented as a
standalone, typed, non-CLI module (`errors.py`'s `JaasClientError`/
`JaasApiError`/`JaasNotFoundError`/`JaasAuthError`, not print-and-return-
None like the CLI helper). Archive extraction (`client.py::_extract_
archive`) is a from-scratch stdlib-`tarfile` reimplementation of `artifact/
packaging.py::extract_archive`, not an import of it — deliberate, so this
package's runtime dependency surface stays `httpx` + `pyyaml` only, never
the full `jaas_registry` package.

`get_entrypoint_content()` is the one client method with real product
judgment behind it: a "skill" in this registry is instructional content
(a manifest-named entrypoint file, typically a SKILL.md), not a directly
invokable function — so the two capabilities every framework adapter
exposes are **search** (discover skills) and **get the entrypoint's raw
text** (load one skill's instructions for an agent to read and follow),
not "call the skill" as if it were an RPC. If a future framework adapter
needs something beyond these two, extend `jaas-client` first, not the
adapter — keep framework packages thin translators over one shared core.

## The three framework adapters — same shape, three conventions

`jaas-langgraph`, `jaas-crewai`, `jaas-autogen` each expose exactly
`build_jaas_tools(client) -> list[<framework's own tool type>]` with two
tools, `search_skills` and `get_skill` — same names, same two-tool
contract, only the wrapping convention differs per framework:

| Package | Real dependency | Tool primitive | Invocation in tests |
|---|---|---|---|
| `jaas-langgraph` | `langchain-core` (+ `langgraph` for interop tests) | `@tool`-decorated function → `BaseTool` | `.invoke({"query": ...})` |
| `jaas-crewai` | `crewai-tools` (+ `crewai` for interop tests) | `@tool`-decorated function → `BaseTool` | `.run(query=...)` (kwargs, not a dict) |
| `jaas-autogen` | `autogen-core` (+ `autogen-agentchat`/`autogen-ext` for interop tests) | `FunctionTool(func, description=..., name=...)` | `await .run_json({"query": ...}, CancellationToken())` -- **async**, unlike the other two |

Each adapter accepts a **structurally-typed** `_JaasClientLike` `Protocol`
(searching for `.search()`/`.get_entrypoint_content()`), not an import of
`jaas_client.JaasRegistryClient` itself — lets a test hand it a minimal
fake without needing a real client, and keeps the adapter decoupled from
`jaas-client`'s concrete implementation. If you add a third tool, extend
this protocol and all three adapters' fakes/tests together, not just one.

**"AutoGen" is ambiguous — this targets the current `autogen-core`/
`autogen-agentchat` packages** (Microsoft's post-2024 rearchitecture), not
the community `pyautogen`/AG2 fork. Confirmed live via `uv pip install
--dry-run` before committing to this, since training data on which
"AutoGen" is canonical right now is exactly the kind of thing likely to be
stale (see this repo's own `AGENTS.md`: verify framework APIs against the
real installed package, don't trust priors).

## Two-tier testing: fakes for logic, real frameworks for interop

Every adapter has two test files:
- `test_adapter.py` — a hand-rolled fake client (not `jaas_client` itself,
  not mocked via a mocking library), proving `build_jaas_tools`'
  formatting/dispatch logic in isolation, fast.
- `test_real_<framework>_interop.py` — the real framework package (real
  `BaseTool`/`FunctionTool`, real `ToolNode`/`Agent`/`AssistantAgent`
  construction) AND a real `jaas_registry` FastAPI app end to end. This is
  the layer that would have caught it if, say, CrewAI's `@tool` decorator
  required an explicit name where LangChain's doesn't (it does; see the
  table above) — confirmed by introspecting each framework's actual
  installed API (`inspect.signature`, trial calls) before writing adapter
  code, not by recalling how these frameworks' tool APIs used to work.

For AutoGen's `AssistantAgent` specifically, constructing one requires a
real `ChatCompletionClient` — use `autogen_ext.models.replay.
ReplayChatCompletionClient(["some canned reply"], model_info=ModelInfo(
function_calling=True, ...))`, never a real LLM provider client, so this
test suite makes zero external network/API calls and zero API costs.

## The httpx2 / FastAPI TestClient trap (real bug hit during Phase 4.1)

`jaas-client`'s own end-to-end test (`test_client_against_real_api.py`)
extracts FastAPI `TestClient`'s internal `._transport` and wraps it in a
plain `httpx.Client(transport=...)` for a fast in-process real-API test —
works fine there. **It silently breaks the moment `httpx2` is installed
anywhere in the same venv** (confirmed: `langchain-core`/`langgraph` pull
in `httpx2` transitively via `langsmith`; `crewai`/`autogen-core` don't,
today, but that could change): `starlette.testclient` auto-detects
`httpx2`'s presence and switches `TestClient`'s internal transport to an
`httpx2`-flavored one, which a classic `httpx.Client` can't consume —
fails with `assert isinstance(response.stream, SyncByteStream)`, a
confusing low-level assertion error with no obvious connection to httpx2.

**Fix used everywhere in `sdks/`:** `tests/_live_server.py` (duplicated
per-package, not shared — each package's tests are self-contained) runs
the real FastAPI app on a real localhost TCP port via `uvicorn.Server` in
a background thread, and the SDK client talks to it over real HTTP. Slower
to set up (~tens of ms) than the transport-extraction trick, but immune to
this class of bug and arguably more representative of real usage anyway.
**Use `run_app()` from that module for any new real-interop test added
here — don't reach for `TestClient()._transport` in `sdks/`, even though
it's exactly what `jaas-client`'s own test does successfully today.** If
you ever add a framework dependency to `jaas-client` itself (unlikely,
given the "keep it thin" design above), re-check whether that test still
works.
