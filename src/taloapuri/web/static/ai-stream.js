// Tekoälyn vastauksen striimaus ja latausanimaatio.
//
// Lomake, jolla on data-ai-stream="<osoite>", lähetetään fetchillä ja vastaus (Server-Sent
// Events) näytetään sitä mukaa kuin se syntyy. Lopuksi siirrytään tallennettuun vastaukseen,
// jossa lähdeviitteet on tarkistettu. Ilman JavaScriptiä lomake toimii tavallisesti.
(function () {
  "use strict";
  if (!window.fetch || !window.ReadableStream || !window.TextDecoder) return;

  function parseEvents(buffer) {
    const events = [];
    let index;
    while ((index = buffer.indexOf("\n\n")) !== -1) {
      const chunk = buffer.slice(0, index);
      buffer = buffer.slice(index + 2);
      let name = "message";
      let data = "";
      chunk.split("\n").forEach(function (line) {
        if (line.startsWith("event:")) name = line.slice(6).trim();
        else if (line.startsWith("data:")) data += line.slice(5).trim();
      });
      try {
        events.push({ name: name, data: data ? JSON.parse(data) : {} });
      } catch (e) {
        /* ohitetaan rikkinäinen tapahtuma */
      }
    }
    return { events: events, rest: buffer };
  }

  document.addEventListener("submit", async function (event) {
    const form = event.target.closest("form[data-ai-stream]");
    if (!form) return;
    event.preventDefault();

    const panel = document.getElementById(form.dataset.aiPanel);
    const status = panel.querySelector(".ai-status");
    const output = panel.querySelector(".ai-stream");
    const errorBox = panel.querySelector(".ai-error");
    const elapsed = panel.querySelector(".ai-elapsed");
    const target = form.dataset.aiTarget ? document.querySelector(form.dataset.aiTarget) : null;
    const buttons = form.querySelectorAll("button, input[type=submit]");

    const body = new FormData(form);
    const question = form.querySelector("textarea[name=question]");
    if (question && !question.value.trim()) {
      form.removeAttribute("data-ai-stream"); // anna palvelimen näyttää selkokielinen virhe
      form.submit();
      return;
    }

    buttons.forEach(function (b) { b.disabled = true; });
    panel.hidden = false;
    panel.setAttribute("aria-busy", "true");
    panel.classList.add("is-working");
    errorBox.hidden = true;
    output.textContent = "";
    if (target) target.value = "";
    status.textContent = "Aloitetaan…";
    panel.scrollIntoView({ block: "nearest", behavior: "smooth" });

    const started = Date.now();
    const timer = window.setInterval(function () {
      elapsed.textContent = Math.round((Date.now() - started) / 1000) + " s";
    }, 1000);

    function finish() {
      window.clearInterval(timer);
      panel.classList.remove("is-working");
      panel.removeAttribute("aria-busy");
    }

    function fail(message) {
      finish();
      errorBox.textContent = message;
      errorBox.hidden = false;
      status.textContent = "Keskeytyi.";
      buttons.forEach(function (b) { b.disabled = false; });
    }

    try {
      const response = await fetch(form.dataset.aiStream, {
        method: "POST",
        body: body,
        credentials: "same-origin",
        headers: { Accept: "text/event-stream" },
      });
      if (!response.ok || !response.body) {
        fail("Toiminto ei onnistunut (" + response.status + "). Lataa sivu uudelleen ja yritä uudelleen.");
        return;
      }
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      for (;;) {
        const chunk = await reader.read();
        if (chunk.done) break;
        buffer += decoder.decode(chunk.value, { stream: true });
        const parsed = parseEvents(buffer);
        buffer = parsed.rest;
        for (const ev of parsed.events) {
          if (ev.name === "status") {
            status.textContent = ev.data.text;
          } else if (ev.name === "delta") {
            panel.classList.add("is-writing");
            output.textContent += ev.data.text;
            if (target) {
              target.value += ev.data.text;
              target.scrollTop = target.scrollHeight;
            }
          } else if (ev.name === "error") {
            fail(ev.data.message);
            return;
          } else if (ev.name === "done") {
            finish();
            status.textContent = "Valmis. Avataan vastaus lähdeviitteineen…";
            window.location.assign(ev.data.redirect);
            return;
          }
        }
      }
      fail("Yhteys katkesi ennen kuin vastaus valmistui. Yritä uudelleen.");
    } catch (e) {
      fail("Yhteys katkesi. Tarkista verkkoyhteys ja yritä uudelleen.");
    }
  });
})();
