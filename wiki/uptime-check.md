# Uptime check

A GitHub Actions workflow, `.github/workflows/uptime.yml` ("Uptime"), visits `https://fastpilot.olaheavy.dev` every 15 minutes. It fails when the page doesn't return HTTP 200 with a non-empty body. GitHub then emails the person who owns the schedule (see below).

## Why it runs in this repository

Founder, 25 Nov 2026: "Move it to fastpilot (Recommended)".

- The check used to be infra's "Staging uptime" workflow.
- Infra is a private repository, and GitHub bills every run of a private-repository job as at least one minute. A check every 15 minutes is about 2,900 minutes a month, almost all of the organisation's 3,000 shared private minutes.
- This repository is public, so its Actions minutes are free. The infra workflow was removed when this one was added (infra Phase 22e).

## What it proves, and what it doesn't

- **It proves** that DNS, Cloudflare, TLS, Caddy and the Streamlit frontend answer from the public internet. GitHub's runners count as outside visitors.
- **It doesn't prove** that Chat, Agent or Playground work. The home page is a static Streamlit shell, so a broken backend, Qdrant, Redis or runner still returns 200. Those are watched on the server (infra [Health and Alerting](https://github.com/olaheavy-dev/infra/blob/main/wiki/health-and-alerting.md)).

## Who gets the failure emails

GitHub sends a scheduled workflow's failure emails to the person who last changed its `cron` line. If the workflow was disabled and re-enabled, they go to the person who re-enabled it ([GitHub: notifications for workflow runs](https://docs.github.com/en/actions/concepts/workflows-and-actions/notifications-for-workflow-runs)).

**Keep that the founder's account:** don't let a bot or another person's account edit the `cron` line or re-enable the workflow.

## Running it by hand

```bash
gh workflow run uptime.yml -R olaheavy-dev/fastpilot                          # the live site
gh workflow run uptime.yml -R olaheavy-dev/fastpilot -f domain=<other-host>   # any public host
```

The second form is also how infra checks that GitHub runners are not challenged by Cloudflare on another site.

## Cost and limits

- **Cost:** free, because the repository is public. Each run takes a few seconds and has a 2-minute timeout.
- **Delays:** GitHub may delay or skip scheduled runs when it is busy, so the real gap between checks can be longer than 15 minutes.
- **Pausing:** GitHub disables scheduled workflows in a public repository after 60 days with no repository activity. If that happens, re-enable the workflow from the founder's account.
