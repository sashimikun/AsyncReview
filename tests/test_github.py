"""Tests for GitHub PR ingestion module."""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock
import httpx

from cr.github import parse_pr_url, load_pr, get_file_contents, get_cached_pr, _pr_cache
from cr.diff_types import PRInfo, FileContents


class TestParsePrUrl:
    """Tests for parse_pr_url function."""

    def test_valid_url(self):
        """Test parsing a valid GitHub PR URL."""
        owner, repo, number = parse_pr_url("https://github.com/AsyncFuncAI/deepwiki-open/pull/448")
        assert owner == "AsyncFuncAI"
        assert repo == "deepwiki-open"
        assert number == 448

    def test_valid_url_with_trailing_slash(self):
        """Test parsing URL with trailing content."""
        owner, repo, number = parse_pr_url("https://github.com/owner/repo/pull/123/files")
        assert owner == "owner"
        assert repo == "repo"
        assert number == 123

    def test_valid_url_without_https(self):
        """Test parsing URL without https prefix."""
        owner, repo, number = parse_pr_url("github.com/owner/repo/pull/99")
        assert owner == "owner"
        assert repo == "repo"
        assert number == 99

    def test_invalid_url_no_pull(self):
        """Test invalid URL without /pull/."""
        with pytest.raises(ValueError, match="Invalid GitHub PR URL"):
            parse_pr_url("https://github.com/owner/repo/issues/123")

    def test_invalid_url_no_number(self):
        """Test invalid URL without PR number."""
        with pytest.raises(ValueError, match="Invalid GitHub PR URL"):
            parse_pr_url("https://github.com/owner/repo/pull/")

    def test_invalid_url_completely_wrong(self):
        """Test completely invalid URL."""
        with pytest.raises(ValueError, match="Invalid GitHub PR URL"):
            parse_pr_url("https://gitlab.com/owner/repo/merge_requests/1")


