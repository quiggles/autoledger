# AutoLedger 🚗

A self-hosted car running cost tracker. Track fuel, insurance, servicing and other vehicle expenses with full fuel efficiency analysis (MPG, km/L) and spending reports.

Built with Flask + Python + flat JSON storage. Runs in Docker on Mac, Windows, Linux, or a Synology NAS.

![AutoLedger Dashboard](https://img.shields.io/badge/version-2.0.0-blue) ![Docker](https://img.shields.io/badge/docker-ready-green) ![License](https://img.shields.io/badge/license-MIT-brightgreen)

---

## Features

- **Private by default** — password-protected with a one-time setup that creates
  your admin account on first run (see [First run](#first-run--signing-in))
- **Reminders** — service, MOT, road tax and insurance, by **date or mileage**
  ("MOT due in 12 days", "service due in 5,000 miles"), shown on the dashboard
  and pushed to **Home Assistant** and/or **email**
- **Multi-vehicle support** — track any number of cars independently
- **Fuel efficiency analysis** — MPG and km/L from consecutive full-tank fills,
  with configurable sanity bounds for very efficient or very thirsty vehicles
- **LubeLogger import** — import your existing fuel history from LubeLogger CSV exports
- **9 reports** — monthly spend, category breakdown, cumulative spend, MPG trend, km/L trend, price-per-litre trend, cost-per-mile, fill-up interval, fuel vs other costs, annual breakdown table
- **UK date format** — DD/MM/YYYY throughout
- **Light/dark mode** — defaults to your OS preference; switchable and saved in browser
- **Health endpoint** — `GET /api/health` + a Docker `HEALTHCHECK` for monitoring
  (Container Radar, Homepage siteMonitor, Portainer)
- **JSON backup/restore** — export and import your full data at any time
- **No external dependencies** — fully self-hosted, no cloud services required

---

## Quick Start

### Prerequisites
- [Docker Desktop](https://www.docker.com/products/docker-desktop/) (Mac / Windows) or Docker + Docker Compose (Linux / Synology)
- [Git](https://git-scm.com/downloads)

### Mac / Linux

```bash
# 1. Clone the repository
git clone https://github.com/quiggles/autoledger.git
cd autoledger

# 2. Copy the example env file
cp .env.example .env

# 3. Start the container
docker compose up --build -d
```

Then open **http://localhost:5050** in your browser.

Data is stored in `./data/` (created automatically on first run).

> **First run:** AutoLedger will ask you to create an admin account before you
> can use it. See [First run](#first-run--signing-in) below.

### Windows

```powershell
# 1. Clone the repository
git clone https://github.com/quiggles/autoledger.git
cd autoledger

# 2. Copy the example env file
copy .env.example .env

# 3. Start the container
docker compose up --build -d
```

Then open **http://localhost:5050** in your browser.

> **Note:** Run the commands above in PowerShell, Command Prompt, or Git Bash. Docker Desktop for Windows must be running first.

---

## Synology NAS Installation (DS923+ / DSM 7.x)

### Via Portainer (recommended)

1. Open Portainer → **Stacks** → **Add Stack**
2. Paste the contents of `docker-compose.yml`
3. Set the environment variable `DATA_PATH` to `/volume1/docker/autoledger/data`
4. Deploy the stack

### Via SSH

```bash
# SSH into your NAS
ssh admin@192.168.0.100

# Create directories
mkdir -p /volume1/docker/autoledger/data

# Clone the repo
cd /volume1/docker/autoledger
git clone https://github.com/quiggles/autoledger.git .

# Configure data path
echo "DATA_PATH=/volume1/docker/autoledger/data" > .env

# Start
docker compose up -d --build
```

App will be at `http://192.168.0.100:5050`

---

## Configuration

Copy `.env.example` to `.env` (if you haven't already), then edit it to configure the data storage location:

```bash
# Mac / Linux / Windows (default — stores data next to docker-compose.yml)
DATA_PATH=./data

# Synology NAS
DATA_PATH=/volume1/docker/autoledger/data
```

All other settings (currency, categories, efficiency bounds, reminder schedule,
and notifications) are managed through the app's **Settings** page.

---

## First run / signing in

The first time you open AutoLedger it shows a **Create your admin account**
screen. Choose a username and a password (at least 8 characters) — this is the
single account that protects your data.

> ⚠️ There is **no password recovery**. Store the credential somewhere safe (a
> password manager). If you forget it, you can regain access by deleting
> `data/auth.json` from the data folder and onboarding again — your cost data is
> untouched.

After that, you'll see a normal **Sign in** screen on each new browser/session.
Use the **Sign out** button at the bottom of the sidebar to end a session.

**How your data is protected:** your cost, vehicle and settings files stay as
plain, human-readable JSON (easy to back up and inspect). Only true *secrets* —
your email password and Home Assistant token — are encrypted on disk. None of
those secrets are ever sent back to the browser.

---

## Reminders & Notifications

Create reminders on the **Reminders** page for things like MOT, service, road tax
and insurance. Each reminder can trigger on a **date**, a **mileage**, or both
(whichever comes first), with a warning lead time and optional repeat ("every 12
months" / "every 10,000 miles"). Current mileage is taken from your latest fuel
odometer reading.

Due and overdue reminders appear as a banner on the **Dashboard** and as a count
badge in the sidebar. To get notified when the app is closed, enable channels in
**Settings → Notifications**:

- **Email (SMTP):** works with any SMTP provider. Inline help is provided for
  **Resend** (`smtp.resend.com`, user `resend`, password = your API key) and
  **Gmail** (app password). There's a **Send test email** button to verify it.
- **Home Assistant:** enter your HA base URL and a long-lived access token
  (HA → Profile → Security). AutoLedger pushes a sensor per reminder
  (`sensor.autoledger_<vehicle>_<type>`) you can use on dashboards/automations,
  and can optionally call a notify service. There's a **Send test** button too.

A background job checks reminders once a day (time configurable in Settings) and
sends any that are due. You can also press **Check now** on the Reminders page.

---

## Monitoring (health check)

`GET /api/health` returns JSON with the app status, version and record counts and
requires **no authentication**, so monitors can poll it:

```bash
curl http://localhost:5050/api/health
# {"status":"ok","version":"2.0.0","vehicles":2,"records":418}
```

The Docker image also defines a `HEALTHCHECK`, so `docker ps` / Portainer /
Container Radar / Homepage siteMonitor show real application health.

---

## Updating

```bash
# Pull latest code
git pull

# Rebuild and restart
docker compose up --build
```

Your data in `./data/` is never touched by an update.

---

## LubeLogger Migration

If you're coming from LubeLogger:

1. In LubeLogger, export your fuel log as CSV (each vehicle separately)
2. In AutoLedger, create your vehicle on the **Vehicles** page
3. Go to **Import / Export** → **Import LubeLogger CSV**
4. Select your exported CSV file

AutoLedger reads LubeLogger's column format directly:
`Date, Odometer, FuelConsumed, Cost, FuelEconomy, IsFillToFull, Notes`

---

## Data Storage

All data is stored as plain JSON files in the `data/` directory:

| File | Contents |
|------|----------|
| `data/costs.json` | All cost records (plain JSON) |
| `data/vehicles.json` | Vehicle definitions (plain JSON) |
| `data/settings.json` | Preferences (currency, categories, MPG bounds, check time) |
| `data/reminders.json` | Reminders (plain JSON) |
| `data/notify.json` | Notification config — **secrets encrypted** |
| `data/auth.json` | Admin username + Argon2id password hash |
| `data/secret.key` | Encryption key for secrets (`0600`) |
| `data/session.key` | Session-signing secret (`0600`) |

> The whole `data/` folder is **gitignored** and must never be committed. Back it
> up by copying the folder — keep `secret.key` with it, or the saved email/HA
> secrets will need re-entering (your cost data is unaffected).

**Backup:** use the **Export AutoLedger JSON** button, or simply copy the `data/` folder.

**Restore:** use the **Import AutoLedger JSON** button on the Import/Export page.

---

## Port

The app runs on port **5050** by default. To change it, edit `docker-compose.yml`:

```yaml
ports:
  - "YOUR_PORT:5000"
```

---

## Tech Stack

| Layer | Technology |
|-------|------------|
| Backend | Python 3.12, Flask 3.0, Gunicorn (single worker) |
| Auth | Argon2id (`argon2-cffi`), signed-cookie sessions |
| Secrets | Fernet at-rest encryption (`cryptography`) |
| Scheduling | APScheduler (in-process daily reminder job) |
| Storage | JSON files (atomic writes via `tempfile` + `os.replace`) |
| Frontend | Vanilla JS (no framework), Chart.js 4.4 |
| Fonts | Inter + Syne (Google Fonts) |
| Container | Docker + Docker Compose (with `HEALTHCHECK`) |

---

## Project Structure

```
autoledger/
├── app.py                  # Flask entry point; blueprints; auth guard; scheduler
├── version.py              # Single source of truth for the app version
├── requirements.txt        # Python dependencies
├── Dockerfile              # + HEALTHCHECK
├── docker-compose.yml
├── .env.example            # Config template (data path, optional secrets) — copy to .env
├── docs/adr/               # Architecture Decision Records (0001–0008)
├── routes/
│   ├── data.py             # Shared JSON load/save helpers
│   ├── logging_config.py   # Structured stdout logging
│   ├── crypto.py           # At-rest secret encryption (Fernet)
│   ├── auth.py             # Onboarding, login/logout, API access guard
│   ├── health.py           # /api/health
│   ├── costs.py            # Cost record CRUD API
│   ├── vehicles.py         # Vehicle CRUD API
│   ├── settings.py         # Settings API
│   ├── reports.py          # Report aggregation endpoints
│   ├── importexport.py     # Import/export endpoints
│   ├── reminders.py        # Reminder CRUD + status evaluation
│   ├── notify.py           # Email + Home Assistant channels
│   └── scheduler.py        # Daily reminder job
├── tests/                  # pytest suite (83 tests) — run via `make test`
└── static/
    ├── index.html          # Single-page app shell
    ├── css/styles.css      # All styles (light + dark mode)
    └── js/app.js           # All frontend logic
```

---

## Development

The project ships a `Makefile` with standard targets:

```bash
make run     # build + run in Docker (http://localhost:5050)
make test    # pytest suite on Python 3.12 in Docker (83 tests)
make lint    # ruff
make fmt     # ruff format (opt-in — not run across the aligned-column codebase)
make clean   # remove caches / local venv (never touches ./data)
```

> **Tests run on Python 3.12 inside Docker** because the code uses 3.10+ type
> syntax (`X | None`). `make test` needs Docker running but no host Python. See
> [ADR 0005](docs/adr/0005-testing-approach.md).

**Run directly without Docker** (requires **Python 3.10+** on the host):

```bash
# Mac / Linux
pip install -r requirements.txt
DATA_DIR=./data flask --app app run --port 5050 --debug
```

```powershell
# Windows (PowerShell)
pip install -r requirements.txt
$env:DATA_DIR="./data"; flask --app app run --port 5050 --debug
```

---

## Changelog

See [CHANGELOG.md](CHANGELOG.md) for full version history.

---

## Attribution

This project was fully coded by AI ([Claude](https://claude.ai) by Anthropic) through prompting and direction by **Gary Quigley**. No manual code was written — every line was generated via conversational prompting.

---

## License

MIT — do whatever you like with it.
