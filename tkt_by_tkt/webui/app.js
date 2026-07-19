/* Ticket by Ticket web client.
 *
 * Pure API consumer of design/api.md: it renders state and submits intended
 * actions; the server is the rules engine and every 409/422 it returns is
 * surfaced in the banner rather than second-guessed here.  Board geometry
 * ports the slippy-tile math and rectangle-row route drawing of mapsvg.py.
 */
"use strict";

const COLORS = ["blue", "red", "orange", "green", "yellow", "purple",
                "white", "black"];
const WILD = "wild";
const BLANK = "blank";
const CARD_FILL = {
  blue: "#2b6cb8", red: "#c94040", orange: "#dd8531", green: "#4a9d54",
  yellow: "#d9bc3a", purple: "#8a55b0", white: "#f2f2f2", black: "#333333",
  blank: "#9a9a9a", wild: "#b06ab3",
};
const PLAYER_COLORS = ["#e6194b", "#3cb44b", "#4363d8", "#f58231",
                       "#911eb4", "#42d4f4", "#f032e6", "#9a6324"];
const DEFAULT_TILES = "https://tile.openstreetmap.org/{z}/{x}/{y}.png";
const POLL_MS = 2000;
const MAX_BOARD_PX = 2048;

let cfg = null;      // {server, game, player, token, tiles}
let tbtMap = null;   // map JSON from GET /map
let geo = null;      // board geometry: zoom, origin, size, city pixel coords
let pub = null;      // last public state
let priv = null;     // last private state
let lastEtag = null;
let lastSeq = 0;
let pollTimer = null;
let laneEls = {};    // "route#track" -> {group, rects, color}
let claimCtx = null; // route being claimed via the dialog

const $ = (id) => document.getElementById(id);

/* ----- API ----------------------------------------------------------- */

async function api(path, options) {
  const opts = options || {};
  const headers = Object.assign({}, opts.headers);
  if (opts.auth !== false) {
    headers["Authorization"] = "Bearer " + cfg.token;
  }
  if (opts.body !== undefined) {
    headers["Content-Type"] = "application/json";
  }
  const response = await fetch(cfg.server + "/v1/games/" + cfg.game + path, {
    method: opts.method || (opts.body !== undefined ? "POST" : "GET"),
    headers: headers,
    body: opts.body !== undefined ? JSON.stringify(opts.body) : undefined,
  });
  if (response.status === 304) {
    return null;
  }
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const err = new Error(data.message || response.statusText);
    err.code = data.error || String(response.status);
    throw err;
  }
  return { data: data, etag: response.headers.get("ETag") };
}

/* ----- slippy-map math (mapsvg.py deg2num, fractional) ---------------- */

function worldX(lng, zoom) {
  return (lng + 180) / 360 * Math.pow(2, zoom) * 256;
}

function worldY(lat, zoom) {
  const rad = lat * Math.PI / 180;
  return (1 - Math.asinh(Math.tan(rad)) / Math.PI) / 2
         * Math.pow(2, zoom) * 256;
}

function computeGeo(cities) {
  const lats = Object.values(cities).map((c) => c[0]);
  const lngs = Object.values(cities).map((c) => c[1]);
  const latMargin = Math.max((Math.max(...lats) - Math.min(...lats)) * 0.08, 0.01);
  const lngMargin = Math.max((Math.max(...lngs) - Math.min(...lngs)) * 0.08, 0.01);
  const north = Math.max(...lats) + latMargin;
  const south = Math.min(...lats) - latMargin;
  const west = Math.min(...lngs) - lngMargin;
  const east = Math.max(...lngs) + lngMargin;
  let zoom = 3;
  for (let z = 14; z >= 3; z--) {
    const w = worldX(east, z) - worldX(west, z);
    const h = worldY(south, z) - worldY(north, z);
    if (w <= MAX_BOARD_PX && h <= MAX_BOARD_PX) {
      zoom = z;
      break;
    }
  }
  const tileX0 = Math.floor(worldX(west, zoom) / 256);
  const tileY0 = Math.floor(worldY(north, zoom) / 256);
  const tileX1 = Math.floor(worldX(east, zoom) / 256);
  const tileY1 = Math.floor(worldY(south, zoom) / 256);
  const g = {
    zoom: zoom,
    tileX0: tileX0, tileY0: tileY0, tileX1: tileX1, tileY1: tileY1,
    originX: tileX0 * 256, originY: tileY0 * 256,
    width: (tileX1 - tileX0 + 1) * 256,
    height: (tileY1 - tileY0 + 1) * 256,
    cityPx: {},
  };
  for (const [name, latlng] of Object.entries(cities)) {
    g.cityPx[name] = [worldX(latlng[1], zoom) - g.originX,
                      worldY(latlng[0], zoom) - g.originY];
  }
  return g;
}

