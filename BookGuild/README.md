# Book Guild

A Windows desktop app where a guild of AI agents researches, writes, illustrates and typesets books ready to sell on Amazon KDP and Etsy.

- **Plan and phase checklist:** [docs/PLAN.md](docs/PLAN.md). The app is built phase by phase, and each phase is verified before the next one starts.
- **How the code fits together:** [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md). Start here when resuming work.

## Setup (one time)

Requires Python 3.11+.

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
```

## API keys

Keys are read from **Windows environment variables** and are never stored in this project. The variable names are listed in `config/settings.toml`; change a name there if yours differs.

| Variable | Needed for |
|---|---|
| `OPENROUTER_API_KEY` | **required**: all AI calls |
| `TAVILY_API_KEY`, `EXA_API_KEY` | optional: web research (Phase 4) |
| `PEXELS_API_KEY`, `PIXABAY_API_KEY`, `UNSPLASH_ACCESS_KEY` | optional: licensed images (Phase 7) |

## Run

You don't need to activate the virtual environment; just call its Python directly:

```powershell
.\.venv\Scripts\python.exe app.py            # open the app
.\.venv\Scripts\python.exe app.py --check    # list which keys were found, then exit
.\.venv\Scripts\python.exe -m pytest         # run tests (free - no real AI calls)
```

## Models

`config/models.toml` lists the model for each Guild role in three profiles: `test` (cheapest), `balanced` and `quality`. Switch profiles in **AI ▸ Model profile**, and pick models with live prices in **AI ▸ Models…**.
