"use strict";
// Dane z events.json (generowane codziennie). Bez frameworka i bez kroku build.
const CAT = {
  scena: ["Scena", "var(--c1)"], kino: ["Kino", "var(--c2)"], biblioteka: ["Biblioteka", "var(--c3)"],
  edukacja: ["Edukacja", "var(--c4)"], okolice: ["Okolice (do 30 km)", "var(--c5)"], inne: ["Inne", "var(--c6)"],
};
const MON = ["styczeń","luty","marzec","kwiecień","maj","czerwiec","lipiec","sierpień","wrzesień","październik","listopad","grudzień"];
const MONG = ["stycznia","lutego","marca","kwietnia","maja","czerwca","lipca","sierpnia","września","października","listopada","grudnia"];
const DAY = ["niedziela","poniedziałek","wtorek","środa","czwartek","piątek","sobota"];
const $ = (id) => document.getElementById(id);
const pad = (n) => String(n).padStart(2, "0");
const iso = (d) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
const now = new Date();
const today = iso(now);
const flt = Object.fromEntries(Object.keys(CAT).map((k) => [k, true]));
let view = new Date(now.getFullYear(), now.getMonth(), 1), sel = null, E = [];

// Daty w events.json mają offset Europe/Warsaw, więc data i godzina to po prostu fragmenty tekstu.
const dayOf = (s) => s.slice(0, 10);
const timeOf = (e) => (e.all_day ? "" : e.start.slice(11, 16));
const lastDay = (e) => dayOf(e.end || e.start);

function el(tag, attrs, ...kids) {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (k === "class") n.className = v; else if (k === "text") n.textContent = v; else n.setAttribute(k, v);
  }
  kids.flat().forEach((c) => n.append(c));
  return n;
}
const vis = () => E.filter((e) => flt[e.category]);
// Kino: seanse tylko w wymienionych dniach (`dates`), reszta: cały zakres start..end.
const onDay = (e, k) => (e.dates && e.dates.length ? e.dates.includes(k) : dayOf(e.start) <= k && k <= lastDay(e));
const shortDay = (d) => `${+d.slice(8, 10)}.${d.slice(5, 7)}`;

function gcal(e) {
  const d = (s) => s.replace(/-/g, "");
  let dates;
  if (e.all_day) {
    const nx = new Date(lastDay(e) + "T12:00:00"); nx.setDate(nx.getDate() + 1);
    dates = `${d(dayOf(e.start))}/${d(iso(nx))}`;
  } else {
    const st = new Date(e.start), en = e.end ? new Date(e.end) : new Date(st.getTime() + 2 * 36e5);
    const f = (x) => x.toISOString().replace(/[-:]|\.\d{3}/g, "");
    dates = `${f(st)}/${f(en)}`;
  }
  const p = new URLSearchParams({ action: "TEMPLATE", text: e.title, dates, location: [e.venue, e.place].filter(Boolean).join(", "), details: e.url || "" });
  return "https://calendar.google.com/calendar/render?" + p;
}

function chips() {
  $("chips").replaceChildren(...Object.entries(CAT).map(([k, [label, color]]) => {
    const b = el("button", { class: "chip", "aria-pressed": String(flt[k]), "data-k": k }, el("i", { style: `background:${color}` }), label);
    b.onclick = () => { flt[k] = !flt[k]; chips(); draw(); };
    return b;
  }));
}

function next() {
  const lim = new Date(now); lim.setDate(lim.getDate() + 7);
  const L = iso(lim), v = vis().filter((e) => lastDay(e) >= today && e.status !== "cancelled");
  const t = v.filter((e) => onDay(e, today)), w = v.filter((e) => dayOf(e.start) <= L);
  const box = $("next"); box.replaceChildren();
  if (t.length) {
    box.append(el("b", { text: `Dziś: ${t.length} ${t.length === 1 ? "wydarzenie" : "wydarzenia"}` }),
      el("div", { text: t.map((e) => `${timeOf(e) ? timeOf(e) + " " : ""}${e.title}`).join("; ") }));
  } else {
    const f = v[0];
    box.append(el("b", { text: `W ciągu 7 dni: ${w.length}` }),
      el("div", { text: f ? `Najbliższe: ${f.title}, ${dayOf(f.start).split("-").reverse().slice(0, 2).join(".")}${timeOf(f) ? " o " + timeOf(f) : ""}` : "Brak nadchodzących wydarzeń" }));
  }
}

