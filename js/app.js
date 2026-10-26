const VIEWS = ["home", "fixtures", "results", "table", "scorers"];
const STATS = [
  ["possessionPct", "Possession", true],
  ["totalShots", "Shots", false],
  ["shotsOnTarget", "On target", false],
  ["wonCorners", "Corners", false],
  ["foulsCommitted", "Fouls", false],
  ["offsides", "Offsides", false],
  ["saves", "Saves", false],
  ["yellowCards", "Yellow cards", false],
  ["redCards", "Red cards", false],
];

let season = null;
let filter = "all";
let currentView = "home";
const openMatches = new Set();

const app = document.querySelector("#app");

function esc(value) {
  return String(value ?? "").replace(/[&<>"']/g, (character) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;",
  }[character]));
}

function viewFromHash() {
  const name = location.hash.replace("#", "");
  return VIEWS.includes(name) ? name : "home";
}

function ordinal(number) {
  const tens = number % 100;
  if (tens >= 11 && tens <= 13) return `${number}th`;
  if (number % 10 === 1) return `${number}st`;
  if (number % 10 === 2) return `${number}nd`;
  if (number % 10 === 3) return `${number}rd`;
  return `${number}th`;
}

function opponent(match) {
  return match.bluesHome ? match.awayTeam : match.homeTeam;
}

function place(match) {
  return match.bluesHome ? "Home" : "Away";
}

function outcome(match) {
  const scored = match.bluesHome ? match.homeScore : match.awayScore;
  const conceded = match.bluesHome ? match.awayScore : match.homeScore;
  if (scored > conceded) return "W";
  if (scored < conceded) return "L";
  return "D";
}

function outcomeWord(letter) {
  if (letter === "W") return "win";
  if (letter === "L") return "loss";
  return "draw";
}

function monthLabel(match) {
  return new Intl.DateTimeFormat("en-GB", {
    timeZone: "Europe/London",
    month: "long",
    year: "numeric",
  }).format(new Date(match.kickoffUtc));
}

function goalsFor(match, team) {
  return (match.scorers || []).filter(
    (item) => item.team === team && ["goal", "penalty", "own-goal"].includes(item.kind)
  );
}

function scorerLine(item) {
  const name = item.player || "Scorer not named";
  let extra = "";
  if (item.kind === "penalty") extra = ' <span class="tag">pen</span>';
  if (item.kind === "own-goal") extra = ' <span class="tag">own goal</span>';
  const minute = item.minute ? `<span class="minute">${esc(item.minute)}</span> ` : "";
  return `<li>${minute}${esc(name)}${extra}</li>`;
}

function bluesMark(name) {
  return name === season.club ? " blues" : "";
}

function competitionMeta(match) {
  const bits = [place(match), match.competition];
  if (match.round) bits.push(match.round);
  return bits.join(" · ");
}

function statNumber(value) {
  const number = Number(value);
  return Number.isFinite(number) ? number : 0;
}

function renderStats(match) {
  if (!match.statsAvailable || !match.stats) {
    return "<p class=\"meta\">Possession, shots and cards were not published for this match.</p>";
  }
  const home = match.stats.home || {};
  const away = match.stats.away || {};
  const rows = STATS.map(([key, label, percent]) => {
    if (home[key] == null && away[key] == null) return "";
    const left = statNumber(home[key]);
    const right = statNumber(away[key]);
    const total = left + right;
    const leftWidth = total > 0 ? (left / total) * 100 : 50;
    const show = (value, isPercent) => {
      if (value == null || value === "") return "–";
      return isPercent ? `${esc(value)}%` : esc(value);
    };
    return `
      <div class="stat">
        <div class="stat-top">
          <b class="${match.homeTeam === season.club ? "blues" : ""}">${show(home[key], percent)}</b>
          <span class="stat-name">${esc(label)}</span>
          <b class="${match.awayTeam === season.club ? "blues" : ""}">${show(away[key], percent)}</b>
        </div>
        <div class="bar" aria-hidden="true">
          <i style="width:${leftWidth}%"></i>
          <i class="other" style="width:${100 - leftWidth}%"></i>
        </div>
      </div>`;
  }).join("");
  return `
    <p class="meta">${esc(match.homeTeam)} on the left, ${esc(match.awayTeam)} on the right.</p>
    ${rows}`;
}

