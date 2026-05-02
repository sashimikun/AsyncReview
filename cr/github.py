"""GitHub PR ingestion for Part 2."""

import os
import re
import subprocess
import uuid
from pathlib import Path
from datetime import datetime

import httpx

from .config import CR_CACHE_DIR, GITHUB_TOKEN, GITHUB_API_BASE
from .diff_types import PRInfo, FileContents, DiffFileContext


# In-memory store for loaded PRs (MVP - no persistence)
_pr_cache: dict[str, PRInfo] = {}


def parse_pr_url(url: str) -> tuple[str, str, int]:
    """Parse a GitHub PR URL into (owner, repo, number).
    
    Args:
        url: GitHub PR URL like https://github.com/owner/repo/pull/123
        
    Returns:
        Tuple of (owner, repo, pr_number)
        
    Raises:
        ValueError: If URL format is invalid
    """
    pattern = r"github\.com/([^/]+)/([^/]+)/pull/(\d+)"
    match = re.search(pattern, url)
    if not match:
        raise ValueError(f"Invalid GitHub PR URL: {url}")
    return match.group(1), match.group(2), int(match.group(3))


def _get_headers() -> dict[str, str]:
    """Get HTTP headers for GitHub API requests."""
    headers = {
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "cr-review-tool",
    }
    if GITHUB_TOKEN:
        headers["Authorization"] = f"token {GITHUB_TOKEN}"
    return headers


async def _fetch_all_pages(client: httpx.AsyncClient, url: str, headers: dict, params: dict | None = None) -> list[dict]:
    """Fetch all pages from a paginated GitHub API endpoint."""
    all_items = []
    page = 1
    params = params.copy() if params else {}
    params["per_page"] = 100
    params["page"] = page

    while True:
        resp = await client.get(url, headers=headers, params=params, timeout=30.0)

        # Handle 404/Empty gracefully if needed, but for list endpoints 200 is expected
        if resp.status_code == 404:
            return []

        resp.raise_for_status()
        items = resp.json()

        if not items:
            break

        all_items.extend(items)

        # If we got fewer than per_page items, we've reached the end
        if len(items) < 100:
            break

        page += 1
        params["page"] = page

    return all_items


async def load_pr(pr_url: str) -> PRInfo:
    """Load PR metadata from GitHub.
    
    Args:
        pr_url: GitHub PR URL
        
    Returns:
        PRInfo with metadata and file list
    """
    owner, repo, number = parse_pr_url(pr_url)
    review_id = str(uuid.uuid4())[:8]
    
    async with httpx.AsyncClient() as client:
        # Fetch PR metadata
        pr_resp = await client.get(
            f"{GITHUB_API_BASE}/repos/{owner}/{repo}/pulls/{number}",
            headers=_get_headers(),
            timeout=30.0,
        )
        pr_resp.raise_for_status()
        pr_data = pr_resp.json()
        
        # Fetch changed files
        files_data = await _fetch_all_pages(
            client,
            f"{GITHUB_API_BASE}/repos/{owner}/{repo}/pulls/{number}/files",
            _get_headers(),
        )
    
        # Fetch commits
        commits_data = await _fetch_all_pages(
            client,
            f"{GITHUB_API_BASE}/repos/{owner}/{repo}/pulls/{number}/commits",
            _get_headers(),
        )

        commits_list = [
            {
                "sha": c["sha"],
                "message": c["commit"]["message"],
                "author": {
                    "name": c["commit"]["author"]["name"],
                    "date": c["commit"]["author"]["date"],
                    "login": c["author"]["login"] if c.get("author") else None,
                    "avatar_url": c["author"]["avatar_url"] if c.get("author") else None,
                },
                "html_url": c["html_url"],
            }
            for c in commits_data
        ]

        # Fetch comments (using issue comments for main conversation)
        comments_data = await _fetch_all_pages(
            client,
            f"{GITHUB_API_BASE}/repos/{owner}/{repo}/issues/{number}/comments",
            _get_headers(),
        )

        comments_list = [
             {
                 "id": c["id"],
                 "user": {
                     "login": c["user"]["login"],
                     "avatar_url": c["user"]["avatar_url"],
                 },
                 "body": c["body"],
                 "created_at": c["created_at"],
                 "html_url": c["html_url"],
             }
             for c in comments_data
         ]

    files = [
        {
             "path": f["filename"],
             "status": f.get("status", "modified"),
             "additions": f.get("additions", 0),
             "deletions": f.get("deletions", 0),
             "patch": f.get("patch"),
        }
        for f in files_data
    ]
    
    pr_info = PRInfo(
        review_id=review_id,
        owner=owner,
        repo=repo,
        number=number,
        title=pr_data.get("title", ""),
        body=pr_data.get("body") or "",
        base_sha=pr_data["base"]["sha"],
        head_sha=pr_data["head"]["sha"],
        files=files,
        created_at=datetime.now(),
        user={"login": pr_data["user"]["login"], "avatar_url": pr_data["user"]["avatar_url"]},
        state=pr_data.get("state", "open"),
        draft=pr_data.get("draft", False),
        head_ref=pr_data["head"]["ref"],
        base_ref=pr_data["base"]["ref"],
        commits=pr_data.get("commits", 0),
        additions=pr_data.get("additions", 0),
        deletions=pr_data.get("deletions", 0),
        changed_files=pr_data.get("changed_files", 0),
        commits_list=commits_list,
        comments=comments_list,
    )
    
    # Cache for later file fetching
    _pr_cache[review_id] = pr_info
    
    return pr_info