/* ----- board rendering ------------------------------------------------ */

function svgEl(tag, attrs, parent) {
  const el = document.createElementNS("http://www.w3.org/2000/svg", tag);
  for (const [k, v] of Object.entries(attrs)) {
    el.setAttribute(k, v);
  }
  if (parent) {
    parent.appendChild(el);
  }
  return el;
}

function routeId(cityA, cityB) {
  return [cityA, cityB].sort().join("|");
}

function drawBoard() {
  const svg = $("board");
  svg.innerHTML = "";
  laneEls = {};
  geo = computeGeo(tbtMap.cities);
  svg.setAttribute("viewBox", "0 0 " + geo.width + " " + geo.height);

  const tiles = svgEl("g", { "class": "tiles" }, svg);
  for (let x = geo.tileX0; x <= geo.tileX1; x++) {
    for (let y = geo.tileY0; y <= geo.tileY1; y++) {
      svgEl("image", {
        href: cfg.tiles.replace("{z}", geo.zoom).replace("{x}", x)
                       .replace("{y}", y),
        x: x * 256 - geo.originX, y: y * 256 - geo.originY,
        width: 256, height: 256,
      }, tiles);
    }
  }

  const routesG = svgEl("g", { "class": "routes" }, svg);
  for (const route of tbtMap.routes) {
    drawRoute(routesG, route);
  }

  const citiesG = svgEl("g", { "class": "cities" }, svg);
  for (const [name, px] of Object.entries(geo.cityPx)) {
    svgEl("circle", { cx: px[0], cy: px[1], r: 6, "class": "city" }, citiesG);
    const label = svgEl("text", { x: px[0] + 9, y: px[1] + 4,
                                  "class": "city-label" }, citiesG);
    label.textContent = name;
  }
}

function drawRoute(parent, route) {
  const rid = routeId(route.cities[0], route.cities[1]);
  const [pa, pb] = [geo.cityPx[route.cities[0]], geo.cityPx[route.cities[1]]];
  const dist = Math.hypot(pb[0] - pa[0], pb[1] - pa[1]);
  const angle = Math.atan2(pb[1] - pa[1], pb[0] - pa[0]) * 180 / Math.PI;
  const mid = [(pa[0] + pb[0]) / 2, (pa[1] + pb[1]) / 2];
  const length = route.length;
  const tracks = route.tracks;
  // one row of "car" rectangles per lane, laid along the x axis and
  // rotated onto the city-to-city line (same scheme as mapsvg.py, but
  // sized to the on-screen distance instead of fixed print dimensions)
  const carLen = Math.min(40, Math.max(10, (dist - 28) / (length * 9 / 8)));
  const carW = 10;
  const rowLen = length * carLen * 9 / 8 - carLen / 8;
  const rowsH = tracks.length * carW * 9 / 8 - carW / 8;
  const routeG = svgEl("g", {
    transform: "translate(" + mid[0] + " " + mid[1] + ") rotate(" + angle + ")",
  }, parent);
  tracks.forEach((color, track) => {
    const fill = CARD_FILL[color] || CARD_FILL.blank;
    const laneG = svgEl("g", { "class": "lane" }, routeG);
    const rects = [];
    for (let car = 0; car < length; car++) {
      rects.push(svgEl("rect", {
        x: car * carLen * 9 / 8 - rowLen / 2,
        y: track * carW * 9 / 8 - rowsH / 2,
        width: carLen, height: carW,
        fill: fill, opacity: 0.8, stroke: "#00000055",
      }, laneG));
    }
    const tip = svgEl("title", {}, laneG);
    tip.textContent = rid + " — length " + length + ", " + color + " lane";
    laneG.addEventListener("click", () => onLaneClick(rid, track, route));
    laneEls[rid + "#" + track] = { group: laneG, rects: rects,
                                   color: color, tip: tip, route: route };
  });
}

function applyClaims() {
  const claimed = {};
  for (const claim of pub.claims) {
    claimed[claim.route + "#" + claim.track] = claim.player;
  }
  for (const [key, lane] of Object.entries(laneEls)) {
    const owner = claimed[key];
    if (owner) {
      const color = playerColor(owner);
      lane.group.classList.add("claimed");
      lane.tip.textContent = key.split("#")[0] + " — claimed by "
                             + playerName(owner);
      for (const rect of lane.rects) {
        rect.setAttribute("fill", color);
        rect.setAttribute("opacity", 0.95);
        rect.setAttribute("stroke", "#000");
      }
    } else {
      lane.group.classList.remove("claimed");
      for (const rect of lane.rects) {
        rect.setAttribute("fill", CARD_FILL[lane.color] || CARD_FILL.blank);
        rect.setAttribute("opacity", 0.8);
        rect.setAttribute("stroke", "#00000055");
      }
    }
  }
}

