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
cp .env.example .env      # add your MONGODB_URI
set -a; source .env; set +a
.venv/bin/python app.py   # http://localhost:5001
```

## Deploy (Vercel)

Import the repo in Vercel (Flask is detected automatically), then set `MONGODB_URI`
in Project → Settings → Environment Variables. In Atlas, allow access from
`0.0.0.0/0` (Network Access), since Vercel has no fixed IPs.
