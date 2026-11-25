# Uptime check

A GitHub Actions workflow, `.github/workflows/uptime.yml` ("Uptime"), visits `https://fastpilot.olaheavy.dev` every 15 minutes, at :07, :22, :37 and :52 past the hour. It tries up to three times, 5 seconds apart, and sends `Cache-Control: no-cache` with the user agent `fastpilot-uptime`, so the answer comes from the server, not Cloudflare's cache, and the requests can be found in Caddy's logs. It fails when the page doesn't return HTTP 200 with a non-empty body. GitHub then emails the person who owns the schedule (see below).

## Why it runs in this repository

Founder, 25 Nov 2026: "Move it to fastpilot (Recommended)".

- The check used to be infra's "Staging uptime" workflow.
- Infra is a private repository, and GitHub bills every run of a private-repository job as at least one minute. A check every 15 minutes is about 2,900 minutes a month, almost all of the organisation's 3,000 shared private minutes.
- This repository is public, so its Actions minutes are free. The infra workflow was removed when this one was added (infra Phase 22e).

## What it proves, and what it doesn't

- **It proves** that DNS, Cloudflare, TLS, Caddy and the Streamlit frontend answer from the public internet. GitHub's runners count as outside visitors.
- **It doesn't prove** that Chat, Agent or Playground work. The home page is a static Streamlit shell, so a broken backend, Qdrant, Redis or runner still returns 200. Those are watched on the server (infra [Health and Alerting](https://github.com/olaheavy-dev/infra/blob/main/wiki/health-and-alerting.md)).

## Who gets the failure emails

GitHub sends a scheduled workflow's failure emails to ([GitHub: notifications for workflow runs](https://docs.github.com/en/actions/concepts/workflows-and-actions/notifications-for-workflow-runs)):

1. the account that first created the workflow, here the one that merged the file to `main`;
2. then whoever later changes its `cron` line;
3. or whoever re-enables it after it was disabled.

That person must also have Actions notifications turned on in their own GitHub settings.

**Keep that the founder's account:** the founder merges the pull request that adds this file. Don't let a bot or another person's account edit the `cron` line or re-enable the workflow. To check who owns the schedule, look at the `actor` of the latest scheduled run:

```bash
gh api 'repos/olaheavy-dev/fastpilot/actions/runs?event=schedule&per_page=1' --jq '.workflow_runs[0].actor.login'
```

## Running it by hand

```bash
gh workflow run uptime.yml -R olaheavy-dev/fastpilot                          # the live site
gh workflow run uptime.yml -R olaheavy-dev/fastpilot -f domain=<other-host>   # any public host
```

The second form is also how infra checks that GitHub runners are not challenged by Cloudflare on another site.

## Cost and limits

- **Cost:** free, because the repository is public. Each run takes a few seconds and has a 2-minute timeout.
- **Delays:** GitHub may delay or skip scheduled runs when it is busy, most of all at the start of each hour, which is why the check runs off the hour. The real gap between checks can still be longer than 15 minutes; the old infra check, on the hour, ran about every 2 hours in August 2026.
- **Pausing:** GitHub disables scheduled workflows in a public repository after 60 days with no repository activity. If that happens, re-enable the workflow from the founder's account.
