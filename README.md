# browser_ai_agent

Stage 1 project skeleton for a CLI browser AI agent.

This step includes Typer CLI startup, Rich terminal output, settings loading, and a shared logger utility. Playwright and Claude are intentionally not connected yet.

## Run

```powershell
cd browser_ai_agent
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e .
browser-ai-agent "Find the latest invoice in my account"
```

You can also run the module directly:

```powershell
python -m app.main "Find the latest invoice in my account"
```
