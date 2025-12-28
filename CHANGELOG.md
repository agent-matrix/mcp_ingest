# Changelog

All notable changes to this project will be documented in this file.

## [Unreleased] - 2025-12-28

### Added - Production-Ready Harvesting Upgrades

This release adds critical improvements for harvesting MCP servers at scale, specifically designed to support daily automation and reliable ingestion from sources like `modelcontextprotocol/servers`.

#### 1. **Relative README Link Resolution** (CRITICAL)
- **File**: `mcp_ingest/utils/extractor.py`
- **New Functions**:
  - `extract_relative_paths_from_markdown()`: Extracts relative paths from markdown links
  - `resolve_repo_relative_links()`: Converts relative paths to absolute GitHub tree URLs
- **Impact**: Can now harvest servers referenced via relative links like `./src/server` or `src/server/README.md`
- **Why**: Many repos (especially `modelcontextprotocol/servers`) use relative paths to reference MCP servers
- **Integration**: Automatically integrated into `extract_github_repo_links_from_readme()`

#### 2. **GitHub API Fallback Enumeration for Monorepos**
- **File**: `mcp_ingest/utils/github_contents.py` (NEW)
- **New Functions**:
  - `list_dirs()`: Lists directories at a given path using GitHub Contents API
  - `enumerate_monorepo_servers()`: Discovers server directories in common roots (src/, servers/, packages/)
- **Impact**: Can discover servers even when not explicitly listed in README
- **Features**:
  - Automatic retry with exponential backoff
  - Rate limiting handling (403/429)
  - Configurable search depth and roots

#### 3. **Stable Slugging with Collision Handling**
- **File**: `mcp_ingest/utils/slug.py` (NEW)
- **New Functions**:
  - `stable_slug()`: Deterministic, filesystem-safe slug generation
  - `slug_from_repo_and_path()`: Generate slugs from GitHub coordinates
  - `dedupe_slugs()`: Ensure uniqueness with numeric suffixes
- **Impact**: Catalog paths remain stable across harvests, preventing thrashing
- **Features**:
  - Unicode normalization (café → cafe)
  - Lowercase, alphanumeric + hyphens only
  - Deterministic hash suffix for long names
  - Never returns empty string

#### 4. **Provenance and Enrichment Metadata**
- **File**: `mcp_ingest/emit/enrich.py` (ENHANCED)
- **New Parameters**:
  - `detector`: Detection framework (e.g., "fastmcp", "langchain")
  - `confidence`: Detector confidence score (0.0-1.0)
  - `stars`: GitHub repository stars count
  - `forks`: GitHub repository forks count
- **New Manifest Fields**:
  - `provenance.harvested_at`: ISO timestamp of harvest
  - `provenance.source_repo`: Source repository URL
  - `provenance.source_ref`: Git reference (branch/tag/SHA)
  - `provenance.source_path`: Relative path within repo
  - `provenance.detector`: Detection method used
  - `provenance.confidence`: Detection confidence
  - `provenance.stars`: Repository stars (for ranking)
  - `provenance.forks`: Repository forks (for ranking)
  - `provenance.harvester`: Harvester tool name
  - `provenance.harvester_version`: Harvester version
- **Impact**: Enables better deduplication, ranking, trust scoring, and UI display
- **Backward Compatible**: All additions use `setdefault()` and are optional

#### 5. **Rate Limiting, Backoff, and ETag Caching**
- **File**: `mcp_ingest/utils/http_cache.py` (NEW)
- **New Functions**:
  - `get_with_etag()`: HTTP fetch with ETag caching and retry logic
  - `clear_cache()`: Clear the ETag cache
  - `get_cache_stats()`: Get cache statistics
- **Features**:
  - ETag-based caching (If-None-Match / 304 Not Modified)
  - Exponential backoff for rate limits (403/429)
  - Persistent cache to disk (`.cache/http_etags.json`)
  - Up to 6 retry attempts with 2^n second delays
  - Respects X-RateLimit-Reset headers
- **Impact**: Daily automation won't hammer GitHub APIs or re-download unchanged resources
- **Configuration**: `MCP_INGEST_HTTP_CACHE` env var for cache location

### Changed
- Enhanced `extract_github_repo_links_from_readme()` to also extract and resolve relative links
- All changes are **additive** and **backward compatible** - existing code continues to work

### Technical Details

#### Backward Compatibility
- ✅ All existing APIs unchanged (only new optional parameters added)
- ✅ Existing tests pass (2 passed, 1 skipped)
- ✅ CLI commands work unchanged
- ✅ Default behavior preserved (new features opt-in via parameters)

#### Testing
All new modules have been tested:
- ✓ Import validation
- ✓ Unit tests for core functions
- ✓ Integration with existing codebase
- ✓ Existing test suite passes

#### Use Cases Enabled

1. **Daily Harvesting from modelcontextprotocol/servers**:
   ```bash
   mcp-ingest harvest-source https://github.com/modelcontextprotocol/servers \
     --out dist/harvest \
     --max-workers 8
   ```
   Now captures servers referenced via relative links!

2. **Production Catalog Building**:
   - Stable slugs prevent path thrashing
   - Provenance enables deduplication and ranking
   - ETag caching reduces API load
   - Rate limiting prevents 403 errors

3. **Matrix Hub Integration**:
   - Rich provenance for UI display
   - Quality scoring via confidence + stars
   - Source tracking for security/trust

### Migration Guide

No migration needed! All changes are backward compatible. To use new features:

**Enable ETag caching** (automatic):
```bash
export MCP_INGEST_HTTP_CACHE=".cache"
mcp-ingest harvest-source <repo> --out dist/
```

**Use stable slugging**:
```python
from mcp_ingest.utils.slug import stable_slug, slug_from_repo_and_path

slug = slug_from_repo_and_path("owner", "repo", "src/server")
```

**Add provenance to manifests**:
```python
from mcp_ingest.emit.enrich import enrich_manifest

enrich_manifest(
    manifest_path,
    detector="fastmcp",
    confidence=0.95,
    stars=123,
    forks=45,
)
```

### Next Steps

These upgrades prepare `mcp_ingest` for:
- Daily GitHub Actions in `agent-matrix/catalog`
- Production-scale harvesting (thousands of servers)
- Integration with Matrix Hub's ingestion pipeline
- Future Guardian policy enforcement

---

## [0.1.0] - Previous Release

Initial release with core functionality:
- Basic MCP server detection
- Manifest generation
- MatrixHub registration
- Harvest from repos/zips
