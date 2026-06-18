# lgharness

A small LangGraph-based agent harness CLI.

## Run

    export OPENAI_API_KEY=sk-...
    export OPENAI_BASE_URL=https://your-openai-compatible/v1   # optional
    python -m lgharness --model gpt-4o-mini

## Permission modes

- `default` (ask before write_file / bash)
- `full_auto` (no prompts)
- `plan` (block mutating tools)

    python -m lgharness --permission-mode full_auto
