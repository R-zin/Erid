# Erid soft launch

A soft launch means a small, invite-only group of early users on one hosted instance.
Nothing is announced publicly yet. The goals are to find rough edges and to prove
that shared context really carries over between Claude Code, Cursor and Codex. It
should not attract strangers.

## 1. Go / no-go checklist

### Ready in the repo

- [x] Lint, format and the full test suite are green (SQLite and Postgres CI jobs).
- [x] Compose stack has healthchecks, start ordering and a one-shot deploy (`infra/deploy.sh`).
- [x] Production overlay (`docker-compose.prod.yml`): HTTPS via Caddy, only ports 80/443 exposed,
      Postgres in a named volume, and a refusal to start without its secrets.
- [x] Closed mode on by default in production (`ERID_ALLOW_OPEN_WORKSPACES=0`): no anonymous
      workspaces and no slug squatting.
- [x] Workspace provisioning is operator-only (`ERID_ADMIN_TOKEN`) and the workspace
      directory is private (`ERID_PUBLIC_WORKSPACE_DIRECTORY=0`).
- [x] Startup logs a warning for every dev-only setting that is still on.

### Do on the host before inviting anyone

- [ ] Pick a domain and point its DNS A/AAAA record at the host. Open ports 80 and 443.
- [ ] `cp .env.example .env`, then fill in:
  - `ERID_ENV=prod`, `ERID_DOMAIN=erid.example.com`
  - `POSTGRES_PASSWORD`, `ERID_ADMIN_TOKEN`, `ERID_SESSION_SECRET` (`openssl rand -hex 32` each)
  - A stable `ERID_JWT_PRIVATE_KEY` / `ERID_JWT_PUBLIC_KEY` pair. Without it, every token
    dies on restart.
  - Optional: GitHub/Google OAuth apps with callback `https://$ERID_DOMAIN/api/auth/<provider>/callback`
- [ ] `./infra/deploy.sh`. Then check `https://$ERID_DOMAIN/health` and confirm the startup
      log shows **no** `ERID_*` warnings.
- [ ] Smoke test from your laptop: provision a test workspace, add the MCP server in Claude Code,
      call `workspace_summary`, and create a decision. Watch it appear live on the dashboard.
- [ ] Backups: a nightly `docker compose exec -T postgres pg_dump -U postgres erid | gzip > erid-$(date +%F).sql.gz`
      run from cron, copied off the box. Do one test restore before launch.
- [ ] Uptime check on `https://$ERID_DOMAIN/health` (any free pinger is fine).

### Known gaps (acceptable for a soft launch, fix before a public launch)

- The dashboard's "create workspace" button won't work once `ERID_ADMIN_TOKEN` is set.
  The operator provisions workspaces with curl (below).
- No error reporting service (Sentry or similar). Watch the logs, and the Prometheus
  metrics described in `docs/production.md`.

Rate limiting, metrics and running several API instances, all gaps in earlier
versions of this list, are now built in; see `docs/production.md`.

## 2. Onboarding a tester

```bash
# Operator: create the team's workspace and capture the owner key (shown once).
curl -s -XPOST "https://$ERID_DOMAIN/api/workspaces?slug=acme" \
  -H "X-Admin-Token: $ERID_ADMIN_TOKEN" | jq -r .api_key
```

Send the owner key over a private channel (a password manager share, not email), along
with the message below.

## 3. Launch materials

### Invite message (DM / email to each tester)

> Hey! I'm soft-launching **Erid**, a shared, real-time memory for AI coding tools.
> Claude Code, Cursor and Codex all read and write the same project state: open tasks,
> decisions, handoffs and who's editing what. A new session starts with the full picture
> instead of from zero.
>
> You're one of a handful of early users. Setup takes about 2 minutes:
>
> ```bash
> claude mcp add --transport http erid https://ERID_DOMAIN/mcp \
>   --header "X-Erid-Workspace: YOUR_SLUG" \
>   --header "X-API-Key: YOUR_KEY"
> ```
>
> (Cursor and Codex configs: https://github.com/R-zin/Erid/tree/main/clients)
> Dashboard: https://ERID_DOMAIN. Paste your key to see everything live.
>
> Try it for a week on a real project. At the end of a session, ask your agent to
> "leave a handoff". At the start of the next one, ask it to "catch up". Then tell me
> what broke, what was confusing, and whether it saved you any re-explaining.
> It's early: expect rough edges, and please don't put secrets in decisions or tasks yet.

### Short post (for a small community / friends' Discord, once testers are happy)

> Built **Erid**: a self-hostable, real-time context server for AI coding agents.
> Every MCP-capable tool (Claude Code, Cursor, Codex CLI) shares one live project state:
> tasks, decisions, handoffs and presence, with a dashboard streaming over WebSocket.
> No more agents re-deciding things another session already settled.
> FastAPI + Postgres, MIT licensed: https://github.com/R-zin/Erid. Looking for a few
> teams to try the hosted beta; DM me.

## 4. Feedback loop

- One feedback channel (a GitHub Discussion or a small group chat) and a weekly 15-minute
  check-in per tester.
- Ask the same three questions every time: *What did your agent pick up from Erid that it
  would otherwise have asked you? What went wrong? What would make you stop using it?*
- Triage into GitHub issues labelled `softlaunch`. Fix blockers within the week.

## 5. Exit criteria for a public launch

- ≥ 3 teams have used it for ≥ 2 weeks with no data loss and no security incident.
- Rate limiting and error reporting are in place, and backups are verified by a restore.
- The self-serve signup path is decided: OAuth sign-up with automatic workspace creation,
  or a waitlist.
