"""Situation Monitor tab tools: log_idea/log_bug/list/resolve for the Ideas +
Bugs panel, and track/untrack/list for which GitHub repos back the Shipping
Log panel. Tracked repos are settings rows the same way
tracking.py stores tracked URLs — the key is "owner/name", the
value is a display label, category is fixed to SHIPPING_REPO_CATEGORY.
"""

from edith.memory.records import planning, system
from edith.tools.base import ToolContext, tool

SHIPPING_REPO_CATEGORY = "shipping_repo"
SHIPPING_ACCOUNT_CATEGORY = "shipping_account"
VERCEL_PROJECT_CATEGORY = "vercel_project"


def _log(ctx: ToolContext, kind: str, title: str, project: str, note: str) -> str:
    item_id = planning.create_idea_bug(ctx.conn, kind, title, note or None, project or None)
    return f"Logged {kind} #{item_id}: {title}"


@tool
def log_idea(ctx: ToolContext, title: str, project: str = "", note: str = "") -> str:
    """Log a product/feature idea to the Situation Monitor dashboard's Ideas + Bugs panel.
    Call this when the user mentions an idea they want to remember or come back to later.

    Args:
        project: Optional project/product this belongs to
        note: Optional extra detail
    """
    return _log(ctx, "idea", title, project, note)


@tool
def log_bug(ctx: ToolContext, title: str, project: str = "", note: str = "") -> str:
    """Log a bug to the Situation Monitor dashboard's Ideas + Bugs panel. Call this when the
    user reports something broken and wants it tracked.

    Args:
        project: Optional project/product this belongs to
        note: Optional extra detail
    """
    return _log(ctx, "bug", title, project, note)


@tool
def list_ideas_bugs(ctx: ToolContext, kind: str = "", status: str = "open") -> str:
    """List logged ideas/bugs from the Situation Monitor dashboard. Defaults to open items only.

    Args:
        kind: Optional: idea or bug
        status: Optional: open or resolved (default open)
    """
    items = planning.list_ideas_bugs(ctx.conn, kind or None, status or None)
    if not items:
        return "Nothing logged yet."
    lines = []
    for i in items:
        tag = f"[{i['project']}] " if i["project"] else ""
        lines.append(f"#{i['id']} ({i['kind']}) {tag}{i['title']}")
    return "\n".join(lines)


@tool
def resolve_idea_bug(ctx: ToolContext, item_id: int) -> str:
    """Mark a logged idea or bug as resolved, given its id."""
    ok = planning.resolve_idea_bug(ctx.conn, item_id)
    return f"Marked #{item_id} resolved." if ok else f"No idea/bug with id {item_id}."


@tool
def track_shipping_repo(ctx: ToolContext, repo: str, label: str = "") -> str:
    """Add a GitHub repo to the Situation Monitor dashboard's Shipping Log panel, which shows
    its recent commits. Call when the user names a repo/project they want to see ship activity for.

    Args:
        repo: 'owner/name', e.g. 'techwarq/edith'
        label: Optional display name, defaults to the repo path
    """
    system.set_setting(ctx.conn, key=repo, value=label or repo, category=SHIPPING_REPO_CATEGORY)
    return f"Now tracking {repo} in the shipping log."


@tool
def untrack_shipping_repo(ctx: ToolContext, repo: str) -> str:
    """Stop showing a repo's commits in the Shipping Log panel."""
    removed = system.delete_setting(ctx.conn, repo)
    return f"Stopped tracking {repo}." if removed else f"{repo} wasn't being tracked."


@tool
def list_shipping_repos(ctx: ToolContext) -> str:
    """List every repo currently tracked in the Shipping Log panel."""
    facts = system.list_settings(ctx.conn, SHIPPING_REPO_CATEGORY)
    if not facts:
        return "No repos are being tracked in the shipping log yet."
    return "\n".join(f"{f['key']} ({f['value']})" for f in facts)


@tool
def track_shipping_account(ctx: ToolContext, username: str, label: str = "") -> str:
    """Track an entire GitHub account/username in the Shipping Log panel — pulls recent public
    commits across ALL of that user's repos automatically, each one tagged with the repo it
    came from. Use this instead of track_shipping_repo when the user wants everything they
    ship tracked without naming each repo individually (e.g. 'track my GitHub, techwarq').

    Args:
        username: GitHub username, e.g. 'techwarq'
        label: Optional display name, defaults to the username
    """
    system.set_setting(ctx.conn, key=username, value=label or username, category=SHIPPING_ACCOUNT_CATEGORY)
    return f"Now tracking all of {username}'s public GitHub activity in the Shipping Log — every commit tagged with its repo automatically."


@tool
def untrack_shipping_account(ctx: ToolContext, username: str) -> str:
    """Stop tracking a GitHub account's activity in the Shipping Log panel."""
    removed = system.delete_setting(ctx.conn, username)
    return f"Stopped tracking {username}." if removed else f"{username} wasn't being tracked."


@tool
def list_shipping_accounts(ctx: ToolContext) -> str:
    """List every GitHub account currently tracked in the Shipping Log panel."""
    facts = system.list_settings(ctx.conn, SHIPPING_ACCOUNT_CATEGORY)
    if not facts:
        return "No GitHub accounts are being tracked in the shipping log yet."
    return "\n".join(f["key"] for f in facts)


@tool
def track_vercel_project(ctx: ToolContext, project_id: str, label: str = "") -> str:
    """Add a Vercel project to the Situation Monitor dashboard's Analytics panel, which shows
    its pageviews. Call when the user names an app/project they want visitor stats tracked for.

    Args:
        project_id: Vercel project ID, e.g. 'prj_abc123'
        label: Optional display name, defaults to the project id
    """
    system.set_setting(ctx.conn, key=project_id, value=label or project_id, category=VERCEL_PROJECT_CATEGORY)
    return f"Now tracking {label or project_id} ({project_id}) in the Analytics panel."


@tool
def untrack_vercel_project(ctx: ToolContext, project_id: str) -> str:
    """Stop showing a Vercel project's pageviews in the Analytics panel."""
    removed = system.delete_setting(ctx.conn, project_id)
    return f"Stopped tracking {project_id}." if removed else f"{project_id} wasn't being tracked."


@tool
def list_vercel_projects(ctx: ToolContext) -> str:
    """List every Vercel project currently tracked in the Analytics panel."""
    facts = system.list_settings(ctx.conn, VERCEL_PROJECT_CATEGORY)
    if not facts:
        return "No Vercel projects are being tracked in the Analytics panel yet."
    return "\n".join(f"{f['value']} ({f['key']})" for f in facts)