/* ----- state helpers -------------------------------------------------- */

function playerIndex(playerId) {
  return pub.players.findIndex((p) => p.player_id === playerId);
}

function playerColor(playerId) {
  return PLAYER_COLORS[Math.max(playerIndex(playerId), 0)
                       % PLAYER_COLORS.length];
}

function playerName(playerId) {
  const player = pub.players[playerIndex(playerId)];
  return player ? player.name : playerId;
}

function isMyTurn() {
  return pub.current_player === cfg.player
         && ["turn", "second_card"].includes(pub.expecting);
}

function handCounts() {
  const counts = {};
  for (const card of priv.hand) {
    counts[card] = (counts[card] || 0) + 1;
  }
  return counts;
}

/* ----- panels --------------------------------------------------------- */

function cardChip(color, count, onclick) {
  const chip = document.createElement(onclick ? "button" : "span");
  chip.className = "card card-" + color;
  chip.textContent = count !== null ? color + " ×" + count : color;
  if (onclick) {
    chip.type = "button";
    chip.addEventListener("click", onclick);
  }
  return chip;
}

function renderTable() {
  const row = $("faceup-row");
  row.innerHTML = "";
  const deck = document.createElement("button");
  deck.type = "button";
  deck.className = "card card-deck";
  deck.textContent = "deck ×" + pub.deck_count;
  deck.title = "Draw blind from the deck (" + pub.discard_count
               + " in discard)";
  deck.addEventListener("click", () => act(api("/card-draws",
                                              { body: { source: "deck" } }),
                                          reportDraw));
  row.appendChild(deck);
  for (const card of pub.faceup) {
    row.appendChild(cardChip(card, null, () =>
      act(api("/card-draws", { body: { source: "faceup", card: card } }),
          reportDraw)));
  }

  const table = $("players-table");
  table.innerHTML = "<tr><th></th><th>player</th><th>cars</th><th>cards</th>"
                    + "<th>tickets</th><th>routes</th></tr>";
  for (const player of pub.players) {
    const tr = document.createElement("tr");
    if (player.player_id === pub.current_player) {
      tr.className = "current";
    }
    const you = player.player_id === cfg.player ? " (you)" : "";
    tr.innerHTML = "<td><span class='swatch' style='background:"
      + playerColor(player.player_id) + "'></span></td>"
      + "<td></td><td>" + player.cars + "</td><td>" + player.hand_count
      + "</td><td>" + player.ticket_count + "</td><td>"
      + player.claimed_routes + "</td>";
    tr.children[1].textContent = player.name + you;
    table.appendChild(tr);
  }
}

function renderPrivate() {
  const hand = $("hand-row");
  hand.innerHTML = "";
  const counts = handCounts();
  for (const color of COLORS.concat([WILD])) {
    if (counts[color]) {
      hand.appendChild(cardChip(color, counts[color], null));
    }
  }
  $("cars-label").textContent = "Cars left: " + priv.cars;

  const tickets = $("ticket-list");
  tickets.innerHTML = "";
  for (const ticket of priv.tickets) {
    const li = document.createElement("li");
    li.textContent = ticket.cities.join(" – ") + " (" + ticket.points + ") "
                     + (ticket.completed ? "✓" : "…");
    li.className = ticket.completed ? "done" : "";
    tickets.appendChild(li);
  }

  const offer = priv.pending_offer;
  $("offer-section").hidden = !offer;
  if (offer) {
    const list = $("offer-list");
    list.innerHTML = "";
    for (const ticket of offer) {
      const label = document.createElement("label");
      label.className = "offer-item";
      const box = document.createElement("input");
      box.type = "checkbox";
      box.value = ticket.ticket_id;
      label.appendChild(box);
      label.appendChild(document.createTextNode(
        " " + ticket.cities.join(" – ") + " (" + ticket.points + " pts)"));
      list.appendChild(label);
    }
  }
}

