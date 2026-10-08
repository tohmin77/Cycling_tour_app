document.addEventListener("content-loaded", function () {
  const el = document.getElementById("map-data");
  if (!el || !window.L) return;
  const data = JSON.parse(el.textContent);
  const map = L.map("map");
  L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png",
    {maxZoom: 18, attribution: "&copy; OpenStreetMap contributors"}).addTo(map);
  const line = L.polyline(data.path.map(p => [p.lat, p.lng]), {color: "#0b6b4f", weight: 5}).addTo(map);
  data.stops.forEach((s, i) => L.marker([s.lat, s.lng]).addTo(map).bindTooltip((i + 1) + ". " + s.name));
  map.fitBounds(line.getBounds(), {padding: [20, 20]});
});
