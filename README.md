# CountJar

Simple hosted counters: hit a URL, get a number. Flask frontend + API.

## API

```
GET /api/v1/<namespace>/<name>/up    # +1
GET /api/v1/<namespace>/<name>/down  # -1
GET /api/v1/<namespace>/<name>       # read
```

## Run locally

```sh
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python app.py   # http://localhost:5001, stores data in countjar.db
```

## Deploy (Vercel)

Import the repo in Vercel (Flask is detected automatically), then add a Postgres
database from the Storage tab so `DATABASE_URL`/`POSTGRES_URL` is set.
