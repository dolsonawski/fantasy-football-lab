# Sharing & installing Fantasy Football Lab

The app is a Progressive Web App (PWA): once it's reachable over the network,
anyone can open the link on desktop or phone and **Add to Home Screen** to get
an app icon that launches full-screen.

## 1. Use it on your phone right now (same Wi-Fi)

No hosting needed for a quick test on your own devices.

1. Start the server bound to your whole network:
   ```
   .venv\Scripts\python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
   ```
2. Find this machine's LAN IP (Windows): `ipconfig` → the "IPv4 Address"
   (looks like `192.168.x.x`).
3. On your phone (same Wi-Fi), open `http://192.168.x.x:8000`.
4. iPhone Safari: Share → **Add to Home Screen**. Android Chrome: ⋮ →
   **Install app / Add to Home screen**.

Note: on a plain-HTTP LAN address the service worker/offline cache is limited,
but the app and add-to-home-screen still work. Full PWA behavior needs HTTPS,
which you get automatically with any host below.

## 2. Put it on the internet (shareable link)

The app stores accounts, drafts, leagues, and rankings as files under
`FFL_DATA_DIR`. On a host, point that at a **persistent disk** so data survives
restarts, and set `FFL_SECURE_COOKIES=1` (all hosts below serve HTTPS).

### Render (easiest, free tier)
1. Push this folder to a GitHub repo.
2. Render → **New → Blueprint** → select the repo. It reads `render.yaml`
   (Python build, HTTPS, a 1 GB persistent disk at `/var/data`).
3. Deploy. You get a `https://<name>.onrender.com` link to share.

### Docker (Fly.io, Railway, a VPS, etc.)
```
docker build -t ff-lab .
docker run -p 8000:8000 -v ff-lab-data:/data ff-lab
```
The image sets `FFL_DATA_DIR=/data` and `FFL_SECURE_COOKIES=1`; mount a volume
at `/data` (as shown) to persist accounts and drafts. Put it behind an HTTPS
proxy/load balancer, or use a platform that terminates TLS for you.

## 3. Everyone signs in

The landing page is a sign-in / create-profile screen. Each person makes their
own profile; their mock drafts, imported leagues, and trade analysis are saved
to that account. Share the link, they sign up, done.

## Environment variables
| Var | Default | Purpose |
| --- | --- | --- |
| `FFL_DATA_DIR` | `app/data` | Where all persisted data + caches live. Point at a persistent disk when hosted. |
| `FFL_SECURE_COOKIES` | off | Set to `1` behind HTTPS so the session cookie is marked Secure. |
| `PORT` | `8000` | Port to bind (most hosts set this automatically). |
