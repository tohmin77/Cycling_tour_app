(function () {
  const HORIZON = 15;
  const API = "https://api.open-meteo.com/v1/forecast";
  const iso = d => d.getFullYear() + "-" + String(d.getMonth() + 1).padStart(2, "0") + "-" + String(d.getDate()).padStart(2, "0");

  // Mirrors attire_summary() in app/advice.py
  function attireSummary(tmin, tmax, prob, mm, wind) {
    const parts = tmax >= 28 ? ["Light short sleeves", "bib shorts"]
      : tmax >= 20 ? ["Short sleeves", "bib shorts"]
      : tmax >= 12 ? ["Long sleeves or arm warmers", "knee warmers", "light gloves"]
      : tmax >= 5 ? ["Thermal jersey", "tights", "warm gloves"]
      : ["Winter jacket", "tights", "winter gloves"];
    if (tmin < 8 && tmax >= 12 && tmax < 20) parts.push("thermal base layer for the cold start");
    if (tmin < 12 && tmax >= 20) parts.push("arm warmers for the start");
    if ((prob || 0) >= 50 || mm >= 2) parts.push("waterproof jacket");
    else if ((prob || 0) >= 25) parts.push("rain jacket in the bag");
    if (wind >= 30) parts.push("windproof layer");
    return parts.join(", ");
  }

  function refresh(card, button, status) {
    const rows = [...card.querySelectorAll("tr[data-date]")];
    const limit = new Date(); limit.setDate(limit.getDate() + HORIZON);
    const today = iso(new Date()), last = iso(limit);
    const dates = rows.map(r => r.dataset.date).filter(d => d >= today && d <= last);
    if (!dates.length) { status.textContent = "No tour day is within the 15-day forecast yet."; return; }
    button.disabled = true; status.textContent = "Updating…";
    const q = new URLSearchParams({
      latitude: card.dataset.lat, longitude: card.dataset.lng, timezone: "auto",
      hourly: "temperature_2m,precipitation_probability,precipitation,wind_speed_10m",
      start_date: dates[0], end_date: dates[dates.length - 1],
    });
    fetch(API + "?" + q)
      .then(r => { if (!r.ok) throw new Error(r.status); return r.json(); })
      .then(j => {
        const h = j.hourly, days = {};
        h.time.forEach((stamp, i) => {
          const hour = +stamp.slice(11, 13);
          if (hour < 6 || hour > 22 || h.temperature_2m[i] == null) return;
          const x = days[stamp.slice(0, 10)] = days[stamp.slice(0, 10)] || {t: [], p: [], mm: 0, w: 0};
          x.t.push(h.temperature_2m[i]);
          if (h.precipitation_probability[i] != null) x.p.push(h.precipitation_probability[i]);
          x.mm += h.precipitation[i] || 0;
          x.w = Math.max(x.w, h.wind_speed_10m[i] || 0);
        });
        Object.keys(days).forEach(day => {
          const row = card.querySelector('tr[data-date="' + day + '"]'), x = days[day];
          if (!row) return;
          const p = x.p.length ? Math.max(...x.p) : null;
          row.querySelector(".t").textContent = Math.round(Math.min(...x.t)) + "–" + Math.round(Math.max(...x.t)) + "°C";
          row.querySelector(".r").textContent = (p == null ? "" : Math.round(p) + "% · ") + x.mm.toFixed(1) + " mm";
          row.querySelector(".w").textContent = Math.round(x.w) + " km/h";
          row.querySelector(".a").textContent = attireSummary(Math.min(...x.t), Math.max(...x.t), p, x.mm, x.w);
          row.querySelector(".src").textContent = "forecast";
          row.classList.remove("typical"); row.classList.add("updated");
        });
        status.textContent = "Updated " + new Date().toLocaleTimeString([], {hour: "2-digit", minute: "2-digit"});
      })
      .catch(() => { status.textContent = "Could not reach the forecast service. Try again."; })
      .finally(() => { button.disabled = false; });
  }

  function init() {
    const card = document.getElementById("daily");
    if (!card || card.dataset.bound) return;
    card.dataset.bound = "1";
    const button = document.getElementById("refresh-wx"), status = document.getElementById("wx-status");
    button.addEventListener("click", () => refresh(card, button, status));
    refresh(card, button, status);
  }
  document.addEventListener("content-loaded", init);
  init();
})();
