# Running it on a Windows PC

No cloud account, no billing, no card, no monthly cost — and the documents never
leave a machine you own, which for files containing SSNs is the better answer
anyway.

Everything runs inside **WSL2** (Windows Subsystem for Linux). That is not a
detour: it means the same Linux commands, the same scripts and the same
container images as any other deployment, so nothing here is a Windows-only
variant that drifts out of date.

---

## What you need

| | |
|---|---|
| Windows 10 (2004+) or Windows 11 | 64-bit |
| 8 GB RAM | 4 GB works; the containers want ~1.5 GB while idle |
| 15 GB free disk | images, database and stored PDFs |
| A machine that stays on | it can only be reached while it is awake |
| Your real template | the blank `CFT_ CD.pdf`, for Stage 5 |
| ~45 minutes | mostly waiting on installs and the first build |

---

## Stage 1 — Install WSL2 and Docker Desktop

**1. Open PowerShell as Administrator** (right-click Start → *Terminal
(Admin)*), and run:

```powershell
wsl --install -d Ubuntu
```

This installs WSL2 and Ubuntu. **Reboot when it asks.** After the reboot an
Ubuntu window opens and asks you to choose a username and password — these are
for Linux and are unrelated to your Windows login. Write the password down; you
will need it for `sudo`.

**2. Install Docker Desktop** from
<https://www.docker.com/products/docker-desktop/> and run the installer with
**"Use WSL 2 instead of Hyper-V"** ticked.

**3. Connect Docker to Ubuntu.** Open Docker Desktop → the gear icon
(**Settings**) → **Resources** → **WSL Integration** → enable **Ubuntu** →
**Apply & Restart**.

**4. Make it start with Windows.** Settings → **General** → tick **Start Docker
Desktop when you sign in to your computer**. Without this, nothing comes back
after a reboot.

**Check:** open the **Ubuntu** app from the Start menu and run:

```bash
docker run --rm hello-world
```

You want "Hello from Docker!". If you instead get `permission denied` or
`cannot connect to the Docker daemon`, Docker Desktop is not running or the WSL
integration in step 3 was not applied.

> From here on, **every command goes in the Ubuntu window**, not PowerShell.

---

## Stage 2 — Get the code

```bash
sudo apt update && sudo apt install -y git
git clone <your-repo-url>
cd Signwithme1
```

> Keep the project inside the Linux filesystem (`~/Signwithme1`), **not** under
> `/mnt/c/...`. Docker reads files across the Windows/Linux boundary many times
> slower, and a build that takes three minutes in one place can take twenty in
> the other.

**Check:** `ls` shows `backend`, `frontend`, `docker-compose.yml`.

---

## Stage 3 — Configure

Generate three secrets:

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(48))"   # DB_PASSWORD
python3 -c "import secrets; print(secrets.token_urlsafe(48))"   # JWT_SECRET
python3 -c "import secrets; print(secrets.token_urlsafe(48))"   # PII_ENCRYPTION_KEY
```

```bash
cp .env.example .env
nano .env
```

Set these and leave the rest alone:

| Variable | Value |
|---|---|
| `DB_PASSWORD` | first generated string |
| `JWT_SECRET` | second — the app refuses to start with the example one |
| `PII_ENCRYPTION_KEY` | third, and **different** from `JWT_SECRET` |
| `SEED_ADMIN_EMAIL` | your email |
| `SEED_ADMIN_PASSWORD` | a password you choose, 8–72 characters |
| `STORAGE_BACKEND` | leave as `local` |
| `FRONTEND_BIND` | leave as `127.0.0.1` |

In `nano`: arrow keys to move, type normally, **`Ctrl+O`** then **`Enter`** to
save, **`Ctrl+X`** to quit.

> **Copy `PII_ENCRYPTION_KEY` somewhere safe right now** — a password manager,
> not this machine. It encrypts every stored SSN and EIN. Lose it and those
> values cannot be recovered, by design. Keep it separate from your backups: a
> backup holding both the ciphertext and its key is just plaintext.

```bash
./scripts/preflight.sh
```

**Check:** `0 blocking`. It catches default secrets, a `.env` that would be
committed, and insufficient disk. A swap warning is harmless on a real PC — that
check exists for 1 GB cloud instances.

---

## Stage 4 — Start it

```bash
docker compose up -d --build
```

Note: no `-f docker-compose.gcp.yml` here. That file exists to squeeze the stack
into 1 GB; your PC has room, so the plain configuration lets each service take
what it needs.

First build is 5–15 minutes. Then:

```bash
docker compose ps
curl -fsS http://127.0.0.1:8000/health
curl -fsS http://127.0.0.1:8000/ready
```

**Check:** five containers `running`, and `/ready` returns
`{"status":"ready"}` — that one proves the database migrated and is answering,
which `/health` alone does not.

Open **<http://localhost:3000>** in your Windows browser. Docker Desktop
forwards the port out of WSL automatically. Sign in with the admin email and
password you set in Stage 3.

If `/ready` fails: `docker compose logs backend | tail -40`.

---

## Stage 5 — Validate detection on your real template

**Do this before trusting the system with anything real.** It is the one part
that has never been tested against your actual document.

1. Sign in as your admin account.
2. **Templates → Upload a blank template** → the real `CFT_ CD.pdf`.
3. Wait for status `ready`. If it reports **failed** with an OCR message, the
   file is a scan — see the note at the end of this document.
4. Click **Inspect** and expand every page. For each, check:
   * every field that should be filled is listed
   * signature fields are typed `signature`, not `text_line`
   * coordinates look plausible — `x, y` inside the page, sensible `w × h`
5. Note anything missing or wrong. Expect to correct some of roughly 150 fields.

**Then fix the rules to match.** The compliance rules reference field ids the
detector was *expected* to produce — `p1_cdl`, `p2_dot_eligible`,
`p4_straight_truck` and so on:

```
backend/app/services/comparison_engine.py
  DEFAULT_CROSS_FIELD_RULES   — values that must agree across pages
  DEFAULT_FMCSA_RULES         — compliance requirements
