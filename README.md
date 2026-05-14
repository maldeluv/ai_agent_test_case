# browser_ai_agent

Stage 2 project skeleton for a CLI browser AI agent.

This step includes Typer CLI startup, Rich terminal output, settings loading, a shared logger utility, and a Playwright browser session with a persistent local profile. Claude is intentionally not connected yet.

## Run

```powershell
cd browser_ai_agent
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e .
python -m playwright install chromium
browser-ai-agent "Find the latest invoice in my account"
```

You can also run the module directly:

```powershell
python -m app.main "Find the latest invoice in my account"
```

Use `--no-wait` when you want the command to start and close the browser without waiting for Enter:

```powershell
browser-ai-agent "Find the latest invoice in my account" --no-wait
```
