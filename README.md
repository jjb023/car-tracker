# car-tracker

Internal web app for tracking company cars across locations and
booking them onto spaces (dynos, emissions boxes, bays, etc.). 

## Features

- **Dashboard** showing every car's current location, grouped by building + space
- **Cars**: create, edit, archive, move between spaces (or mark off-site); full
  movement history is kept automatically
- **Bookings**: reserve a space for a car for a time window; overlapping
  bookings on the same space are rejected
- **Admin**: create/delete buildings and spaces (kinds: general, bay, emissions,
  dyno, other)
- **Shared-password login** — anyone with the link + password gets in
- **JSON API** at `/api/*` (key-auth via `X-API-Key`) with auto-generated
  OpenAPI at `/docs`, ready to wire up to a Teams LLM bot later

## Stack

- Python 3.10+ · FastAPI · SQLAlchemy 2 · SQLite · Jinja2 + Pico.css

## Setup

```bash
python -m venv .venv
source .venv/bin/activate       # Windows: .venv\Scripts\activate
pip install -r requirements.txt

```

## Run

```bash
./run.sh
# or:  uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Visit <http://localhost:8000> and log in with `APP_PASSWORD`.

## Expose to the company (Cloudflare tunnel)

Install [`cloudflared`](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/),
then in another terminal:

```bash
cloudflared tunnel --url http://localhost:8000
```

Cloudflare prints a public `https://*.trycloudflare.com` URL. Share that URL
and the password with the team. Keep the office PC on and `./run.sh` running.

For a stable URL, register a named tunnel through your Cloudflare dashboard.

## Database

- SQLite file at `data/car-tracker.db` (override with `DB_PATH` in `.env`)
- Schema is auto-created on first startup
- **Do not** put the file inside an actively-syncing OneDrive folder — the
  sync client can corrupt the DB mid-write. Back up instead:

```bash
# Consistent backup (run from cron / Task Scheduler):
sqlite3 data/car-tracker.db ".backup '/path/to/OneDrive/car-tracker-backup.db'"
```

## JSON API

Auth: send `X-API-Key: <API_KEY from .env>`.

```
GET  /api/buildings
GET  /api/spaces[?building_id=…]
GET  /api/cars[?include_archived=true]
GET  /api/cars/{id}
POST /api/cars                         # {reg, make_model, notes}
POST /api/cars/{id}/move               # {space_id|null, notes}
GET  /api/bookings[?active_only=…&car_id=…&space_id=…]
POST /api/bookings                     # {car_id, space_id, start_at, end_at, purpose, notes, created_by}
POST /api/bookings/{id}/cancel
```

OpenAPI UI: <http://localhost:8000/docs>

## Future: Teams bot backed by a local LLM

The goal is to chat with the app in a Teams channel ("book AB12 CDE into
Dyno 1 tomorrow at 9") **without sending any car data to a cloud LLM**. All
inference runs on a machine inside the office network.

Recommended shape:

- **Local inference server** — [Ollama](https://ollama.com) is the easiest
  starting point. It runs on Windows/Mac/Linux, pulls open-weight models,
  and exposes an OpenAI-compatible endpoint at `http://localhost:11434/v1`.
  Good tool-calling models to try: `llama3.1:8b-instruct`,
  `qwen2.5:7b-instruct`, `hermes3`. Heavier alternatives if you have a
  bigger GPU: vLLM, text-generation-inference.
- **Bot service** — a small Python/Node process that:
  1. Receives Teams messages (Azure Bot Service messaging endpoint, exposed
     through the same Cloudflare tunnel — or a simpler channel-scoped
     Incoming/Outgoing Webhook if that's enough).
  2. Sends the user message + this app's OpenAPI schema (fetched from
     `/openapi.json`) as tools to the local LLM.
  3. Executes any tool calls the model returns as HTTP requests against
     `/api/*` (using `X-API-Key`).
  4. Returns the model's final answer back to Teams.
- **Data boundary** — the bot only ever talks to (a) Teams, (b) the local
  LLM, (c) this app's `/api/*`. No car data leaves the office network.

Nothing about this MVP needs to change for the bot to work later — the
OpenAPI spec at `/openapi.json` is the contract it will consume.

## Layout

```
app/
  main.py              FastAPI app, startup, routers
  config.py            .env-driven settings
  db.py                SQLAlchemy engine + session
  models.py            Building, Space, Car, CarLocation, Booking
  schemas.py           Pydantic models for the JSON API
  services.py          move_car, create_booking (conflict check), etc.
  auth.py              Shared-password session cookie + API-key dep
  routes/
    auth_routes.py     /login, /logout
    ui.py              Dashboard, cars, bookings, admin (HTML)
    api.py             /api/* JSON
  templates/           Jinja2 templates (Pico.css styling)
  static/styles.css    A few layout tweaks
data/                  SQLite file lives here (gitignored)
```