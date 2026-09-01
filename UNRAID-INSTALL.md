# The Shelf — Unraid install

## Install (Community Applications, one-click)

The image is published to **GHCR** by Actions on every push
(`ghcr.io/adorablebrillo/the-shelf:latest`), so nothing needs building on the server.

1. **Unraid → Apps → Settings → Custom repositories** → Add
   `https://github.com/adorablebrillo/the-shelf`
2. **Apps → search "The Shelf" → Install**
3. Check the two paths default correctly
   (`/mnt/user/appdata/the-shelf/config` + `/data`, port **8787**) → **Apply**
4. Open **http://[unraid-ip]:8787** → **shelf settings** → paste your OpenRouter
   key → pick the model (prices shown) → **save**

The image is built automatically when the repo updates (first push → build takes
~2 min; if you install before it finishes, click **Update container** afterwards
or just re-Apply the template).

> **Private repo instead?** Flip it to private in GitHub and add a fine-grained
> token in CA (Apps → Settings → Github integration). The template reference stays the same.

## Notes

- **Schedule**: the container runs the pipeline the 1st of every month at **09:00**
  (container TZ — set `Europe/Madrid` in the template, already there). Also a
  manual "run monthly pipeline now" button in Settings.
- **Where things live**:
  - `/config` → `settings.json` (your key + model) and `logs/monthly.log`
  - `/app/pipeline/data` → candidates, filtered lists, curated month JSON (history)
- **Reset**: delete the two appdata folders and re-add the key — clean slate.
