# ImmortalSerg Home Assistant Add-ons

One repository URL for my Home Assistant add-ons:

`https://github.com/immortalserg/paperless-plugin`

## Add-ons

- **FinWorkspace** — self-hosted finance manager (original source: [FinWorkspace-HA](https://github.com/immortalserg/FinWorkspace-HA)). This catalog duplicates its add-on files so it can be installed from this single repository.
- **Paperless Auto Metadata** — automatically extract beneficiary, amount, IBAN and communication from OCR receipts into Paperless-ngx using its REST API.

### Paperless configuration and web interface

Add the repository in **Home Assistant → Settings → Add-ons → Add-on Store → ⋮ → Repositories**, then install **Paperless Auto Metadata**. Start it and click **Open Web UI** to edit the connection, field IDs, regex patterns, scan interval and dry-run mode. Changes are stored in the add-on's `/data/settings.json` and persist across restarts. The same basic settings are available on the Home Assistant add-on **Configuration** tab; values saved in the web UI take precedence.

Defaults:

| Source OCR label | Paperless field |
| --- | --- |
| Bénéficiaire | Correspondent (create if missing) |
| Montant | Custom field ID 2 (monetary, `EUR190.30`) |
| IBAN | Custom field ID 3 (text) |
| Communication | Custom field ID 4 (text) |
| Communication | Title: `оплата ` + value |

- `dry_run` is **true** on first install: test a document before permitting any changes.
- The API token is never displayed after saving it in the web UI. Do not commit tokens to GitHub.
- New documents are checked every 30 seconds by default. Only up to 100 newest documents are scanned per poll (editable).
- Existing custom fields are preserved; unmatched documents are not changed.
- Records are cached in `/data/processed.json`; OCR changes and configuration changes trigger reprocessing.
- Built-in web interface uses **Home Assistant ingress** (no externally exposed web port).
- This processes only documents matching all four expected bank labels. It does **not** require modifying the Paperless-ngx container.

### Important for existing FinWorkspace users

Home Assistant derives add-on identity from the **repository URL**, not merely the add-on `slug`. FinWorkspace from this catalog will appear as a **different add-on** from the existing `FinWorkspace-HA` installation. **Do not uninstall or replace the existing FinWorkspace add-on without a database backup and migration plan.** You may keep the old add-on installed while using this common catalog for new installations.

## Development

Run `python3 -m unittest discover -s tests -v` from the repository root.