function renderCards(match) {
  const cards = match.cards || [];
  if (!cards.length) return "";
  const lines = cards.map((card) => {
    const kind = card.kind === "red" ? "red card" : "yellow card";
    const detail = card.detail ? `, ${card.detail.toLowerCase()}` : "";
    const minute = card.minute ? `${card.minute} ` : "";
    return `<li>${esc(minute)}${esc(card.player || "Player not named")} (${esc(card.team)}), ${esc(kind)}${esc(detail)}</li>`;
  }).join("");
  return `<h3 class="kicker">Cards</h3><ul class="card-list">${lines}</ul>`;
}

function renderScoreBlock(match) {
  const blocks = ["home", "away"].map((side) => {
    const team = side === "home" ? match.homeTeam : match.awayTeam;
    const score = side === "home" ? match.homeScore : match.awayScore;
    const where = side === "home" ? "Home" : "Away";
    const events = goalsFor(match, team);
    const list = match.scorersComplete
      ? events.length
        ? `<ul class="event-list">${events.map(scorerLine).join("")}</ul>`
        : "<p class=\"meta\">No goals</p>"
      : "";
    return `
      <div>
        <div class="side">
          <span class="who${bluesMark(team)}">${esc(team)}<small>${where}</small></span>
          <span class="goals">${score == null ? "–" : esc(score)}</span>
        </div>
        ${list}
      </div>`;
  }).join("");
  const saved = (match.scorers || []).filter((item) => item.kind === "penalty-saved");
  const savedHtml = saved.length
    ? `<p class="meta">Penalty saved: ${saved.map((item) => `${esc(item.player || "Unnamed")} ${esc(item.minute || "")}`).join(", ")}</p>`
    : "";
  const incomplete = match.status === "finished" && !match.scorersComplete
    ? "<p class=\"meta\">The scorers for this match did not add up to the score, so they are not listed.</p>"
    : "";
  return `<div class="scoreline">${blocks}</div>${savedHtml}${incomplete}`;
}

function matchDetail(match) {
  const attendance = match.attendance
    ? `Attendance ${Number(match.attendance).toLocaleString("en-GB")}`
    : "Attendance was not published";
  const venue = match.venue || "Venue not published";
  return `
    <div class="match-more">
      <p class="meta">${esc(venue)}. ${esc(attendance)}.</p>
      ${renderScoreBlock(match)}
      ${renderStats(match)}
      ${renderCards(match)}
      <p><a class="more-link" href="${esc(match.reportUrl)}" target="_blank" rel="noopener">ESPN match report</a></p>
    </div>`;
}

function resultCard(match) {
  const open = openMatches.has(match.id);
  return `
    <article class="match">
      <button class="match-open" data-match="${esc(match.id)}" aria-expanded="${open ? "true" : "false"}">
        <p class="when">${esc(match.dateLong)} · ${esc(match.timeUk || "Time not confirmed")} UK</p>
        <p class="meta">${esc(competitionMeta(match))}</p>
        <p class="opponent">${esc(match.homeTeam)} ${esc(match.homeScore)}–${esc(match.awayScore)} ${esc(match.awayTeam)}</p>
      </button>
      ${open ? matchDetail(match) : ""}
    </article>`;
}

function fixtureCard(match) {
  const time = match.timeKnown && match.timeUk ? match.timeUk : "TBC";
  return `
    <article class="card fixture">
      <div>
        <div class="date">${esc(match.dateShort)}</div>
        <div class="time">${esc(time)}</div>
      </div>
      <div>
        <span class="badge ${match.bluesHome ? "" : "away"}">${esc(place(match))}</span>
        <strong>${esc(opponent(match))}</strong>
        <p class="meta">${esc(match.competition)}${match.round ? ` · ${esc(match.round)}` : ""}${match.venue ? ` · ${esc(match.venue)}` : ""}</p>
      </div>
    </article>`;
}

