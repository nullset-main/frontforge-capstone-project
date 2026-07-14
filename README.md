# FrontForge AI — Planner Agent + Component Agent (starter)

This is a minimal slice of the full FrontForge AI system described in the
capstone brief: just the **Planner Agent** and **Component Agent**, wired
together in a plain sequential pipeline (no LangGraph, per your setup).

## Setup

1. Install [Ollama](https://ollama.com) and pull the model:
   ```bash
   ollama pull qwen2.5:3b
   ```
2. Create a virtualenv and install dependencies:
   ```bash
   python -m venv .venv
   source .venv/bin/activate   # on Windows: .venv\Scripts\activate
   pip install -r requirements.txt
   ```

## Run

```bash
python main.py
```

You'll be prompted for a natural language app description, e.g.:

> "A simple admin dashboard with a sidebar, a topbar, a stats overview page
> with 3 charts, and a users table page."

This will:
1. Call the **Planner Agent**, which asks the model to produce a JSON
   `ProjectPlan` (pages, components, routing, npm dependencies, styling).
   The plan is saved to `generated_project/plan.json`.
2. Loop over every component in the plan and call the **Component Agent**,
   which generates a complete `.jsx` file for each one, using the rest of
   the plan (styling choice, sibling component names, prop lists) as
   context. Files land in `generated_project/src/components/`.

## How the two agents talk to each other

```
requirement (string)
      |
      v
+----------------+        ProjectPlan (pydantic model / plan.json)
| Planner Agent  | -----------------------------------------------+
+----------------+                                                 |
                                                                    v
                                          for each ComponentSpec in plan.components:
                                                     |
                                                     v
                                          +--------------------+
                                          |  Component Agent   |  -> ComponentName.jsx
                                          +--------------------+
```

`frontforge/schemas.py` defines the shared contract (`ProjectPlan`,
`PageSpec`, `ComponentSpec`, `GeneratedComponent`) so both agents agree on
field names without hand-parsing free text between them.

## Where this fits the fuller assignment

- `rag_context` is already a parameter on `ComponentAgent.generate()` — wire
  your ChromaDB/FAISS retriever to fill it in once you build the RAG layer.
- The Clarification, UI Architect, Styling, Package Manager, and Reviewer
  agents from Section 2.4 of the brief would each become another step in
  `main.py`'s `run()` function, either before `planner.plan()` (Clarification)
  or after the component loop (Package Manager, Reviewer).
- Swap `model="qwen2.5:3b"` in `main.py` to compare against larger models for
  your Section 2.3 quantization/model-size analysis.

## Files

```
frontforge/
  llm.py                        # single place to configure the Ollama model
  schemas.py                    # ProjectPlan / ComponentSpec / etc (pydantic)
  prompts/
    planner_prompt.py
    component_prompt.py
  agents/
    planner_agent.py             # requirement -> ProjectPlan
    component_agent.py           # ComponentSpec -> .jsx file
main.py                          # wires the two agents together
requirements.txt
```
