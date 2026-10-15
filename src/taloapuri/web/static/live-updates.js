// Elävät päivitykset: kysyy palvelimelta 30 sekunnin välein (vain kun välilehti on näkyvissä)
// lukemattomien määrät ja päivittää yläpalkin laskurit. Kun uutta tapahtuu, näytetään ilmoitus
// "Uusia tapahtumia – Näytä". Ilman JavaScriptiä kaikki näkyy, kun sivu ladataan.
(function () {
  "use strict";
  const body = document.body;
  const url = body && body.dataset.statusUrl;
  if (!url || !window.fetch) return;

  const NORMAL = 30000;
  const AFTER_ERROR = 120000;
  const toast = document.querySelector(".live-toast");
  let version = null;
  let timer = null;

  // Selaimen välilehden otsikkoon lukemattomien määrä, esim. "(2) Etusivu – Taloapuri".
  const baseTitle = document.title.replace(/^\(\d+\)\s*/, "");
  function setTabTitle(total) {
    document.title = total > 0 ? "(" + total + ") " + baseTitle : baseTitle;
  }

  function setBadge(name, count) {
    const badge = document.querySelector('[data-live="' + name + '"]');
    if (!badge) return;
    badge.querySelector("[data-live-count]").textContent = String(count);
    badge.hidden = count === 0;
  }

  function userIsTyping() {
    const el = document.activeElement;
    return el && (el.tagName === "TEXTAREA" || (el.tagName === "INPUT" && el.type !== "submit"));
  }

  function showToast(data) {
    if (!toast) return;
    const parts = [];
    if (data.unread_cases) parts.push(data.unread_cases + " lukematonta asiaa");
    if (data.unread_messages) parts.push(data.unread_messages + " lukematonta viestiä");
    const message = "Uusia tapahtumia" + (parts.length ? " (" + parts.join(", ") + ")" : "") + ".";
    toast.querySelector("[data-live-message]").textContent = message;
    toast.hidden = false;
  }

  function schedule(delay) {
    window.clearTimeout(timer);
    timer = window.setTimeout(poll, delay);
  }

  async function poll() {
    if (document.visibilityState !== "visible") return; // jatketaan, kun välilehti palaa näkyviin
    try {
      const response = await fetch(url, { credentials: "same-origin", headers: { Accept: "application/json" } });
      if (!response.ok) throw new Error(String(response.status));
      const data = await response.json();
      setBadge("messages", data.unread_messages);
      setTabTitle(data.unread_cases + data.unread_messages);
      if (version !== null && data.feed_version && data.feed_version !== version && !userIsTyping()) {
        showToast(data);
      }
      if (version === null || !userIsTyping()) version = data.feed_version;
      schedule(NORMAL);
    } catch (e) {
      schedule(AFTER_ERROR);
    }
  }

  document.addEventListener("visibilitychange", function () {
    if (document.visibilityState === "visible") poll();
  });
  poll();
})();