function filtered(matches) {
  if (filter === "league") return matches.filter((match) => match.competitionCode === "championship");
  if (filter === "cups") return matches.filter((match) => match.competitionCode !== "championship");
  return matches;
}

function filterBar() {
  const options = [
    ["all", "All"],
    ["league", "League"],
    ["cups", "Cups"],
  ];
  return `
    <div class="filters" role="group" aria-label="Competition">
      ${options.map(([value, label]) => `
        <button type="button" data-filter="${value}" aria-pressed="${filter === value ? "true" : "false"}">${label}</button>
      `).join("")}
    </div>`;
}

function groupedFixtures(matches) {
  let month = "";
  return matches.map((match) => {
    const label = monthLabel(match);
    const heading = label === month ? "" : `<h2 class="month">${esc(label)}</h2>`;
    month = label;
    return heading + fixtureCard(match);
  }).join("");
}

function emptyCups() {
  const notes = (season.competitions || [])
    .filter((item) => item.code !== "championship" && item.note)
    .map((item) => `<p>${esc(item.note)}</p>`)
    .join("");
  return `<div class="empty"><p>No upcoming cup ties.</p>${notes}</div>`;
}

function renderHome() {
  const blues = season.table.rows.find((row) => row.isBlues);
  if (!blues) {
    return `<p class="error">Birmingham City are not in the saved table.</p>`;
  }
  const played = season.matches.filter((match) => match.competitionCode === "championship" && match.status === "finished");
  const form = played.slice(-5).map(outcome);
  const next = season.matches.find((match) => match.status === "scheduled" || match.status === "live");
  const last = [...season.matches].reverse().find((match) => match.status === "finished");
  const formLabel = form.length
    ? `Last five Championship results, most recent on the right: ${form.map(outcomeWord).join(", ")}.`
    : "";
  const faGap = (season.gaps || []).find((gap) => gap.startsWith("FA Cup"));
  const nextBlock = next ? `
    <article class="card">
      <p class="kicker">${next.status === "live" ? "Live now" : "Next match"}</p>
      <p class="when">${esc(next.dateLong)}</p>
      <p class="kickoff">${esc(next.timeKnown ? next.timeUk : "TBC")}</p>
      <p class="meta">UK time</p>
      <p class="opponent">${esc(opponent(next))}</p>
      <p class="meta"><span class="badge ${next.bluesHome ? "" : "away"}">${esc(place(next))}</span>${esc(next.competition)}${next.round ? ` · ${esc(next.round)}` : ""}</p>
      ${next.venue ? `<p class="meta">${esc(next.venue)}</p>` : ""}
    </article>` : `<article class="empty"><p>No upcoming fixture is listed.</p></article>`;
  const lastBlock = last ? `
    <article class="card">
      <p class="kicker">Last result</p>
      <p class="when">${esc(last.dateShort)} · ${esc(last.competition)}</p>
      <p class="opponent">${esc(last.homeTeam)} ${esc(last.homeScore)}–${esc(last.awayScore)} ${esc(last.awayTeam)}</p>
      <p class="meta">${esc(place(last))}${last.venue ? ` · ${esc(last.venue)}` : ""}</p>
      <p><a class="more-link" href="#results">See scorers and stats</a></p>
    </article>` : "";
  const top = (season.seasonTotals.scorers || []).slice(0, 3);
  const topBlock = top.length ? `
    <article class="card">
      <p class="kicker">Top scorers</p>
      ${top.map((row) => `<p><strong>${esc(row.player)}</strong> · ${esc(row.goals)}</p>`).join("")}
      <p><a class="more-link" href="#scorers">Full list</a></p>
    </article>` : "";
  return `
    <section class="hero">
      <p class="kicker">${esc(season.season)} Championship</p>
      <div class="position">
        <strong>${esc(ordinal(blues.rank))}</strong>
        <span>${esc(blues.points)} points<br>goal difference ${blues.goalDifference > 0 ? "+" : ""}${esc(blues.goalDifference)}</span>
      </div>
      <ul class="facts">
        <li><b>${esc(blues.played)}</b><span>Played</span></li>
        <li><b>${esc(blues.won)}</b><span>Won</span></li>
        <li><b>${esc(blues.drawn)}</b><span>Drawn</span></li>
        <li><b>${esc(blues.lost)}</b><span>Lost</span></li>
      </ul>
      ${form.length ? `<div class="form" aria-label="${esc(formLabel)}">${form.map((letter) => `<span class="pill ${letter}">${letter}</span>`).join("")}</div><p class="form-label">Last five, newest on the right</p>` : ""}
    </section>
    ${nextBlock}
    ${lastBlock}
    ${topBlock}
    ${faGap ? `<p class="note"><strong>FA Cup.</strong> ${esc(faGap)}</p>` : ""}
    <p class="updated">Updated ${esc(season.updatedLabel)}. Not a live score app. The numbers are the saved copy in this site.</p>`;
}