function renderStatus() {
  $("game-label").textContent = cfg.game + " · " + pub.phase;
  const banner = $("turn-banner");
  if (pub.phase === "finished") {
    banner.textContent = "Game over";
  } else if (priv && priv.pending_offer) {
    banner.textContent = "Pick your tickets";
  } else if (isMyTurn()) {
    banner.textContent = pub.expecting === "second_card"
      ? "Your turn — draw a second card" : "Your turn!";
  } else if (pub.phase === "setup") {
    banner.textContent = "Waiting for setup ticket picks";
  } else {
    banner.textContent = "Waiting for " + playerName(pub.current_player);
  }
  banner.classList.toggle("mine", isMyTurn() || !!(priv && priv.pending_offer));
  $("draw-tickets-btn").disabled = !(isMyTurn() && pub.expecting === "turn");

  $("scores-section").hidden = !pub.scores;
  if (pub.scores) {
    const table = $("scores-table");
    table.innerHTML = "<tr><th>player</th><th>routes</th><th>tickets</th>"
                      + "<th>longest</th><th>total</th></tr>";
    const sorted = [...pub.scores].sort((a, b) => b.total - a.total);
    for (const score of sorted) {
      const tr = document.createElement("tr");
      tr.innerHTML = "<td></td><td>" + score.route_points + "</td><td>+"
        + score.tickets_gained + " / −" + score.tickets_lost + "</td><td>"
        + score.longest_path_bonus + "</td><td><b>" + score.total
        + "</b></td>";
      tr.children[0].textContent = playerName(score.player_id);
      table.appendChild(tr);
    }
  }
}

function renderLog(events) {
  const list = $("log-list");
  for (const ev of events) {
    const li = document.createElement("li");
    li.textContent = describeEvent(ev);
    list.appendChild(li);
    lastSeq = Math.max(lastSeq, ev.seq);
  }
  list.scrollTop = list.scrollHeight;
}

function describeEvent(ev) {
  const who = ev.player ? playerName(ev.player) : "";
  switch (ev.type) {
    case "join": return who + " joined";
    case "start": return who + " started the game";
    case "card_draw":
      return ev.source === "faceup"
        ? who + " took a face-up " + ev.card + " card"
        : who + " drew from the deck";
    case "claim":
      return who + " claimed " + ev.route + " (lane " + ev.track + ") with "
             + ev.cards.join(", ");
    case "ticket_draw": return who + " drew " + ev.offered + " tickets";
    case "ticket_keep": return who + " kept " + ev.kept + " ticket(s)";
    case "faceup_reshuffle": return "face-up row reshuffled (3+ wilds)";
    case "last_round": return "Last round! " + who + " is almost out of cars";
    case "game_end": return "Game over";
    default: return JSON.stringify(ev);
  }
}

/* ----- actions -------------------------------------------------------- */

function showError(err) {
  $("banner-text").textContent = (err.code ? err.code + ": " : "")
                                 + err.message;
  $("banner").hidden = false;
}

function reportDraw(result) {
  $("banner-text").textContent = "You drew a " + result.card + " card"
    + (result.draws_remaining ? " — one more draw" : "");
  $("banner").hidden = false;
}

async function act(promise, onSuccess) {
  try {
    const response = await promise;
    $("banner").hidden = true;
    if (onSuccess) {
      onSuccess(response.data);
    }
  } catch (err) {
    showError(err);
  }
  await refresh(true);
}

function onLaneClick(rid, track, route) {
  if (!pub || pub.phase === "finished") {
    return;
  }
  if (pub.claims.some((c) => c.route === rid && c.track === track)) {
    return;
  }
  claimCtx = { rid: rid, track: track, length: route.length,
               lane: route.tracks[track] };
  const counts = handCounts();
  const wilds = counts[WILD] || 0;
  const select = $("claim-color");
  select.innerHTML = "";
  const candidates = claimCtx.lane === BLANK
    ? COLORS.filter((c) => counts[c])
    : [claimCtx.lane];
  for (const color of candidates) {
    const opt = document.createElement("option");
    opt.value = color;
    opt.textContent = color + " (" + (counts[color] || 0) + " in hand)";
    select.appendChild(opt);
  }
  select.disabled = claimCtx.lane !== BLANK;
  $("claim-title").textContent = rid;
  $("claim-info").textContent = "Length " + claimCtx.length + ", "
    + claimCtx.lane + " lane. You have " + wilds + " wild(s).";
  updateClaimCards();
  $("claim-dialog").showModal();
}

function updateClaimCards() {
  const counts = handCounts();
  const color = $("claim-color").value;
  const wilds = counts[WILD] || 0;
  const wanted = Math.max(0, claimCtx.length - (counts[color] || 0));
  const maxWilds = Math.min(wilds, claimCtx.length);
  // if the hand can't cover the route, keep the bounds consistent so the
  // form still submits and the server's 422 explains the problem
  const minWilds = Math.min(wanted, maxWilds);
  const input = $("claim-wilds");
  input.min = minWilds;
  input.max = maxWilds;
  input.value = Math.min(Math.max(Number(input.value) || 0, minWilds),
                         maxWilds);
  const n = Number(input.value);
  const cards = Array(claimCtx.length - n).fill(color)
                .concat(Array(n).fill(WILD));
  $("claim-cards").textContent = cards.join(", ") || "—";
  claimCtx.cards = cards;
}

