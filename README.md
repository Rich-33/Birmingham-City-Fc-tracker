# Blues tracker

A phone-friendly page of Birmingham City fixtures, results, match stats and the Championship table for the 2026/27 season.

It is an unofficial fan page. It is not run by the club. The colours are royal blue and white so it is easy to spot on a phone.

The page does not call a live feed while you are looking at it. The numbers are saved in this project, in `data/season.json`, and a free automatic job on GitHub refreshes that file. Old results stay in the file, so the record builds up even if a website later drops them.

## Look at it on your phone

After the one-time setup below, open this address in Chrome:

**https://rich-33.github.io/Birmingham-City-Fc-tracker/**

To keep it on your home screen: tap the three dots in Chrome, then **Add to Home screen**. It opens like a small app. It is built for a phone first (Richard uses a Galaxy S24 Ultra). On a computer it sits in a narrow column.

Kick-off times are UK time, summer and winter.

## What you can see

- **Home.** League place, points, the next match and the last result.
- **Fixtures.** Every Championship game still to come, with the date, UK kick-off, opponent, home or away, and the competition. Cup ties show here too once they exist.
- **Results.** Scores for games already played. Tap a match for scorers, cards, possession, shots and the other stats that were published.
- **Table.** The Championship table. Birmingham’s row is highlighted. Swipe sideways to see every column.
- **Scorers.** Blues goalscorers this season, counted from the goals on the match list, plus yellow cards.

## What is filled in, and what is left blank

Filled in from real published figures:

- All 46 Championship fixtures for 2026/27.
- League results that have already been played, with the score, scorers and team stats.
- Carabao Cup ties that have been played (also called the EFL Cup). Birmingham’s two ties this season are Swansea City away and Brentford at home.
- The Championship table, including Southampton’s points deduction. The feed records the deduction. It does not say why, so the page does not guess.

Left blank on purpose:

- **FA Cup.** No 2026/27 tie for Birmingham had been published when this was last built. The page says so. It will appear after a later update, once the source lists it.
- **Attendance** on a handful of matches. The source had no crowd figure, so those rows say it was not published. A zero is not shown in its place.
- **Live minute-by-minute scores.** This is not a live score app. A finished game shows up after the next update.

Nothing on the page is an invented score, fixture or statistic. If a figure is missing, the page says so.

## Where the numbers come from

Two free sources, neither of which needs an account or a key:

1. **ESPN’s public football feed.** Fixtures, UK kick-off times, results, scorers, match stats and the Championship table. No API key.
2. **openfootball’s public fixture list.** Championship matchday numbers only (Matchday 1, Matchday 2, and so on). Scores from that list are not used, because it can lag behind.

A paid feed was not needed. [football-data.org](https://www.football-data.org/) has a free tier with a key, but it was not required, because the ESPN feed already covers this season. You do **not** need to create a key or add a secret.

## How the page stays up to date

A GitHub Action (an automatic job) runs twice a day, at about 7:30am and 10:45pm UK time in winter, and an hour later in British Summer Time. GitHub sometimes starts these a bit late.

The job downloads the latest figures, checks they still add up, and saves `data/season.json` only when something has changed. If the download fails, it leaves the previous file alone, so the page keeps the last good numbers.

You can also run it yourself: open the **Actions** tab, choose **Update Blues data**, then **Run workflow**.

When the season rolls over, the old file is copied into `data/history` before the new season replaces it.

## One-time setup

You only do this once, after merging the pull request. No install, no account with a data company, and no API key.

### 1. Merge the pull request

Open the pull request and press **Merge**. The site and the saved results are in that merge.

### 2. Turn on GitHub Pages

1. Open the repository on GitHub.
2. Go to **Settings**, then **Pages**.
3. Under **Build and deployment**, set **Source** to **Deploy from a branch**.
4. Set the branch to **main** and the folder to **/ (root)**.
5. Press **Save**.

Wait a couple of minutes, then open:

https://rich-33.github.io/Birmingham-City-Fc-tracker/

The repository needs to be public. GitHub Pages is free for a public repository.

### 3. Let the automatic job save new results

The daily job has to be allowed to write the updated file back into the repository.

1. Go to **Settings**, then **Actions**, then **General**.
2. Under **Workflow permissions**, choose **Read and write permissions**.
3. Press **Save**.

If GitHub asks you to enable Actions the first time you open the **Actions** tab, allow them.

### 4. Optional: fetch today’s numbers straight away

You do not have to wait until the next morning. Open **Actions**, choose **Update Blues data**, and press **Run workflow**.

The figures already saved in the merge are enough for the page to work before that first run.

## If something looks wrong

- The page is blank or missing its styling: give Pages another minute, then refresh. Use the `github.io` address, not a downloaded copy of the files.
- The automatic job has a red cross: the site is still showing the last saved file. Open the failed job and read the message. A failed download does not wipe the results.
- A kick-off time moves because the game is on television: the next update picks up the new time from ESPN.