function cal() {
  const y = view.getFullYear(), mo = view.getMonth();
  $("mt").textContent = `${MON[mo]} ${y}`;
  const cells = ["Pn","Wt","Śr","Cz","Pt","So","Nd"].map((d) => el("span", { class: "w", text: d }));
  const off = (new Date(y, mo, 1).getDay() + 6) % 7, n = new Date(y, mo + 1, 0).getDate(), v = vis();
  for (let i = 0; i < off; i++) cells.push(el("button", { class: "d", disabled: "" }));
  for (let d = 1; d <= n; d++) {
    const k = `${y}-${pad(mo + 1)}-${pad(d)}`;
    const cats = [...new Set(v.filter((e) => onDay(e, k)).map((e) => e.category))];
    const b = el("button", { class: "d" + (k === today ? " t" : "") + (k === sel ? " s" : ""), "data-k": k,
      "aria-label": `${d} ${MONG[mo]}${cats.length ? ", są wydarzenia" : ""}`, "aria-pressed": String(k === sel) },
      String(d), el("em", {}, cats.map((c) => el("u", { style: `background:${k === sel ? "var(--bg)" : CAT[c][1]}` }))));
    b.onclick = () => { sel = sel === k ? null : k; draw(); };
    cells.push(b);
  }
  $("g").replaceChildren(...cells);
}

function card(e, newIds) {
  const showPlace = e.place && !(e.venue || "").toLowerCase().includes(e.place.toLowerCase());
  const where = [e.venue, showPlace ? e.place : null].filter(Boolean).join(", ");
  const dist = e.category === "okolice" && e.distance_km ? ` (${Math.round(e.distance_km)} km)` : "";
  const multi = e.end && !(e.dates && e.dates.length) && lastDay(e) !== dayOf(e.start) ? `do ${lastDay(e).split("-").reverse().slice(0, 2).join(".")} · ` : "";
  const days = e.dates && e.dates.length ? ` · seanse: ${e.dates.slice(0, 6).map(shortDay).join(", ")}${e.dates.length > 6 ? ` i ${e.dates.length - 6} więcej` : ""}` : "";
  const times = e.times && e.times.length ? ` · godz. ${e.times.join(", ")}` : "";
  const title = el("h3", { text: e.title });
  if (e.status === "cancelled") title.append(el("span", { class: "badge", text: "Odwołane" }));
  if (newIds.has(e.id)) title.append(el("span", { class: "badge", text: "Nowe" }));
  const lead = (e.dates && e.dates.length) || (e.times && e.times.length > 1) ? "" : (timeOf(e) ? timeOf(e) + " · " : "");
  const meta = el("p", { text: `${lead}${multi}${where}${dist}${days}${times}${e.price_text ? " · " + e.price_text : ""}` });
  const row = el("div", { class: "row" });
  const link = (href, text, cls) => el("a", { class: cls, href, target: "_blank", rel: "noopener", text });
  if (e.ticket_url) row.append(link(e.ticket_url, "Bilety", "a p"));
  if (e.url) row.append(link(e.url, "Szczegóły", e.ticket_url ? "a" : "a p"));
  row.append(link(gcal(e), "Dodaj do kalendarza", "a"));
  const art = el("article", { class: "ev", style: `--cc:${CAT[e.category][1]}` }, title, meta);
  if (e.status === "cancelled") art.classList.add("cancelled");
  if (e.confidence === "low") art.append(el("p", { class: "low", text: "Wydarzenie cykliczne lub niepewny termin, sprawdź u organizatora." }));
  art.append(row);
  return art;
}

function list() {
  const v = vis().filter((e) => (sel ? onDay(e, sel) : lastDay(e) >= today));
  const firsts = new Set(E.map((e) => e.first_seen));
  const yesterday = new Date(now); yesterday.setDate(yesterday.getDate() - 1);
  const newIds = firsts.size > 1 ? new Set(E.filter((e) => e.first_seen >= iso(yesterday)).map((e) => e.id)) : new Set();
  $("clr").hidden = !sel;
  $("lt").textContent = sel ? `Wydarzenia: ${sel.split("-").reverse().join(".")}` : "Nadchodzące wydarzenia";
  if (!v.length) { $("list").replaceChildren(el("p", { class: "empty", text: "Brak wydarzeń dla tego wyboru. Zmień dzień albo włącz więcej kategorii." })); return; }
  const out = []; let last = "";
  for (const e of v) {
    const day = dayOf(e.start) < today ? today : dayOf(e.start);
    if (!sel && day !== last) {
      last = day; const d = new Date(day + "T12:00:00");
      out.push(el("h2", { text: `${DAY[d.getDay()]}, ${d.getDate()} ${MONG[d.getMonth()]}${day === today ? " (dziś)" : ""}` }));
    }
    out.push(card(e, newIds));
  }
  $("list").replaceChildren(...out);
}

