#!/usr/bin/env bash
# Publish the website to GitHub Pages: build site/ (pipeline/build_site.py) and force-push it as the only commit of
# the gh-pages branch, so the rebuilt data files (~16 MB a build) never pile up in the repository's history.
#
#   bash pipeline/deploy_site.sh [--url https://civilwar.petertuuk.com/ --cname civilwar.petertuuk.com]
#
# Run from Git Bash (Windows) or any shell with git, python and push access to origin. Then, once: GitHub repository
# Settings > Pages > Source: "Deploy from a branch", branch gh-pages, folder / (root).
set -euo pipefail
cd "$(dirname "$0")/.."
PY=$(command -v python3 || command -v python)
"$PY" pipeline/build_site.py site "$@"
remote=$(git remote get-url origin)
rev=$(git rev-parse --short HEAD)
dirty=$(git status --porcelain -- viewer pipeline | head -1)
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
cp -r site/. "$tmp"/
cd "$tmp"
git init -q -b gh-pages
git add -A
git -c user.name="$(git -C "$OLDPWD" log -1 --format=%an)" -c user.email="$(git -C "$OLDPWD" log -1 --format=%ae)" \
  commit -q -m "Site build $(date -u +%Y-%m-%d) from ${rev}${dirty:+ (with uncommitted changes)}"
git push -f "$remote" gh-pages
echo "deployed ${rev} to gh-pages"
