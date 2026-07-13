// Anonymous per-browser identity: no login, no password. A random ID is
// generated once and stored in this browser; every API request sends it as
// X-FFL-UID, which the server uses directly as the storage namespace for
// drafts/leagues/trades. Copy the ID into another browser/device to share
// the same data there — that's the only "account recovery" mechanism, and
// it's intentional (no server-side account database to keep in sync).
const KEY = "ffl_uid";

function randomId() {
  if (window.crypto?.randomUUID) return window.crypto.randomUUID().replace(/-/g, "");
  // Fallback for older browsers.
  return Array.from({ length: 32 }, () => Math.floor(Math.random() * 16).toString(16)).join("");
}

export function getDeviceId() {
  let id = localStorage.getItem(KEY);
  if (!id) {
    id = randomId();
    localStorage.setItem(KEY, id);
  }
  return id;
}

export function setDeviceId(id) {
  const clean = (id || "").trim();
  if (!/^[A-Za-z0-9_-]{8,64}$/.test(clean)) {
    throw new Error("That doesn't look like a valid ID (8–64 letters/numbers).");
  }
  localStorage.setItem(KEY, clean);
  return clean;
}