class TestLoadPr:
    """Tests for load_pr function."""

    @pytest.fixture
    def mock_pr_response(self):
        """Mock GitHub PR API response."""
        return {
            "title": "Add new feature",
            "body": "This PR adds a cool feature",
            "base": {"sha": "abc123base", "ref": "main"},
            "head": {"sha": "def456head", "ref": "feature-branch"},
            "user": {"login": "testuser", "avatar_url": "https://example.com/avatar"},
            "state": "open",
            "draft": False,
            "commits": 1,
            "additions": 10,
            "deletions": 5,
            "changed_files": 2,
        }

    @pytest.fixture
    def mock_files_response(self):
        """Mock GitHub PR files API response."""
        return [
            {
                "filename": "src/main.py",
                "status": "modified",
                "additions": 10,
                "deletions": 5,
                "patch": "@@ -1,5 +1,10 @@\n+new line",
            },
            {
                "filename": "tests/test_main.py",
                "status": "added",
                "additions": 25,
                "deletions": 0,
            },
        ]

    @pytest.mark.asyncio
    async def test_load_pr_success(self, mock_pr_response, mock_files_response):
        """Test successful PR loading."""
        # Clear cache
        _pr_cache.clear()
        
        with patch("cr.github.httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client_class.return_value.__aenter__.return_value = mock_client
            
            # Mock responses
            pr_resp = MagicMock()
            pr_resp.json.return_value = mock_pr_response
            pr_resp.raise_for_status = MagicMock()
            
            files_resp = MagicMock()
            files_resp.json.return_value = mock_files_response
            files_resp.raise_for_status = MagicMock()
            
            # Mock commits response
            commits_resp = MagicMock()
            commits_resp.status_code = 200
            commits_resp.json.return_value = []

            # Mock comments response
            comments_resp = MagicMock()
            comments_resp.status_code = 200
            comments_resp.json.return_value = []

            mock_client.get = AsyncMock(side_effect=[pr_resp, files_resp, commits_resp, comments_resp])

            pr_info = await load_pr("https://github.com/test/repo/pull/42")
            
            assert pr_info.owner == "test"
            assert pr_info.repo == "repo"
            assert pr_info.number == 42
            assert pr_info.title == "Add new feature"
            assert pr_info.body == "This PR adds a cool feature"
            assert pr_info.base_sha == "abc123base"
            assert pr_info.head_sha == "def456head"
            assert len(pr_info.files) == 2
            assert pr_info.files[0]["path"] == "src/main.py"
            assert pr_info.files[0]["status"] == "modified"
            
            # Check it's cached
            cached = get_cached_pr(pr_info.review_id)
            assert cached is not None
            assert cached.owner == "test"

    @pytest.mark.asyncio
    async def test_load_pr_pagination(self, mock_pr_response):
        """Test that load_pr correctly handles pagination for files."""
        # Mock Files response - Page 1 (100 files)
        mock_files_page1 = [
            {"filename": f"file_{i}.txt", "status": "added"} for i in range(100)
        ]
        # Mock Files response - Page 2 (50 files)
        mock_files_page2 = [
            {"filename": f"file_{i}.txt", "status": "added"} for i in range(100, 150)
        ]

        with patch("cr.github.httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client_class.return_value.__aenter__.return_value = mock_client

            # Responses
            pr_resp = MagicMock()
            pr_resp.json.return_value = mock_pr_response
            pr_resp.raise_for_status = MagicMock()

            files_resp1 = MagicMock()
            files_resp1.json.return_value = mock_files_page1
            files_resp1.raise_for_status = MagicMock()

            files_resp2 = MagicMock()
            files_resp2.json.return_value = mock_files_page2
            files_resp2.raise_for_status = MagicMock()

            commits_resp = MagicMock()
            commits_resp.status_code = 200
            commits_resp.json.return_value = []

            comments_resp = MagicMock()
            comments_resp.status_code = 200
            comments_resp.json.return_value = []

            mock_client.get = AsyncMock(side_effect=[
                pr_resp, files_resp1, files_resp2, commits_resp, comments_resp
            ])

            pr_info = await load_pr("https://github.com/owner/repo/pull/1")
            assert len(pr_info.files) == 150


class TestGetFileContents:
    """Tests for get_file_contents function."""

    @pytest.mark.asyncio
    async def test_get_file_contents_modified(self):
        """Test getting contents for a modified file."""
        # Setup cache with mock PR
        review_id = "test123"
        _pr_cache[review_id] = PRInfo(
            review_id=review_id,
            owner="test",
            repo="repo",
            number=1,
            title="Test PR",
            body="",
            base_sha="base_sha",
            head_sha="head_sha",
            files=[],
        )
        
        with patch("cr.github.httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client_class.return_value.__aenter__.return_value = mock_client
            
            base_resp = MagicMock()
            base_resp.status_code = 200
            base_resp.text = "old content"
            
            head_resp = MagicMock()
            head_resp.status_code = 200
            head_resp.text = "new content"
            
            mock_client.get = AsyncMock(side_effect=[base_resp, head_resp])
            
            old_file, new_file = await get_file_contents(review_id, "src/main.py")
            
            assert old_file is not None
            assert old_file.contents == "old content"
            assert new_file is not None
            assert new_file.contents == "new content"

    @pytest.mark.asyncio
    async def test_get_file_contents_not_found_review(self):
        """Test error when review ID not found."""
        with pytest.raises(ValueError, match="Review .* not found"):
            await get_file_contents("nonexistent", "file.py")

    @pytest.mark.asyncio
    async def test_get_file_contents_large_file(self):
        """Test getting contents for a large file (fallback to blob)."""
        review_id = "test_large"
        _pr_cache[review_id] = PRInfo(
            review_id=review_id,
            owner="test",
            repo="repo",
            number=1,
            title="Test PR",
            body="",
            base_sha="base_sha",
            head_sha="head_sha",
            files=[],
            commits=0, additions=0, deletions=0, changed_files=0,
            commits_list=[], comments=[],
            created_at=None, user={}, head_ref="head", base_ref="base"
        )

        with patch("cr.github.httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client_class.return_value.__aenter__.return_value = mock_client

            # Base: Raw -> 403
            base_raw_resp = MagicMock()
            base_raw_resp.status_code = 403

            # Base: Metadata -> OK (small content)
            import base64
            base_content = "small content"
            base_b64 = base64.b64encode(base_content.encode("utf-8")).decode("utf-8")

            base_meta_resp = MagicMock()
            base_meta_resp.status_code = 200
            base_meta_resp.raise_for_status = MagicMock()
            base_meta_resp.json.return_value = {
                "content": base_b64,
                "sha": "base_blob_sha"
            }

            # Head: Raw -> 403
            head_raw_resp = MagicMock()
            head_raw_resp.status_code = 403

            # Head: Metadata -> OK (too large, no content)
            head_meta_resp = MagicMock()
            head_meta_resp.status_code = 200
            head_meta_resp.raise_for_status = MagicMock()
            head_meta_resp.json.return_value = {
                "sha": "head_blob_sha"
            }

            # Head: Blob -> OK
            head_content = "large content fetched via blob"
            head_b64 = base64.b64encode(head_content.encode("utf-8")).decode("utf-8")

            head_blob_resp = MagicMock()
            head_blob_resp.status_code = 200
            head_blob_resp.raise_for_status = MagicMock()
            head_blob_resp.json.return_value = {
                "content": head_b64
            }

            mock_client.get = AsyncMock(side_effect=[
                base_raw_resp, base_meta_resp,
                head_raw_resp, head_meta_resp, head_blob_resp
            ])

            old_file, new_file = await get_file_contents(review_id, "src/large.py")

            assert old_file is not None
            assert old_file.contents == "small content"

            assert new_file is not None
            assert new_file.contents == "large content fetched via blob"

    @pytest.mark.asyncio
    async def test_get_file_contents_not_found_file(self):
        """Test handling of 404 (file added/deleted)."""
        review_id = "test_404"
        _pr_cache[review_id] = PRInfo(
            review_id=review_id,
            owner="test",
            repo="repo",
            number=1,
            title="Test PR",
            body="",
            base_sha="base_sha",
            head_sha="head_sha",
            files=[],
            commits=0, additions=0, deletions=0, changed_files=0,
            commits_list=[], comments=[],
            created_at=None, user={}, head_ref="head", base_ref="base"
        )

        with patch("cr.github.httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client_class.return_value.__aenter__.return_value = mock_client

            # Base: Raw -> 404 (New file)
            base_raw_resp = MagicMock()
            base_raw_resp.status_code = 404

            # Head: Raw -> 200
            head_raw_resp = MagicMock()
            head_raw_resp.status_code = 200
            head_raw_resp.text = "new file content"

            mock_client.get = AsyncMock(side_effect=[
                base_raw_resp,
                head_raw_resp
            ])

            old_file, new_file = await get_file_contents(review_id, "src/new.py")

            assert old_file is None
            assert new_file is not None
            assert new_file.contents == "new file content"