function renderFixtures() {
  const upcoming = filtered(
    season.matches.filter((match) => match.status === "scheduled" || match.status === "postponed" || match.status === "live")
  );
  let body;
  if (!upcoming.length && filter === "cups") body = emptyCups();
  else if (!upcoming.length) body = `<div class="empty"><p>No fixtures are listed for this filter.</p></div>`;
  else body = groupedFixtures(upcoming);
  const notes = (season.competitions || [])
    .filter((item) => item.note)
    .map((item) => `<p class="note">${esc(item.note)}</p>`)
    .join("");
  const showNotes = !(filter === "cups" && !upcoming.length);
  return `<h2>Fixtures</h2>${filterBar()}${body}${showNotes ? notes : ""}<p class="updated">Kick-off times are UK time.</p>`;
}

function renderResults() {
  const played = filtered(
    season.matches.filter((match) => match.status === "finished" || match.status === "live")
  ).slice().reverse();
  const body = played.length
    ? played.map(resultCard).join("")
    : `<div class="empty"><p>No results are listed for this filter yet.</p></div>`;
  return `<h2>Results</h2>${filterBar()}<p class="table-hint">Tap a match for scorers, cards and stats.</p>${body}`;
}

function renderTable() {
  const rows = season.table.rows.map((row) => `
    <tr class="${row.isBlues ? "blues" : ""}">
      <td class="team"><span class="rank">${esc(row.rank)}</span> ${esc(row.team)}</td>
      <td>${esc(row.played)}</td>
      <td>${esc(row.points)}${row.deduction ? "*" : ""}</td>
      <td>${row.goalDifference > 0 ? "+" : ""}${esc(row.goalDifference)}</td>
      <td>${esc(row.won)}</td>
      <td>${esc(row.drawn)}</td>
      <td>${esc(row.lost)}</td>
      <td>${esc(row.goalsFor)}</td>
      <td>${esc(row.goalsAgainst)}</td>
    </tr>`).join("");
  const deductions = season.table.rows.filter((row) => row.deduction);
  const notes = deductions.map((row) => (
    `${esc(row.team)}'s total includes a ${esc(row.deduction)}-point deduction recorded by the source. The source does not say why.`
  )).join(" ");
  return `
    <h2>Championship</h2>
    <p class="table-hint">Birmingham are highlighted. Swipe sideways if you want wins and goals as well.</p>
    <div class="table-wrap">
      <table>
        <caption class="visually-hidden">Championship table, ${esc(season.season)}</caption>
        <thead>
          <tr>
            <th class="team">Club</th><th>P</th><th>Pts</th><th>GD</th><th>W</th><th>D</th><th>L</th><th>F</th><th>A</th>
          </tr>
        </thead>
        <tbody>${rows}</tbody>
      </table>
    </div>
    ${notes ? `<p class="note">${notes}</p>` : ""}
    <p class="updated">Table updated ${esc(season.updatedLabel)}.</p>`;
}

