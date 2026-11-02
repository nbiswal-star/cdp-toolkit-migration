#!/usr/bin/env bash
# Installs the Docker practice site and prints the drafter's application password.
set -euo pipefail
cd "$(dirname "$0")"
wp() { docker compose run --rm cli wp "$@"; }
for _ in $(seq 1 30); do wp core is-installed >/dev/null 2>&1 && break; wp db check >/dev/null 2>&1 && break; sleep 2; done
wp core is-installed >/dev/null 2>&1 || wp core install --url=http://localhost:8899 --title="CDP practice" \
  --admin_user=admin --admin_password="${ADMIN_PASSWORD:-change-me-now}" --admin_email=admin@example.org --skip-email
wp plugin activate cdp-activity
wp rewrite structure '/%postname%/'
wp user get drafter >/dev/null 2>&1 || wp user create drafter drafter@example.org --role=cdp_drafter --user_pass="$(openssl rand -hex 12)"
echo "CDP_WP_URL=http://localhost:8899"
echo "CDP_WP_USER=drafter"
echo "CDP_WP_APP_PASSWORD=$(wp user application-password create drafter cdp --porcelain)"
