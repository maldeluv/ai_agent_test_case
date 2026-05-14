# browser_ai_agent

Stage 4 project skeleton for a CLI browser AI agent.

This step includes Typer CLI startup, Rich terminal output, settings loading, a shared logger utility, a Playwright browser session with a persistent local profile, and a Claude tool-use loop.

## Run

```powershell
cd browser_ai_agent
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e .
python -m playwright install chromium
$env:ANTHROPIC_API_KEY = "your-api-key"
browser-ai-agent "Find the latest invoice in my account"
```

If `ANTHROPIC_API_KEY` is not configured, the CLI still starts the browser and
shows the loaded persistent profile, but skips the agent loop.

You can also run the module directly:

```powershell
python -m app.main "Find the latest invoice in my account"
```

Use `--no-wait` when you want the command to start and close the browser without waiting for Enter:

```powershell
browser-ai-agent "Find the latest invoice in my account" --no-wait
```