```

**A rule naming fields that do not exist is skipped, not failed.** That stops a
mis-specified rule from failing every contract — but it also means the rule
silently does nothing. Re-point them at the real ids, then rebuild:

```bash
docker compose up -d --build backend worker
```

---

## Stage 6 — Run one contract end to end

Use a filled contract with a **deliberate mistake** — a CDL number that differs
between pages, or a blank DOT-eligibility box.

1. **Upload contract**, choose the template, upload the file.
2. Wait for the review page to finish analysing.
3. Confirm the sidebar reports your planted mistake and that approval is blocked.
4. Fix it, re-run the comparison, confirm it clears.
5. Approve → place a signature → choose the date → **Generate final contract**.
6. Download the PDF and open it.

**Check the finished document:**
* the signature sits **on** the signature line, not above or beside it
* the date reads `MM/DD/YYYY` and lands in the date field
* nothing is mirrored vertically or drawn on the wrong page

Then the **Final contract** page should show *"Integrity verified"*, and the
audit trail should list the whole lifecycle.

A signature in the wrong place means the template's box is wrong, not the
overlay — correct that field in the Template Manager and finalise a fresh
contract.

**Only after this passes is the system in service.**

---

## Stage 7 — Reach it from your phone and laptop

Skip this if you will only ever use the app on this PC.

1. Install Tailscale for Windows from <https://tailscale.com/download> and sign
   in.
2. Install it on your phone and laptop under the **same account**.
3. In PowerShell:

```powershell
tailscale serve --bg 3000
```

Tailscale then publishes `http://localhost:3000` to your private network only.
Run `tailscale serve status` to see the URL to open on your other devices.

This is better than opening a firewall port: the app stays bound to loopback,
nothing is exposed to the internet, and access is controlled by which devices
are signed into your tailnet.

**Keep the PC awake.** *Settings → System → Power* → set **Sleep** to *Never*
while plugged in. A sleeping machine is an unreachable one. Leave the screen
timeout alone — that costs nothing.

---

## Stage 8 — Backups

```bash
./scripts/backup.sh
```

Writes to `./backups/<timestamp>/`. Copy each one somewhere off this machine —
an external drive or cloud storage. A backup on the same disk as the thing it
backs up is not a backup.

To schedule it, WSL needs cron running:

```bash
sudo service cron start
crontab -e        # choose nano if asked
```

Add:

```cron
0 2 * * * cd ~/Signwithme1 && ./scripts/backup.sh >> ~/backup.log 2>&1
```

WSL only runs cron while a WSL session is open. If you want backups without
keeping the Ubuntu window open, run `./scripts/backup.sh` by hand on a schedule
you will actually remember — weekly is fine for a personal deployment.

**Test a restore once**, now, while nothing depends on it. Each backup contains
a `RESTORE.md`.

---

## Day-to-day

```bash
docker compose ps                    # what is running
docker compose logs -f backend       # follow the API log
docker compose logs --tail=100 worker
docker compose restart worker        # restart one service
docker compose down                  # stop everything (data is kept)
docker compose up -d                 # start again
```

**Updating:**

```bash
cd ~/Signwithme1
git pull
docker compose up -d --build
```

Migrations apply automatically on start. Take a backup first.

**After a Windows reboot:** Docker Desktop restarts the containers itself, as
long as you ticked "start on sign in" in Stage 1. Check with `docker compose ps`
from the Ubuntu window.

---

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `cannot connect to the Docker daemon` | Docker Desktop not running, or WSL integration off | Start Docker Desktop; re-check Settings → Resources → WSL Integration |
| `/usr/bin/env: 'bash\r': No such file or directory` | Line endings mangled on checkout | `git config --global core.autocrlf input`, then re-clone. `.gitattributes` in the repo should prevent this |
| `permission denied` on entrypoint | Exec bit lost | Rebuild: `docker compose build --no-cache backend` |
| Build is extremely slow | Project sits under `/mnt/c/` | Move it into `~/` and rebuild |
| `localhost:3000` refuses to connect | Frontend container not up | `docker compose ps`, then `docker compose logs frontend` |
| `/ready` fails, `/health` works | Migration did not run | `docker compose logs backend \| grep -i alembic` |
| Contract stuck at `parsing` | Worker down | `docker compose logs worker`; `docker compose restart worker` |
| Template `failed`, mentions OCR | The file is a scan | See below |
| Every field reads as missing | Wrong template, or a scan | Confirm the contract matches its template |
| Signature in the wrong place | Template field coordinates | Correct the field in the Template Manager |
| Login returns 429 | Throttle after repeated failures | Wait 15 minutes, or `docker compose restart backend` |
| PC restarted and nothing works | Docker Desktop did not start | Start it; check "start on sign in" |

**If your template is a scan** (no text layer), make it searchable first:

```bash
sudo apt install -y ocrmypdf
ocrmypdf input.pdf output.pdf
```

Then upload `output.pdf` instead.

---

## What this deployment is and is not

* **Only reachable while the PC is on and awake.** There is no failover.
* **Backups are yours to run.** Nothing is replicated anywhere.
* **Not reviewed by a lawyer.** The audit trail and SHA-256 hashes are solid
  evidentiary material; whether the flow satisfies ESIGN/UETA for your contracts
  is a question for counsel, not for software.
* **Single operator.** No password reset, no token revocation, login throttling
  is per process.
* **Genuinely private.** Nothing leaves the machine. No cloud provider holds
  your drivers' SSNs, and there is no bill.
