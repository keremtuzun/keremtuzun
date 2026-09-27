"""Render the profile stat cards (assets/stats.svg, assets/languages.svg).

Only public, non-fork repositories are counted, so the cards look the same
whichever token runs this. Needs GITHUB_TOKEN (or GH_TOKEN) in the environment.
"""

import json
import os
import urllib.request
from html import escape
from pathlib import Path

USER = os.environ.get("PROFILE_USER", "keremtuzun")
OUT = Path(__file__).resolve().parent.parent / "assets"

QUERY = """
query($login: String!, $after: String) {
  user(login: $login) {
    id
    followers { totalCount }
    pullRequests(first: 100) { nodes { repository { isPrivate } } }
    repositories(first: 100, after: $after, ownerAffiliations: OWNER, privacy: PUBLIC, isFork: false) {
      pageInfo { hasNextPage endCursor }
      nodes {
        name
        stargazerCount
        languages(first: 10, orderBy: {field: SIZE, direction: DESC}) {
          edges { size node { name color } }
        }
      }
    }
  }
}
"""


def request(url, payload=None):
    token = os.environ.get("GITHUB_TOKEN") or os.environ["GH_TOKEN"]
    headers = {"Authorization": f"bearer {token}", "Content-Type": "application/json"}
    req = urllib.request.Request(url, data=json.dumps(payload).encode() if payload else None, headers=headers)
    with urllib.request.urlopen(req) as resp:
        return json.load(resp)


def graphql(variables):
    body = request("https://api.github.com/graphql", {"query": QUERY, "variables": variables})
    if "errors" in body:
        raise SystemExit(body["errors"])
    return body["data"]["user"]


COMMITS_QUERY = """
query($owner: String!, $name: String!, $author: ID!) {
  repository(owner: $owner, name: $name) {
    defaultBranchRef { target { ... on Commit { history(author: {id: $author}) { totalCount } } } }
  }
}
"""


def authored_commits(repo, user_id):
    # This account's contribution graph and search results come back empty,
    # so commits are counted straight from each repo's default branch.
    body = request(
        "https://api.github.com/graphql",
        {"query": COMMITS_QUERY, "variables": {"owner": USER, "name": repo, "author": user_id}},
    )
    ref = body["data"]["repository"]["defaultBranchRef"]
    return ref["target"]["history"]["totalCount"] if ref else 0


def collect():
    repos, after = [], None
    while True:
        user = graphql({"login": USER, "after": after})
        page = user["repositories"]
        repos += page["nodes"]
        if not page["pageInfo"]["hasNextPage"]:
            break
        after = page["pageInfo"]["endCursor"]

    langs = {}
    for repo in repos:
        for edge in repo["languages"]["edges"]:
            name = edge["node"]["name"]
            entry = langs.setdefault(name, {"size": 0, "color": edge["node"]["color"] or "#8b949e"})
            entry["size"] += edge["size"]

    return {
        "repos": len(repos),
        "stars": sum(r["stargazerCount"] for r in repos),
        "followers": user["followers"]["totalCount"],
        "commits": sum(authored_commits(r["name"], user["id"]) for r in repos),
        "prs": sum(not pr["repository"]["isPrivate"] for pr in user["pullRequests"]["nodes"]),
        "langs": sorted(langs.items(), key=lambda kv: -kv[1]["size"]),
    }


STYLE = """
  <style>
    .bg { fill: #ffffff; stroke: #d0d7de; }
    .title { fill: #0969da; font: 600 17px 'Segoe UI', Ubuntu, sans-serif; }
    .label { fill: #57606a; font: 400 13px 'Segoe UI', Ubuntu, sans-serif; }
    .value { fill: #1f2328; font: 600 13px 'Segoe UI', Ubuntu, sans-serif; }
    .foot { fill: #8c959f; font: 400 10px 'Segoe UI', Ubuntu, sans-serif; }
    @media (prefers-color-scheme: dark) {
      .bg { fill: #0d1117; stroke: #30363d; }
      .title { fill: #58a6ff; }
      .label { fill: #8b949e; }
      .value { fill: #e6edf3; }
      .foot { fill: #6e7681; }
    }
  </style>
"""

W, H = 400, 200


def card(title, body):
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" '
        f'role="img" aria-label="{escape(title)}">{STYLE}'
        f'<rect class="bg" x="0.5" y="0.5" width="{W - 1}" height="{H - 1}" rx="6"/>'
        f'<text class="title" x="24" y="36">{escape(title)}</text>{body}'
        f'<text class="foot" x="{W - 24}" y="{H - 12}" text-anchor="end">public repositories only</text>'
        "</svg>\n"
    )


def stats_svg(s):
    rows = [
        ("Public repositories", s["repos"]),
        ("Commits", s["commits"]),
        ("Pull requests", s["prs"]),
        ("Languages used", len(s["langs"])),
    ]
    body = "".join(
        f'<text class="label" x="24" y="{74 + i * 28}">{escape(label)}</text>'
        f'<text class="value" x="{W - 24}" y="{74 + i * 28}" text-anchor="end">{value:,}</text>'
        for i, (label, value) in enumerate(rows)
    )
    return card("GitHub activity", body)


def languages_svg(s, top=6):
    langs = s["langs"][:top]
    total = sum(v["size"] for _, v in langs) or 1
    bar, x = [], 24.0
    width = W - 48
    for name, v in langs:
        w = width * v["size"] / total
        bar.append(f'<rect x="{x:.2f}" y="52" width="{w:.2f}" height="8" fill="{v["color"]}"/>')
        x += w
    bar_group = (
        '<clipPath id="r"><rect x="24" y="52" width="%d" height="8" rx="4"/></clipPath>'
        '<g clip-path="url(#r)">%s</g>' % (width, "".join(bar))
    )
    items = []
    for i, (name, v) in enumerate(langs):
        cx = 24 + (i % 2) * (width / 2)
        cy = 90 + (i // 2) * 26
        pct = 100 * v["size"] / total
        items.append(
            f'<circle cx="{cx + 5}" cy="{cy - 4}" r="5" fill="{v["color"]}"/>'
            f'<text class="label" x="{cx + 16}" y="{cy}">{escape(name)}</text>'
            f'<text class="value" x="{cx + width / 2 - 16}" y="{cy}" text-anchor="end">{pct:.1f}%</text>'
        )
    return card("Most used languages", bar_group + "".join(items))


def main():
    s = collect()
    OUT.mkdir(exist_ok=True)
    (OUT / "stats.svg").write_text(stats_svg(s))
    (OUT / "languages.svg").write_text(languages_svg(s))
    print(json.dumps({k: v for k, v in s.items() if k != "langs"}), [n for n, _ in s["langs"][:6]])


if __name__ == "__main__":
    main()
