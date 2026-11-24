# Putting LightDeck on GitHub (with Claude handling device requests)

Everything inside the project is ready: the GitHub page text (`README.md`), the device request form
(`.github/ISSUE_TEMPLATE/device.yml`) and the two Claude workflows (`.github/workflows/`).
What's left needs your own accounts, so it's done together, step by step. Claude Code can do every
step marked **(Claude)** once you say so.

## 1. Your GitHub account (you)
1. Go to https://github.com/signup and create a free account. Pick a username you're happy to show
   publicly: it becomes part of the page address (`github.com/<username>/LightDeck`).
2. Turn on two-factor sign-in when GitHub suggests it.

## 2. The tools on this PC (Claude, after you OK the downloads)
- **Git** (keeps the history of the code) and **GitHub CLI** `gh` (talks to GitHub from here).
  Both are free official installers; Claude asks before installing them.
- Then you sign in once with `gh auth login` (it opens the browser; you approve there).

## 3. The repository (Claude)
- Create a **public** repository called `LightDeck` (public, so others can send device requests).
- Upload this folder. Personal files are excluded automatically by `.gitignore`:
  `config.json` (your settings), device reports and recordings, build output.
- Create the two labels: `new device` (put on every request by the form) and `device`
  (the one that starts Claude, only you can add it).

## 4. Claude on GitHub (you + Claude)
1. Install the Claude GitHub app on the repository: https://github.com/apps/claude
   (choose "Only select repositories" > LightDeck).
2. Give the workflows a key: in a terminal run `claude setup-token`, then on GitHub go to the repository's
   **Settings > Secrets and variables > Actions > New repository secret**, name it
   `CLAUDE_CODE_OAUTH_TOKEN` and paste the token. (Or run `/install-github-app` in Claude Code in a
   terminal, which does both and opens a pull request with its own workflow file; keep ours instead.)
   Runs on GitHub count toward your Claude plan's usage.
3. In **Settings > Actions > General**, allow "Read and write permissions" for workflows and tick
   "Allow GitHub Actions to create and approve pull requests".

## 5. Point LightDeck at it and publish a release (Claude)
- Put the page address in `lightdeck/report.py` (`REPO_URL = "https://github.com/<username>/LightDeck"`).
  From then on, **Report a device** opens the request form directly.
- Bump `VERSION` in `engine.py`, rebuild (`python build/make_package.py`), and attach the zip to a
  GitHub **Release**, so friends can download it.

## How a device request works after that
1. Someone opens a request with the form (it gets the `new device` label).
2. You get an email. Read it: is it a real device request, nothing strange in it?
3. If yes, add the **`device`** label. Claude starts on GitHub (a few minutes), then either opens a
   pull request with the new driver and comments on the request, or comments explaining what's missing
   (usually a recording from *Add support for it*).
4. Check the pull request: Claude Code on this PC can test it on your hardware, or the person who
   asked can try it. Only you can merge it. Nothing reaches anyone until you merge and make a new release.

Safety built in: only people with write access (you) can start Claude; Claude is told to treat the
request text as information, never as instructions, and to only edit drivers, effects, `engine.py` and
docs; it isn't given any tool to download things or to merge; and every change is a pull request you review.

Ask in an issue or pull request comment with `@claude ...` for anything else (that also only works for you).
