# Toolbox MCP Server

This project uses an MCP (Model Context Protocol) server called **toolbox**. It provides tools for temporal/entity lookups, language, and code execution.

## Deployment

- **Where:** Azure Container (deployed from the toolbox repo).
- **Transport:** SSE (Server-Sent Events).
- **Endpoint:** `https://<your-azure-container-url>/sse`  
  (Replace with the real URL of your container, e.g. `https://toolbox.azurecontainer.io/sse`.)
- **Health check:** `GET https://<url>/health`
- **List tools (REST):** `GET https://<url>/tools`

## Tools

| Tool | Purpose |
|------|--------|
| `before_absolute_reference` | Entity’s association immediately *before* a given date/time. Args: `entity`, `time`. |
| `before_chronological_reference` | Entity’s association immediately before a named event. Args: `entity`, `event`. |
| `after_absolute_reference` | Entity’s association immediately *after* a given date/time. Args: `entity`, `time`. |
| `after_chronological_reference` | Entity’s association immediately after a named event. Args: `entity`, `event`. |
| `event_time` | Date/time when a specified event occurred. Args: `event`. |
| `entity_time_event` | What role/position/event an entity had at a specific time. Args: `entity`, `time`. |
| `language_detection` | Detect language of text. Args: `text`. |
| `translation` | Translate text between languages. Args: `text`, `source_language`, `target_language`. |
| `code_executor` | Executes raw Python in an isolated subprocess; returns stdout/stderr. For exact calculations (dates, times, arithmetic, or anything that must not be approximated). Submit raw Python only (no markdown fences or shell), use `print()` for output, import what you need. Args: `code`. |

## Using it (e.g. with Smolagent)

Connect to the server via its SSE URL (e.g. with `ToolCollection.from_mcp()` or MCPAdapt’s SSE config), then run your agent (e.g. Smolagent HF + Qwen3) with these tools to do inference on your dataset.