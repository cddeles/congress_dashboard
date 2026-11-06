# The Congress — automatically updated dashboard

This is a static website with a scheduled data pipeline. It is designed to run on GitHub Pages without a paid backend or database.

## What updates automatically

- **Current member roster, party, chamber, state/district, current terms, and official portraits:** Congress.gov API v3.
- **Committee assignments, committee chair/ranking-member titles, committee metadata, caucus information, and extra term details:** the public `unitedstates/congress-legislators` structured dataset. Its committee membership is maintained from official House and Senate committee pages, but it is a supplemental/community-maintained source rather than a Congress.gov assignment endpoint.
- **House and Senate party leadership:** extracted from the official House Clerk and Senate leadership pages during each synchronization.

All people are joined using their Bioguide ID, not name alone. The sync script validates the size of the roster, committee dataset, and leadership extraction before writing a new file. If a source changes unexpectedly or data is incomplete, the job fails and the last successfully published `data/congress.json` remains in place.

## One-time setup (about 10–15 minutes)

### 1. Get the free Congress.gov API key

1. Open <https://api.congress.gov/sign-up/>.
2. Complete the API key signup (it is issued through api.data.gov).
3. Verify the email if prompted and copy the key.
4. Keep it private. Do not paste it into `index.html`, commit it to this repository, or send it in a message.

Only one API key is required. The supplemental JSON datasets and official leadership pages are public and do not need keys.

### 2. Put these files in a GitHub repository

1. Sign in at <https://github.com/> and create a new repository, for example `congress-dashboard`.
2. Extract the ZIP you downloaded.
3. Upload the *contents* of the extracted folder to the top level of the repository. The top level should contain `index.html`, `scripts/`, `.github/`, `data/`, and `requirements.txt`.
4. For GitHub Pages, make the repository public unless your GitHub plan supports Pages for a private repository.

### 3. Store the API key safely in GitHub

1. Open the repository's **Settings**.
2. Select **Secrets and variables → Actions**.
3. Select **New repository secret**.
4. Enter this exact name: `CONGRESS_API_KEY`.
5. Paste your Congress.gov key as the value and save.

This stores the key as an encrypted GitHub Actions secret. The automated script can use it, but the browser-facing HTML and published JSON never contain it.

### 4. Allow the updater to publish its result

1. In repository **Settings → Actions → General**, find **Workflow permissions**.
2. Select **Read and write permissions** and save.
3. Open the **Actions** tab.
4. Select **Update Congress data**.
5. Select **Run workflow** to perform the first synchronization.
6. Open the run and confirm the final steps show a successful data sync and publish.

The workflow checks the sources every six hours (UTC), and it can also be started manually from the Actions tab. GitHub may delay scheduled runs during busy periods.

### 5. Publish the website

1. Open repository **Settings → Pages**.
2. Under **Build and deployment**, choose **Deploy from a branch**.
3. Select branch `main` and folder `/(root)`, then save.
4. GitHub will show the website address, usually `https://YOUR-USERNAME.github.io/congress-dashboard/`.
5. Open that address. The page reads `data/congress.json` from the same website.

### 6. Local preview (optional)

To preview from your computer, open a terminal in the extracted project folder and run:

```bash
python -m http.server 8000
```

Then open <http://localhost:8000>. Use a local web server rather than double-clicking `index.html`, because browsers often block local-file JSON requests.

To run a data sync locally, install the dependencies and set `CONGRESS_API_KEY` as an environment variable (do not add it to source control):

```bash
python -m pip install -r requirements.txt
# macOS / Linux:
export CONGRESS_API_KEY="paste-your-key-here"
# Windows PowerShell:
# $env:CONGRESS_API_KEY="paste-your-key-here"
python scripts/sync_data.py
```

## How refresh works

- The **Refresh data** button in the browser reloads the latest published snapshot.
- GitHub Actions performs the API/source synchronization every six hours. To force a fresh source check, run **Actions → Update Congress data → Run workflow**.
- When the snapshot changes, the workflow commits the updated `data/congress.json`; GitHub Pages then serves it like any other static file.

## Important accuracy notes

- No public source is guaranteed to update instantly. Congress.gov, the supplemental committee dataset, and official web pages may reflect changes at different times.
- Committee assignments are not available as a simple member-assignment endpoint in the Congress.gov v3 API documentation, so the supplemental committee dataset fills that gap.
- Leadership is parsed from official web pages. If the House or Senate changes the page structure, validation intentionally fails rather than publishing a misleading empty leadership list. The parser may need an adjustment if those sites redesign their pages.
- This is intentionally a low-maintenance, serverless-style setup, not a promise of zero maintenance. Check the GitHub Actions tab occasionally for failed runs, especially after official data-source changes.
- Vacancies are calculated from 435 authorized voting House seats and 100 Senate seats. Non-voting delegates and the resident commissioner are listed separately.
- The public snapshot contains public congressional information. Never put API keys, credentials, or private data in `data/congress.json`.

## Data and technical references

- Congress.gov API: <https://api.congress.gov/>
- Congress.gov API key signup: <https://api.congress.gov/sign-up/>
- Congress.gov member endpoint docs: <https://github.com/LibraryOfCongress/api.congress.gov/blob/main/Documentation/MemberEndpoint.md>
- Congress.gov committee endpoint docs: <https://github.com/LibraryOfCongress/api.congress.gov/blob/main/Documentation/CommitteeEndpoint.md>
- Supplemental dataset and field definitions: <https://github.com/unitedstates/congress-legislators>
- Official House leadership: <https://clerk.house.gov/Members/ViewLeadership>
- Official Senate leadership: <https://www.senate.gov/senators/leadership.htm>
- GitHub scheduled workflow docs: <https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax#onschedule>
