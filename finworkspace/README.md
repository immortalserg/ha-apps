# FinWorkspace for Home Assistant

FinWorkspace add-on is maintained in the [ImmortalSerg Home Assistant Apps](https://github.com/immortalserg/ha-apps) repository.

The actual finance application is developed at [FinWorkspace](https://github.com/immortalserg/FinWorkspace). This add-on wraps its published image with a Home Assistant-compatible entrypoint.

## Installation

Add `https://github.com/immortalserg/ha-apps` in **Home Assistant → Settings → Apps → App Store → Repositories**, then install **FinWorkspace**. It is available at `http://HOME_ASSISTANT_IP:8223`.

On a new installation, configure `initial_admin_email`, `initial_admin_name` and `initial_admin_password` before starting. Clear them after creating the first admin account.

Most application settings are managed inside FinWorkspace under **Admin → Application Settings**.

## Data and upgrades

The app uses persistent Home Assistant `/data`, including `finance.db`, `uploads/`, `documents/`, `logs/`, `.secret_key`, `.notification_encryption_key`, `app-settings.json`, `app-secrets.json`, `app-settings.key` and `secrets/enablebanking.pem`. Back up the entire `/data` directory, especially keys required to decrypt existing settings.

**Important for existing FinWorkspace-HA users:** Moving between Home Assistant repositories can create a new add-on instance with a separate `/data` volume, even when both use `slug: finworkspace`. Back up the original add-on first. Keep the original installed until the destination's data and startup are verified. A fresh destination installation will not import the old database automatically.

## Releases

Only this repository publishes new Home Assistant wrapper images after migration. The app image stays at `ghcr.io/immortalserg/finworkspace-ha`. To publish an add-on version, update `finworkspace/config.yaml`, the Dockerfile's version label and application image reference as needed, then push a `finworkspace-vX.Y.Z` tag. A manual workflow dispatch for the matching version is also supported.

The application image `ghcr.io/immortalserg/finworkspace` remains maintained independently of this add-on catalog.