def get_cached_pr(review_id: str) -> PRInfo | None:
    """Get a cached PR by review ID."""
    return _pr_cache.get(review_id)


async def get_file_contents(
    review_id: str,
    path: str,
) -> tuple[FileContents | None, FileContents | None]:
    """Get old and new file contents for a file in a PR.
    
    Args:
        review_id: The review ID from load_pr
        path: File path within the repo
        
    Returns:
        Tuple of (old_file, new_file) - either can be None for added/deleted files
    """
    pr_info = _pr_cache.get(review_id)
    if not pr_info:
        raise ValueError(f"Review {review_id} not found")
    
    owner, repo = pr_info.owner, pr_info.repo
    base_sha, head_sha = pr_info.base_sha, pr_info.head_sha
    
    async with httpx.AsyncClient() as client:
        async def _fetch_content(ref: str) -> str | None:
            # 1. Try raw content (fastest)
            try:
                resp = await client.get(
                    f"{GITHUB_API_BASE}/repos/{owner}/{repo}/contents/{path}",
                    headers={**_get_headers(), "Accept": "application/vnd.github.v3.raw"},
                    params={"ref": ref},
                    timeout=30.0,
                )
                if resp.status_code == 200:
                    return resp.text
                elif resp.status_code == 404:
                    return None
                # If 403 or other error, fall through to fallback
            except Exception:
                pass

            # 2. Fallback: Get metadata to find SHA, then fetch blob (handles large files > 1MB)
            try:
                # Get file metadata
                meta_resp = await client.get(
                    f"{GITHUB_API_BASE}/repos/{owner}/{repo}/contents/{path}",
                    headers=_get_headers(),  # Default JSON
                    params={"ref": ref},
                    timeout=30.0,
                )
                if meta_resp.status_code == 404:
                    return None

                meta_resp.raise_for_status()
                data = meta_resp.json()

                # If content is present (small file), use it
                if data.get("content"):
                    import base64
                    return base64.b64decode(data["content"]).decode("utf-8", errors="replace")

                # If content is missing (large file), use sha to fetch blob
                sha = data.get("sha")
                if sha:
                    blob_resp = await client.get(
                        f"{GITHUB_API_BASE}/repos/{owner}/{repo}/git/blobs/{sha}",
                        headers=_get_headers(),
                        timeout=30.0,
                    )
                    blob_resp.raise_for_status()
                    blob_data = blob_resp.json()
                    import base64
                    return base64.b64decode(blob_data["content"]).decode("utf-8", errors="replace")
            except Exception:
                pass

            return None

        # Fetch base version
        old_content = await _fetch_content(base_sha)
        old_file = FileContents(
            name=path,
            contents=old_content,
            cache_key=f"{owner}/{repo}/{base_sha}/{path}",
        ) if old_content is not None else None

        # Fetch head version
        new_content = await _fetch_content(head_sha)
        new_file = FileContents(
            name=path,
            contents=new_content,
            cache_key=f"{owner}/{repo}/{head_sha}/{path}",
        ) if new_content is not None else None
    
    return old_file, new_file

