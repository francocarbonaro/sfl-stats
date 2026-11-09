# SFL Stats

Standings and per-player stats for Street Fighter League (US / Americas, Japan, Europe / EMEAA), 2022 onward.

- `index.html` + `data.js` are the whole site (static, no server).
- `update.py` pulls results from the Liquipedia API and rebuilds `data.js`. Raw pages are kept in `cache/`, and only each league's newest season is re-downloaded.
- A GitHub Action runs it daily (`.github/workflows/update-data.yml`); it can also be started by hand from the Actions tab.

Data from [Liquipedia](https://liquipedia.net/fighters/Street_Fighter_League), licensed CC-BY-SA 3.0.
