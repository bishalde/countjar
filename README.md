# CountJar

Hosted counters for websites, apps and scripts: every number gets its own URL.
Sign in with a phone code, create up to 5 counters, and read or bump them over
the API, with drop-in widgets, SVG badges, a tracking pixel, history charts and
milestone alerts.

The user manual lives in the app at `/docs`.

## How it's built

- **Flask** renders every page (Jinja templates in `countjar/templates/`) and serves
  the JSON API under `/api/v2`. There is no separate frontend app.
- **Tailwind CSS** styles the templates. `tailwind/` only holds the build tool; it
  compiles to `countjar/static/app.css`, which is committed so deploys need no Node.
- **Alpine.js** and **Chart.js** add interactivity and charts, loaded from a CDN.
- **MongoDB** stores everything. **Twilio Verify** sends sign-in codes.

## Run locally

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt -r requirements-dev.txt
.venv/bin/python app.py          # http://localhost:5001
```

Settings are read from the environment (and from a local `.env` file if present);
`countjar/config.py` lists them. With `VERIFY_DEV_MODE=1`, sign-in codes are
printed to the terminal instead of being texted.

## Change styles

Edit templates or `tailwind/app.css`, then rebuild the CSS:

```sh
cd tailwind && npm install && npm run build   # or: npm run watch
```

## Test

```sh
.venv/bin/python -m pytest
```

Tests use an in-memory MongoDB, so they need no database or Twilio account.

## Deploy

Vercel detects the Flask app in `app.py`. Set the production settings in the
Vercel project's environment variables. The app refuses to start on Vercel with
the development secret key or with `VERIFY_DEV_MODE` turned on.
