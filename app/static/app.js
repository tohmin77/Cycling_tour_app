(function () {
  const box = document.getElementById("content");
  const active = document.querySelector(".chip.on");
  if (active) active.scrollIntoView({inline: "center", block: "nearest"});
  if (!box) return;

  function load() {
    box.innerHTML = '<div class="loading"><div class="spinner"></div><p>Loading…</p>' +
      '<p class="muted">The first load of a day can take a minute or two. Later visits are instant.</p></div>';
    fetch(box.dataset.src)
      .then(r => { if (!r.ok) throw new Error(r.status); return r.text(); })
      .then(html => { box.innerHTML = html; document.dispatchEvent(new Event("content-loaded")); })
      .catch(() => {
        box.innerHTML = '<p class="warn">Could not load this section.</p><button type="button" id="retry">Retry</button>';
        document.getElementById("retry").addEventListener("click", load);
      });
  }
  load();
})();
