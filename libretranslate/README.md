# LibreTranslate — Home Assistant App

Self-hosted LibreTranslate translation server, running locally on Home Assistant OS.
Uses the official LibreTranslate container as the base image and stores language models
in the persistent Home Assistant app `/data` volume.

## Install

Add `https://github.com/immortalserg/ha-apps` in Home Assistant → Settings → Apps
→ App Store → Repositories. Refresh the store and install **LibreTranslate**.

Select languages, save, then start the app. The first startup downloads models and
may take several minutes. Internet access is required to download models; subsequent
translation runs locally.

Open the web interface using **Open Web UI**, or visit
`http://HOME_ASSISTANT_IP:5000`.

## Connect Paperless Auto Metadata

In Paperless Auto Metadata → Open Web UI → Перевод OCR, enter:

`http://HOME_ASSISTANT_IP:5000`

Select the destination Paperless custom text field, choose languages and save.
The LibreTranslate API endpoint is `POST /translate`; no API key is needed
on this private-LAN configuration.

## Options

- `languages`: comma-separated ISO language codes, e.g. `en,fr,de,ru`.
- `char_limit`: maximum characters per translation request.
- `req_limit`: requests per minute per client.
- `threads`: worker threads.
- `update_models`: refresh language models at next startup.

## Security and limitations

**Do not expose port 5000 directly to the internet.** The API is unauthenticated.
Restrict the port to your private LAN, VPN or firewall. App port mapping may expose
it on all host interfaces unless firewall rules prevent access.

Only amd64 and aarch64 are declared. The upstream image is large, model downloads
require space and RAM, and the Home Assistant host must have internet access
for initial model installation.

This is a community Home Assistant App, not an official LibreTranslate package.