function submitClaim(event) {
  event.preventDefault();
  const body = { route: claimCtx.rid, track: claimCtx.track,
                 cards: claimCtx.cards };
  $("claim-dialog").close();
  act(api("/claims", { body: body }), (result) => {
    $("banner-text").textContent = "Claimed " + claimCtx.rid + " for "
      + result.points + " points (" + result.cars_remaining + " cars left)";
    $("banner").hidden = false;
  });
}

function submitKeep() {
  const kept = [...$("offer-list").querySelectorAll("input:checked")]
               .map((box) => Number(box.value));
  act(api("/ticket-keeps", { body: { tickets: kept } }));
}

/* ----- polling -------------------------------------------------------- */

async function refresh(force) {
  try {
    const headers = {};
    if (lastEtag && !force) {
      headers["If-None-Match"] = lastEtag;
    }
    const response = await api("", { auth: false, headers: headers });
    if (response === null) {
      return;
    }
    lastEtag = response.etag;
    pub = response.data;
    const me = await api("/players/" + cfg.player);
    priv = me.data;
    const log = await api("/log?since=" + lastSeq, { auth: false });
    renderTable();
    renderPrivate();
    renderStatus();
    applyClaims();
    renderLog(log.data);
  } catch (err) {
    showError(err);
    if (err.code === "unauthorized" || err.code === "forbidden"
        || err.code === "game_not_found") {
      leave();
    }
  }
}

/* ----- join / leave --------------------------------------------------- */

async function enterGame() {
  tbtMap = (await api("/map", { auth: false })).data;
  $("join-view").hidden = true;
  $("play-view").hidden = false;
  drawBoard();
  await refresh(true);
  pollTimer = setInterval(refresh, POLL_MS);
}

function leave() {
  clearInterval(pollTimer);
  pollTimer = null;
  localStorage.removeItem("tbt-playing");
  $("play-view").hidden = true;
  $("join-view").hidden = false;
}

function init() {
  const saved = JSON.parse(localStorage.getItem("tbt-config") || "null");
  if (saved) {
    $("in-server").value = saved.server;
    $("in-game").value = saved.game;
    $("in-player").value = saved.player;
    $("in-token").value = saved.token;
    $("in-tiles").value = saved.tiles === DEFAULT_TILES ? "" : saved.tiles;
  }
  // ?game=…&player=…&token=… prefills the form (and auto-joins when
  // complete) so a seat can be handed to someone as a link
  const params = new URLSearchParams(window.location.search);
  for (const [param, input] of [["server", "in-server"], ["game", "in-game"],
                                ["player", "in-player"], ["token", "in-token"],
                                ["tiles", "in-tiles"]]) {
    if (params.get(param)) {
      $(input).value = params.get(param);
    }
  }

  $("join-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    cfg = {
      server: $("in-server").value.trim().replace(/\/+$/, "")
              || window.location.origin,
      game: $("in-game").value.trim(),
      player: $("in-player").value.trim(),
      token: $("in-token").value.trim(),
      tiles: $("in-tiles").value.trim() || DEFAULT_TILES,
    };
    try {
      await enterGame();
      localStorage.setItem("tbt-config", JSON.stringify(cfg));
      localStorage.setItem("tbt-playing", "1");
      $("join-error").hidden = true;
    } catch (err) {
      $("join-error").textContent = "Could not load game: " + err.message;
      $("join-error").hidden = false;
    }
  });

  $("leave-btn").addEventListener("click", leave);
  $("banner-close").addEventListener("click", () => {
    $("banner").hidden = true;
  });
  $("draw-tickets-btn").addEventListener("click", () =>
    act(api("/ticket-draws", { body: {} })));
  $("keep-btn").addEventListener("click", submitKeep);
  $("claim-color").addEventListener("change", updateClaimCards);
  $("claim-wilds").addEventListener("input", updateClaimCards);
  $("claim-form").addEventListener("submit", submitClaim);
  $("claim-cancel").addEventListener("click", () => {
    $("claim-dialog").close();
  });

  const fromLink = params.get("game") && params.get("player")
                   && params.get("token");
  if (fromLink || (saved && localStorage.getItem("tbt-playing"))) {
    $("join-form").requestSubmit();
  }
}

document.addEventListener("DOMContentLoaded", init);
