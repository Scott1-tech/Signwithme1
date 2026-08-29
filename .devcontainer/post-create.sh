#!/usr/bin/env bash
# Runs once, when the codespace is first created.
set -euo pipefail

cd "$(dirname "$0")/.."

if [ -f .env ]; then
  echo "==> .env already exists; leaving it untouched."
else
  echo "==> Generating .env with fresh secrets..."
  cp .env.example .env

  gen() { python3 -c "import secrets; print(secrets.token_urlsafe(48))"; }
  # A generated password is set for the admin too: a default one in a
  # browser-reachable deployment is an open door.
  ADMIN_PASSWORD="$(python3 -c "import secrets; print(secrets.token_urlsafe(12))")"

  python3 - "$(gen)" "$(gen)" "$(gen)" "${ADMIN_PASSWORD}" <<'PY'
import pathlib, re, sys

db, jwt, pii, admin = sys.argv[1:5]
path = pathlib.Path(".env")
text = path.read_text()
for key, value in (
    ("DB_PASSWORD", db),
    ("JWT_SECRET", jwt),
    ("PII_ENCRYPTION_KEY", pii),
    ("SEED_ADMIN_PASSWORD", admin),
):
    text = re.sub(rf"^{key}=.*$", f"{key}={value}", text, flags=re.M)
path.write_text(text)
PY

  cat > CREDENTIALS.txt <<TXT
Your sign-in details
====================

  Email:    $(grep '^SEED_ADMIN_EMAIL=' .env | cut -d= -f2-)
  Password: ${ADMIN_PASSWORD}

Change SEED_ADMIN_EMAIL in .env before first start if you want a different one.

IMPORTANT
---------
.env also holds PII_ENCRYPTION_KEY, which encrypts every stored SSN and EIN.
Copy it somewhere outside this codespace (a password manager). If the codespace
is deleted, that key goes with it and any backup you kept becomes unreadable.

This file is git-ignored and will not be committed.
TXT
  echo "==> Wrote CREDENTIALS.txt"
fi

cat <<'NEXT'

============================================================
  Ready. Start the app with:

      docker compose up -d --build

  First build takes 5-15 minutes. When it finishes, open the
  PORTS tab, find port 3000, and click the globe icon.

  Sign in with the details in CREDENTIALS.txt
============================================================

NEXT
