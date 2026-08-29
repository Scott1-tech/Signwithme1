# Running it in the browser — GitHub Codespaces

For when you cannot install anything and have no terminal of your own. A
codespace is a Linux machine that GitHub runs for you, with a terminal and an
editor inside a browser tab. Nothing is installed on your computer, no card is
needed, and the free allowance covers this comfortably.

**Read the honest limits at the end before relying on it.** This is a good way
to *use* the app; it is not a 24/7 server.

---

## Start it

**1.** Open your repository on <https://github.com>.

**2.** Click the green **Code** button → the **Codespaces** tab → **Create
codespace on claude/structure-website-build-i08okj**.

A browser editor opens and spends 2–3 minutes preparing the machine. When it
finishes you will see a terminal at the bottom and a message ending in
`Ready. Start the app with: ...`.

**3.** In that terminal, type:

```bash
docker compose up -d --build
```

First build takes 5–15 minutes. It is finished when the prompt returns.

**4.** Check it came up:

```bash
docker compose ps
curl -fsS http://127.0.0.1:8000/ready
```

Five containers `running`, and `{"status":"ready"}` — that second one proves the
database migrated, which the container list alone does not tell you.

**5.** Click the **PORTS** tab next to the terminal. Find the row for port
**3000** ("Contract Signing UI") and click the **globe** icon. The app opens in
a new tab.

**6.** Sign in using the details in `CREDENTIALS.txt` — click it in the file list
on the left. A password was generated for you when the codespace was created.

---

## Who can reach it

By default a forwarded port is **private**: only your GitHub account can open
that URL, even though it looks like a public web address. Anyone else gets a
sign-in page.

Leave it that way. In the PORTS tab, the **Visibility** column should read
`Private`. Do not change it to Public — that would put contracts containing
SSNs on an address anyone could reach.

To use the app from your phone, sign in to GitHub on the phone with the same
account and open the same URL.

---

## Stopping and resuming

A codespace **stops itself after 30 minutes of inactivity**. Nothing is lost —
the disk persists — but the containers stop with it.

To come back: **Code → Codespaces → click your codespace**. Then in the
terminal:

```bash
docker compose up -d
```

No `--build` this time; the images are already there, so it starts in under a
minute.

Stopping it deliberately when you finish is worth doing — it conserves your
monthly allowance. Use **Codespaces → ⋯ → Stop codespace**.

---

## Validate it against your real template

**Do this before trusting the system with anything real.** It is the one part
that has never been tested against your actual document.

1. Sign in as the admin.
2. **Templates → Upload a blank template** → your real `CFT_ CD.pdf`.
3. Wait for status `ready`. If it reports **failed** with an OCR message, the
   file is a scan — make it searchable first:
   ```bash
   sudo apt update && sudo apt install -y ocrmypdf
   ocrmypdf input.pdf output.pdf
   ```
   (Drag the PDF into the file list on the left to upload it into the codespace.)
4. Click **Inspect** and expand every page. Check that every field that should be
   filled is listed, that signature fields are typed `signature`, and that the
   coordinates look plausible.
5. Expect to correct some of roughly 150 fields.

Then re-point the compliance rules at the field ids the detector actually
produced:

```
backend/app/services/comparison_engine.py
  DEFAULT_CROSS_FIELD_RULES   — values that must agree across pages
  DEFAULT_FMCSA_RULES         — compliance requirements
```

**A rule naming fields that do not exist is skipped, not failed** — it silently
does nothing rather than failing every contract. Edit them in the browser
editor, then:

```bash
docker compose up -d --build backend worker
```

Then run one contract end to end, using a copy with a deliberate mistake in it
(a CDL that differs between pages, or a blank DOT-eligibility box). Confirm the
sidebar catches it, fix it, approve, sign, and check the finished PDF: signature
**on** the line, date reading `MM/DD/YYYY`, nothing mirrored.

---

## Getting your documents out

**Do this every session.** Right-click any file in the editor's file list and
choose **Download** to save it to your computer.

Run a backup before you finish:

```bash
./scripts/backup.sh
```

Then download the folder it names under `backups/`. Also download `.env` — or at
least copy `PII_ENCRYPTION_KEY` out of it — and keep it somewhere separate from
the backups. That key decrypts the stored SSNs; a backup stored alongside its own
key is just plaintext.

---

## The honest limits

Read these before deciding this is where the app lives.

**It is not always on.** The codespace stops after 30 minutes idle and takes a
minute to resume. Nobody can reach the app while it is stopped. Fine if you
process contracts in sittings; wrong if you need a link that always works.

**There is a monthly allowance.** GitHub's free tier gives personal accounts a
fixed number of core-hours and some storage each month — roughly 60 hours of use
on the smallest machine, though the exact figures change, so check your own
billing page. Past that, codespaces stop until the month resets or you add
billing.

**Inactive codespaces are deleted.** GitHub removes one that has gone unused for
30 days by default. Everything inside goes with it — database, stored PDFs and
`.env`. This is the reason the backup step above is not optional.

**Your data sits on GitHub's infrastructure.** The contracts, and the SSNs in
them, live on a machine GitHub operates. The port is private to your account and
the sensitive fields are encrypted at rest, but it is still a third party
holding the data. For your own business records that may be perfectly
acceptable — it is your call to make knowingly.

**When you outgrow it**, the same repository runs unchanged on a computer you
own ([`docs/DEPLOYMENT-WINDOWS.md`](DEPLOYMENT-WINDOWS.md)) or on a small cloud
instance ([`docs/DEPLOYMENT.md`](DEPLOYMENT.md)). Nothing you do here is wasted:
the corrected template and the rule changes are just files in the repository.
Commit them and they follow you.

---

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| Build fails, out of disk | 32 GB filled by images | `docker system prune -af` and rebuild |
| Port 3000 not in PORTS tab | Containers not up | `docker compose ps`, then `docker compose logs frontend` |
| Port opens a GitHub sign-in page | Working as designed | Sign in with the same account |
| `/ready` fails, `/health` works | Migration did not run | `docker compose logs backend \| grep -i alembic` |
| Contract stuck at `parsing` | Worker down | `docker compose restart worker` |
| Template `failed`, mentions OCR | The file is a scan | Run `ocrmypdf` as above |
| Signature in the wrong place | Template field coordinates | Correct that field in the Template Manager |
| Everything gone after weeks away | Codespace was deleted for inactivity | Recreate it, restore from your downloaded backup |