function draw() { cal(); list(); next(); }

const SRC = {
  mdk: "MDK Radomsko", radomsko_pl: "radomsko.pl", muzeum: "Muzeum Regionalne", mbp: "Biblioteka (MBP)",
  kamiensk: "Gmina Kamieńsk", przedborz: "MDK Przedbórz", biletyna: "biletyna.pl", ebilet: "ebilet.pl", manual: "Wpisy ręczne",
};

const plural = (n) => (n === 1 ? "wydarzenie" : n % 10 >= 2 && n % 10 <= 4 && !(n % 100 >= 12 && n % 100 <= 14) ? "wydarzenia" : "wydarzeń");

function sourceLine(name, s) {
  const label = SRC[name] || name;
  const fmt = (d) => (d ? d.split("-").reverse().slice(0, 2).join(".") : "");
  if (s.stale) return ["warn", `${label}: dane nieaktualne od ${fmt(s.stale_since)}, ${s.stale_reason || "problem ze źródłem"}`];
  if (!s.ok) return ["bad", `${label}: błąd pobierania od ${fmt(s.first_failure)}`];
  return ["ok", `${label}: ${s.count} ${plural(s.count)}`];
}

async function foot(generated) {
  const f = $("foot"); f.replaceChildren();
  const when = generated ? new Date(generated).toLocaleString("pl-PL", { dateStyle: "long", timeStyle: "short" }) : "brak danych";
  f.append(`Ostatnia aktualizacja: ${when}. Przed wyjściem sprawdź stronę organizatora.`);
  try {
    const st = await (await fetch("status.json", { cache: "no-cache" })).json();
    const lines = Object.entries(st.sources || {}).filter(([n, s]) => n !== "manual" || s.count).map(([n, s]) => sourceLine(n, s));
    const problems = lines.filter(([k]) => k !== "ok").length;
    const summary = el("summary", { class: problems ? "stale" : "", text: problems ? `Źródła danych: ${problems} z problemem` : "Źródła danych: wszystkie działają" });
    f.append(el("details", {}, summary, el("ul", { class: "srcs" }, lines.map(([k, t]) => el("li", { class: k, text: t })))));
  } catch { /* status.json jest opcjonalny */ }
}

function subscribeLink() {
  // events.ics leży obok strony; webcal:// otwiera subskrypcję w aplikacji kalendarza
  const ics = new URL("events.ics", location.href);
  const web = ics.href, cal = "webcal://" + ics.host + ics.pathname;
  const a = el("a", { href: cal, text: "Subskrybuj kalendarz (ICS)" });
  const copy = el("button", { class: "clr", type: "button", text: "Kopiuj adres" });
  copy.onclick = async () => {
    try { await navigator.clipboard.writeText(web); copy.textContent = "Skopiowano"; } catch { prompt("Adres kalendarza ICS:", web); }
  };
  $("subs").replaceChildren(a, " · ", copy);
}

async function main() {
  subscribeLink();
  if ("serviceWorker" in navigator && location.protocol.startsWith("http")) {
    navigator.serviceWorker.register("sw.js").catch(() => {});
  }
  chips();
  $("pv").onclick = () => { view.setMonth(view.getMonth() - 1); cal(); };
  $("nx").onclick = () => { view.setMonth(view.getMonth() + 1); cal(); };
  $("clr").onclick = () => { sel = null; draw(); };
  let generated = null;
  try {
    const data = await (await fetch("events.json", { cache: "no-cache" })).json();
    generated = data.generated; E = data.events;
  } catch {
    $("list").replaceChildren(el("p", { class: "empty", text: "Nie udało się wczytać wydarzeń. Odśwież stronę." }));
  }
  E.sort((a, b) => (a.start < b.start ? -1 : a.start > b.start ? 1 : 0));
  if (E.length) draw(); else { cal(); next(); }
  foot(generated);
}
main();