function renderScorers() {
  const scorers = season.seasonTotals.scorers || [];
  const list = scorers.length
    ? scorers.map((row) => {
      const competitions = Object.entries(row.byCompetition || {})
        .map(([name, goals]) => `${goals} ${name}`)
        .join(", ");
      const pens = row.penalties ? `, ${row.penalties} penalty${row.penalties === 1 ? "" : " penalties"}` : "";
      return `
        <article class="scorer">
          <div>
            <div class="name">${esc(row.player)}</div>
            <p class="sub">${esc(competitions)}${esc(pens)}</p>
          </div>
          <div class="count">${esc(row.goals)}</div>
        </article>`;
    }).join("")
    : `<div class="empty"><p>No Blues goals are stored yet.</p></div>`;
  const own = season.seasonTotals.ownGoalsForBlues || [];
  const ownBlock = own.length
    ? `<article class="note"><strong>Own goals for Blues.</strong> These are not added to a player's total. ${own.map((item) => `${esc(item.player || "Unnamed")}${item.club ? ` (${esc(item.club)})` : ""} ${esc(item.minute || "")} v ${esc(item.opponent)}`).join("; ")}.</article>`
    : "";
  const cards = (season.seasonTotals.cards || []).filter((row) => row.yellow || row.red).slice(0, 8);
  const cardBlock = cards.length
    ? `<h2>Yellow cards</h2>${cards.map((row) => `
        <article class="scorer">
          <div>
            <div class="name">${esc(row.player)}</div>
            <p class="sub">${row.red ? `${esc(row.red)} red` : "No red cards"}</p>
          </div>
          <div class="count">${esc(row.yellow)}</div>
        </article>`).join("")}`
    : "";
  const gaps = (season.gaps || []).map((gap) => `<p>${esc(gap)}</p>`).join("");
  const warnings = (season.warnings || []).map((warning) => `<p>${esc(warning)}</p>`).join("");
  return `
    <h2>Top scorers</h2>
    <p class="table-hint">Counted from the goals stored for this season. Own goals are left out of the list.</p>
    ${list}
    ${ownBlock}
    ${cardBlock}
    ${warnings ? `<h2>Please check</h2><article class="note">${warnings}</article>` : ""}
    <h2>What is not filled in</h2>
    <article class="note">${gaps || "<p>Nothing is flagged as missing.</p>"}</article>
    <p class="updated">Figures updated ${esc(season.updatedLabel)}.</p>`;
}

function render() {
  const view = viewFromHash();
  if (view !== currentView) {
    filter = "all";
    openMatches.clear();
    currentView = view;
  }
  document.querySelectorAll(".tabs a").forEach((link) => {
    const current = link.dataset.view === view;
    if (current) link.setAttribute("aria-current", "page");
    else link.removeAttribute("aria-current");
  });
  const pages = {
    home: renderHome,
    fixtures: renderFixtures,
    results: renderResults,
    table: renderTable,
    scorers: renderScorers,
  };
  app.innerHTML = pages[view]();
}

app.addEventListener("click", (event) => {
  const filterButton = event.target.closest("[data-filter]");
  if (filterButton) {
    filter = filterButton.dataset.filter;
    render();
    return;
  }
  const matchButton = event.target.closest("[data-match]");
  if (matchButton) {
    const id = matchButton.dataset.match;
    if (openMatches.has(id)) openMatches.delete(id);
    else openMatches.add(id);
    render();
    if (openMatches.has(id)) {
      const opened = app.querySelector(`[data-match="${CSS.escape(id)}"]`);
      opened?.closest("article")?.scrollIntoView({ block: "start" });
    }
  }
});

window.addEventListener("hashchange", render);

fetch("data/season.json", { cache: "no-cache" })
  .then((response) => {
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    return response.json();
  })
  .then((payload) => {
    season = payload;
    if (!location.hash) location.replace("#home");
    render();
  })
  .catch(() => {
    app.innerHTML = `<p class="error">The saved fixture list could not be loaded. If you just opened the file from your computer, use the link from GitHub Pages instead.</p>`;
  });
