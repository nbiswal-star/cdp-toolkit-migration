# WordPress side

`cdp-activity/` is a normal WordPress plugin. IF's website manager must approve it before it
goes on the IF website. It adds:

- **Toolkit Activities** (post type `cdp_activity`, REST base `/wp-json/wp/v2/cdp-activities`).
  Public URL base `toolkit/activity/`, set with `CDP_ACTIVITY_SLUG` in `wp-config.php` before
  activation. No archive page: IF builds its own Toolkit listing page (for example with FacetWP).
- Filters **Modules**, **Levels**, **Tags (formats)** (taxonomies `cdp_module`, `cdp_level`,
  `cdp_format`). They are not public URLs. The plugin creates the current terms on activation;
  only editors and administrators can add or change terms.
- An **Activity details** box in the editor: Number, Time (minutes), Submitted by, PDF link,
  Image credit. The migration also stores the old Toolkit address and ID. These fields are
  visible over the REST API only to people who can edit activities.
- A **CDP Drafter** role for the migration account: it can create and edit its own unpublished
  activities and upload files. It **cannot publish**, cannot edit other people's activities,
  and cannot change filter terms.
- Embedded slides and video: iframes are kept only from `docs.google.com`, `www.youtube.com`,
  `www.youtube-nocookie.com`, and `player.vimeo.com` (change with `CDP_EMBED_HOSTS`, and the
  same list in `src/cdp_migration/ricos.py`). Embeds from other hosts are reported for review
  before any draft is made, and the plugin removes them if they are entered by hand.
- Activity details are kept in **Revisions** with the title and text (WordPress 6.4 or later).

Display: build one Breakdance (or theme) single template for Toolkit Activities that shows the
post body and the Activity details fields. Enable the post type in Breakdance first. FacetWP:
sort by the Number field as text gives 1.10 before 1.2, so sort by title or add a numeric sort
key. Re-index FacetWP after activities are published (drafts are not indexed).

## Install on a site

1. Copy the `cdp-activity` folder to `wp-content/plugins/` and activate **CDP Toolkit Activities**.
2. Go to **Settings > Permalinks** and click **Save** (activation also does this).
3. Create a user with the role **CDP Drafter**.
4. As that user: **Users > Profile > Application Passwords**, add one named `cdp`.
   Keep it in a password manager. Revoke it on the same screen after the migration.
5. On the migration computer:
   ```bash
   export CDP_WP_URL=https://staging.example.org CDP_WP_USER=drafter CDP_WP_APP_PASSWORD='xxxx xxxx xxxx'
   cdp --target wordpress migrate --limit 5
   ```

Staff who add or publish activities need the **Editor** or **Administrator** role. Authors and
Contributors cannot see Toolkit Activities.

**Remove:** first revoke the `cdp` application password and delete the drafter user (assign its
content to an editor). Then deactivate and delete the plugin in **Plugins**. Deleting runs `uninstall.php`,
which removes the CDP Drafter role, the added capabilities, and the plugin setting. Toolkit
Activity posts and terms are kept because they are IF content.

## Local practice site

### With Docker

```bash
cd wordpress
docker compose up -d
./setup-local.sh          # installs WordPress, activates the plugin, creates the drafter, prints its application password
```

Log in at http://localhost:8899/wp-admin as `admin` with password `change-me-now` (practice site
only; set another with `ADMIN_PASSWORD='...' ./setup-local.sh` on the first install). Then run the
migration as shown in the main README, under "Try it on your computer". To remove the site and its
data, run `docker compose down -v`.

### Without Docker (PHP 8.1+ with pdo_sqlite)

This is how `tests/test_wordpress_live.py` was run (output in `eval/results/wordpress_integration.txt`):

1. Unpack WordPress into a folder, add the
   [SQLite Database Integration](https://github.com/WordPress/sqlite-database-integration) plugin,
   and copy its `db.copy` to `wp-content/db.php` (replace the two placeholders with real paths).
2. Copy `cdp-activity/` into `wp-content/plugins/`.
3. Add `define('WP_ENVIRONMENT_TYPE', 'local');` to `wp-config.php` (allows Application Passwords over plain HTTP).
4. Copy `router.php` from this folder into the WordPress folder. There, install with WP-CLI and start PHP's server:
   ```bash
   wp core install --url=http://127.0.0.1:8899 --title=CDP --admin_user=admin --admin_password=change-me --admin_email=you@example.org --skip-email
   wp plugin activate cdp-activity
   wp rewrite structure '/%postname%/'
   wp user create drafter drafter@example.org --role=cdp_drafter --user_pass=change-me
   wp user application-password create drafter cdp --porcelain
   php -S 127.0.0.1:8899 router.php
   ```
5. Run the live tests:
   ```bash
   CDP_WP_URL=http://127.0.0.1:8899 CDP_WP_USER=drafter CDP_WP_APP_PASSWORD='...' python -m pytest tests/test_wordpress_live.py
   ```

## Old link forwarding

`cdp migrate` writes `out/redirects.csv` (columns `source,target,regex,code`), from each old
Toolkit address to the activity's planned permalink. After IF publishes the activities, run
`cdp --target wordpress redirects` to rebuild the file from the live addresses (so a changed
slug is picked up), then import it with **Tools > Redirection > Import/Export**, in a group that
matches the old domain only.
This works once IF keeps `collaborativediscussionproject.com`, adds it to the website host
with SSL, and points its DNS there. If Wix registered the domain, it may need to be
transferred first.
