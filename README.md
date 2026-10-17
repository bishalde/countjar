# CountJar

**Hosted counters for websites, apps and scripts. Every number gets its own URL.**

Hit a URL and get a number back. Use it for page views, downloads, sign-ups, likes,
votes, ratings or anything else you want to tally. Then show the number with a
drop-in widget, an SVG badge or your own code, and watch it on a chart.

**Live app:** [countjar.vercel.app](https://countjar.vercel.app) ·
**Docs:** [countjar.vercel.app/docs](https://countjar.vercel.app/docs)

![CountJar landing page](docs/screenshots/landing.png)

## Try it

The demo counter is open to everyone. Run this twice and watch the number go up:

```sh
curl https://countjar.vercel.app/api/v2/demo/test-counter/up
```

```json
{
  "workspace": "demo",
  "name": "test-counter",
  "type": "count",
  "visibility": "public",
  "count": 1285,
  "counted": true
}
```

Leave the action off to read the value. With an API token you can also subtract
(`/down`), set an exact value (`/set?value=42`) or reset it. Every call returns JSON.

## Features

**Counting**
- Four counter types: **counter** (add and subtract), **like** (one per visitor),
  **poll** (yes or no votes with live percentages) and **rating** (1 to 5 stars with
  the average).
- **Public** counters can be read and counted up by anyone with the URL.
  **Private** counters need an API token for every request.
- Step size, minimum and maximum values, and **unique visitors**, so each visitor
  counts once a day or once ever.

**Showing the number**
- **Widgets** with one line of HTML: view counter, like button, poll and star rating.
  Light, dark and glass themes, custom colours, icons and labels.
- **SVG badges** for GitHub READMEs and docs.
- A **tracking pixel** for emails and pages where you can't run JavaScript.
- An **embed builder** on every counter with a live preview and copy-ready snippets.

**Insight**
- History charts for the last **24 hours, 7 days and 30 days**, with CSV and JSON
  export.
- Today, last 7 days and unique visitors at a glance, top referrers, and a log of
  every event.
- **Visitor details** on every visit: country, region, city, device type and model,
  browser, OS, language, page and screen size, with a breakdown by country, city,
  device, browser and OS. IP addresses are recorded too and shown only to the
  workspace owner. Raw events are deleted after 90 days.
- A workspace overview with activity across all counters and the top counters.
- 90 days of raw event history.

**Alerts and teams**
- **Milestone alerts** when a counter reaches a number, by signed **webhook** or
  **text message**.
- **Workspaces** with teammates: owners add people by phone number, and members
  manage counters, tokens and alerts.
- **API tokens** with read, write and admin permissions.

**Accounts**
- **Passwordless sign-in**: enter your mobile number and get a 6-digit code by SMS,
  sent with Twilio Verify.
- An account page with optional profile details: email, birthday, website, company
  or role, and time zone. They stay private to you.

**Free plan**
- 5 counters, 10,000 counted hits a day, up to 3 workspaces and 600 API requests a
  minute per path.

## Screenshots

### Dashboard

| Workspace overview | Counters |
| --- | --- |
| ![Workspace overview with activity chart and top counters](docs/screenshots/overview.png) | ![Counter list with types, access and values](docs/screenshots/counters.png) |

### Counters

| Counter detail and history | Poll results |
| --- | --- |
| ![Counter detail with current value, stats and history chart](docs/screenshots/counter.png) | ![Poll counter showing yes and no percentages](docs/screenshots/poll.png) |

| Embed builder | Milestone alerts |
| --- | --- |
| ![Embed builder with live widget preview and snippet](docs/screenshots/embed.png) | ![Milestone alerts with webhook and text message options](docs/screenshots/milestones.png) |

### Workspace and account

| API tokens | Members |
| --- | --- |
| ![API tokens with read, write and admin permissions](docs/screenshots/tokens.png) | ![Workspace members and add-member form](docs/screenshots/members.png) |

| Account and profile | Sign in |
| --- | --- |
| ![Account page with profile details and plan usage](docs/screenshots/account.png) | ![Phone number sign-in page](docs/screenshots/login.png) |

### Public site

| Dark theme | Docs |
| --- | --- |
| ![Landing page in dark theme](docs/screenshots/landing-dark.png) | ![API reference in the built-in docs](docs/screenshots/docs.png) |

| Pricing | Use-case pages |
| --- | --- |
| ![Pricing page with the free plan](docs/screenshots/pricing.png) | ![Hit counter use-case page with a live widget](docs/screenshots/solution.png) |

### On a phone

| Landing | Overview | Counter |
| --- | --- | --- |
| ![Landing page on a phone](docs/screenshots/phone-landing.png) | ![Workspace overview on a phone](docs/screenshots/phone-overview.png) | ![Counter detail on a phone](docs/screenshots/phone-counter.png) |

## Show a counter on your site

Add a widget with one line of HTML:

```html
<div class="countjar" data-workspace="acme" data-counter="visits"></div>
<script src="https://countjar.vercel.app/embed.js" async></script>
```

Or add a badge to a README:

```markdown
![views](https://countjar.vercel.app/badge/acme/visits.svg)
```

The [docs](https://countjar.vercel.app/docs) cover the full API, code examples for
JavaScript, Python, React, Next.js, Go and PHP, every widget option, and milestone
alerts.

## How it's built

- **Flask** renders every page (Jinja templates in `countjar/templates/`) and serves
  the JSON API under `/api/v2`. There is no separate frontend app.
- **Tailwind CSS** styles the templates. `tailwind/` only holds the build tool; it
  compiles to `countjar/static/app.css`, which is committed so deploys need no Node.
- **Alpine.js** and **Chart.js** add interactivity and charts, loaded from a CDN.
- **MongoDB** stores everything. **Twilio Verify** sends sign-in codes.
- **Vercel** hosts the app.

```
countjar/
  api.py         JSON API: read, count, history, events, stats
  web.py         dashboard: workspaces, counters, tokens, members, account
  auth.py        phone sign-in and onboarding
  embed.py       widget script, SVG badges and tracking pixel
  site.py        landing, pricing and use-case pages, sitemap
  docs.py        the in-app user manual at /docs
  counters.py    counter types, counting rules and history
  accounts.py    users, profiles, workspaces and membership
  notify.py      webhook and SMS milestone alerts
  ratelimit.py   rate limits for the API and sign-in codes
tests/           pytest suite, runs against an in-memory MongoDB
tailwind/        CSS build tool
```

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

## Author

Made by [Bishal De](https://bishalde.vercel.app) ·
[GitHub](https://github.com/bishalde) ·
[LinkedIn](https://www.linkedin.com/in/bishalde/)
