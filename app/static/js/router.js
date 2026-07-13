const routes = {};

export function registerRoute(name, renderFn) {
  routes[name] = renderFn;
}

function currentRouteName() {
  const hash = window.location.hash.replace(/^#\/?/, "");
  return hash.split("?")[0] || "rankings";
}

async function renderCurrent() {
  const name = currentRouteName();
  const container = document.getElementById("app");

  document.querySelectorAll("nav.tabs a").forEach((a) => {
    a.classList.toggle("active", a.dataset.route === name);
  });

  const renderFn = routes[name];
  if (!renderFn) {
    container.innerHTML = `<div class="empty-state">Page not found.</div>`;
    return;
  }

  container.innerHTML = `<div class="loading">Loading&hellip;</div>`;
  try {
    await renderFn(container);
  } catch (err) {
    console.error(err);
    container.innerHTML = `<div class="error-state">Something went wrong: ${err.message || err}</div>`;
  }
}

export function startRouter() {
  window.addEventListener("hashchange", renderCurrent);
  if (!window.location.hash) {
    window.location.hash = "#/rankings";
  }
  renderCurrent();
}
