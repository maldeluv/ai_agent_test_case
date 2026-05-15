# browser_ai_agent

Stage 4 project skeleton for a CLI browser AI agent.

This step includes Typer CLI startup, Rich terminal output, settings loading, a shared logger utility, a Playwright browser session with a persistent local profile, and an LLM tool-use loop. OpenAI is the default provider; Anthropic remains available via configuration.

## Run

```powershell
cd browser_ai_agent
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e .
python -m playwright install chromium
$env:OPENAI_API_KEY = "your-api-key"
browser-ai-agent "Find the latest invoice in my account"
```

If the active provider API key is not configured, the CLI still starts the browser and
shows the loaded persistent profile, but skips the agent loop. Use `LLM_PROVIDER=anthropic`
with `ANTHROPIC_API_KEY` if you want to switch back to Claude.

## Secrets

Keep real API keys only in `.env` or process environment variables. `.env` and
`.env.*` are ignored by git; `.env.example` is the only env file that should be
committed.

```powershell
Copy-Item .env.example .env
notepad .env
```

For OpenAI, set:

```env
LLM_PROVIDER=openai
OPENAI_API_KEY=sk-...
```

Before pushing, check that no local secret file is staged:

```powershell
git status --short
git ls-files .env .env.*
```

You can also run the module directly:

```powershell
python -m app.main "Find the latest invoice in my account"
```

Use `--no-wait` when you want the command to start and close the browser without waiting for Enter:

```powershell
browser-ai-agent "Find the latest invoice in my account" --no-wait
```
