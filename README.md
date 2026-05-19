# AutoLedger 🚗

A self-hosted car running cost tracker. Track fuel, insurance, servicing and other vehicle expenses with full fuel efficiency analysis (MPG, km/L) and spending reports.

Built with Flask + Python + flat JSON storage. Runs in Docker on a Mac, Synology NAS, or any Linux host.

![AutoLedger Dashboard](https://img.shields.io/badge/version-1.8.6-blue) ![Docker](https://img.shields.io/badge/docker-ready-green) ![License](https://img.shields.io/badge/license-MIT-brightgreen)

---

## Features

- **Multi-vehicle support** — track any number of cars independently
- **Fuel efficiency analysis** — MPG and km/L calculated from consecutive full-tank fills
- **LubeLogger import** — import your existing fuel history from LubeLogger CSV exports
- **9 reports** — monthly spend, category breakdown, cumulative spend, MPG trend, km/L trend, price-per-litre trend, cost-per-mile, fill-up interval, fuel vs other costs, annual breakdown table
- **UK date format** — DD/MM/YYYY throughout
- **Light/dark mode** — defaults to light; preference saved in browser
- **JSON backup/restore** — export and import your full data at any time
- **No external dependencies** — fully self-hosted, no cloud services required

---

## Quick Start

### Prerequisites
- [Docker Desktop](https://www.docker.com/products/docker-desktop/) (Mac/Windows) or Docker + Docker Compose (Linux/Synology)

### Mac / Linux

```bash
# 1. Clone the repository
git clone https://github.com/quiggles/autoledger.git
cd autoledger

# 2. Start the container
docker compose up --build

# 3. Open in browser
open http://localhost:5050
```

Data is stored in `./data/` (created automatically on first run).

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

Edit the `.env` file to configure the data storage location:

```bash
# Mac / Linux (default — stores data next to docker-compose.yml)
DATA_PATH=./data

# Synology NAS
DATA_PATH=/volume1/docker/autoledger/data
```

All other settings (currency, categories) are managed through the app's Settings page.

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
| `data/costs.json` | All cost records |
| `data/vehicles.json` | Vehicle definitions |
| `data/settings.json` | User preferences (currency, categories) |

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
| Backend | Python 3.11, Flask 3.0, Gunicorn |
| Storage | JSON files (atomic writes via `tempfile` + `os.replace`) |
| Frontend | Vanilla JS (no framework), Chart.js 4.4 |
| Fonts | Inter + Syne (Google Fonts) |
| Container | Docker + Docker Compose |

---

## Project Structure

```
autoledger/
├── app.py                  # Flask entry point
├── requirements.txt        # Python dependencies
├── Dockerfile
├── docker-compose.yml
├── .env                    # Data path configuration
├── routes/
│   ├── data.py             # Shared JSON load/save helpers
│   ├── costs.py            # Cost record CRUD API
│   ├── vehicles.py         # Vehicle CRUD API
│   ├── settings.py         # Settings API
│   ├── reports.py          # Report aggregation endpoints
│   └── importexport.py     # Import/export endpoints
└── static/
    ├── index.html          # Single-page app shell
    ├── css/styles.css      # All styles (light + dark mode)
    └── js/app.js           # All frontend logic
```

---

## Development

```bash
# Run without Docker (requires Python 3.11+)
pip install -r requirements.txt
DATA_DIR=./data flask --app app run --port 5050 --debug
```

---

## Changelog

See [CHANGELOG.md](CHANGELOG.md) for full version history.

---

## License

MIT — do whatever you like with it.
