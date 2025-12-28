# Catalog Automation Reference

This directory contains **production-ready GitHub Actions workflows and scripts** for automating MCP server catalog maintenance. These files are designed to be copied into your `agent-matrix/catalog` repository.

## 📁 Files Overview

```
catalog-automation/
├── .github/workflows/
│   ├── sync-mcp-servers.yml    # Daily harvest + sync workflow
│   └── validate-pr.yml          # PR validation workflow
├── scripts/
│   ├── sync_from_harvest.py          # Sync harvested data into catalog
│   ├── rebuild_index.py              # Rebuild root index.json
│   ├── validate_catalog.py           # Validate catalog structure
│   ├── validate_schemas.py           # Validate against JSON schema
│   ├── check_duplicates.py           # Check for duplicate IDs
│   └── check_index_consistency.py    # Verify index matches catalog
├── schema/
│   └── manifest.schema.json          # JSON schema for manifests
└── README.md (this file)
```

---

## 🚀 Quick Start

### 1. Copy Files to Your Catalog Repo

```bash
# In your agent-matrix/catalog repository
cd /path/to/catalog

# Copy workflow files
mkdir -p .github/workflows
cp /path/to/mcp_ingest/examples/catalog-automation/.github/workflows/* .github/workflows/

# Copy scripts
mkdir -p scripts
cp /path/to/mcp_ingest/examples/catalog-automation/scripts/* scripts/
chmod +x scripts/*.py

# Copy schema
mkdir -p schema
cp /path/to/mcp_ingest/examples/catalog-automation/schema/* schema/

# Commit
git add .github/ scripts/ schema/
git commit -m "Add catalog automation workflows and scripts"
git push
```

### 2. Configure Repository Settings

In your GitHub repository settings:

1. **Enable Actions**
   - Go to Settings → Actions → General
   - Enable "Allow all actions and reusable workflows"

2. **Set Permissions**
   - Go to Settings → Actions → General → Workflow permissions
   - Select "Read and write permissions"
   - Check "Allow GitHub Actions to create and approve pull requests"

3. **Optional: Create Team** (for PR reviews)
   - Go to Settings → Teams
   - Create team "catalog-maintainers"
   - Add members who should review automated PRs

---

## 📊 Workflows

### 1. Sync MCP Servers (Daily)

**File**: `.github/workflows/sync-mcp-servers.yml`

**Purpose**: Automatically harvest MCP servers from upstream sources and create a PR with updates.

**Triggers**:
- **Daily**: Runs at 02:15 UTC (customizable via cron)
- **Manual**: Can be triggered from Actions tab with custom parameters

**What It Does**:
1. Harvests servers from `modelcontextprotocol/servers` (or custom source)
2. Deduplicates and normalizes manifests
3. Generates stable folder names (slugs)
4. Writes manifests to `servers/` directory
5. Rebuilds `index.json` with all manifest paths
6. Validates structure and schemas
7. Creates a pull request with changes

**Manual Trigger**:
```bash
# Via GitHub UI:
# Go to Actions → Sync MCP Servers (Daily) → Run workflow
# Optionally specify custom source repo and max workers

# Via GitHub CLI:
gh workflow run sync-mcp-servers.yml \
  -f source_repo=https://github.com/modelcontextprotocol/servers \
  -f max_workers=8
```

**Customization**:
```yaml
# Edit cron schedule (line 10)
- cron: "15 2 * * *"  # Change to your preferred time

# Edit default source (line 18)
default: 'https://github.com/modelcontextprotocol/servers'

# Edit max workers (line 22)
default: '8'  # Increase for faster harvesting
```

---

### 2. Validate Catalog PR

**File**: `.github/workflows/validate-pr.yml`

**Purpose**: Validate all changes in pull requests before merging.

**Triggers**:
- Pull requests that modify:
  - `servers/**`
  - `index.json`
  - `schema/**`
  - `scripts/**`
- Pushes to `main` branch

**Checks**:
- ✅ Catalog structure validation
- ✅ Manifest schema validation
- ✅ Python script linting
- ✅ Duplicate ID detection
- ✅ Index consistency verification

**What Gets Blocked**:
- Invalid JSON in manifests
- Missing required fields (id, name, type)
- Duplicate server IDs
- Manifests not listed in index.json
- Index entries pointing to non-existent manifests

---

## 🛠️ Scripts Reference

### sync_from_harvest.py

Syncs harvested manifests into the catalog structure with deduplication.

**Usage**:
```bash
python scripts/sync_from_harvest.py \
  --harvest .harvest \
  --catalog servers \
  --verbose
```

**What It Does**:
- Reads all `manifest.json` files from harvest directory
- Deduplicates based on fingerprint (source_repo + source_path + name)
- Generates stable slugs for folder names
- Writes manifests to `servers/<slug>/manifest.json`
- Creates per-folder `index.json` files

**Options**:
- `--harvest`: Input directory containing harvested manifests (required)
- `--catalog`: Output catalog directory (required)
- `--verbose`: Show detailed progress

---

### rebuild_index.py

Rebuilds the root `index.json` file from all manifests.

**Usage**:
```bash
python scripts/rebuild_index.py \
  --catalog servers \
  --out index.json \
  --base-url https://raw.githubusercontent.com/agent-matrix/catalog/refs/heads/main \
  --verbose
```

**What It Does**:
- Scans catalog directory for all `manifest.json` files
- Generates deterministic index with manifest paths
- Optionally adds absolute GitHub raw URLs
- Includes metadata (id, name, type) for each manifest

**Options**:
- `--catalog`: Catalog directory to scan (required)
- `--out`: Output index.json path (required)
- `--base-url`: Base URL for absolute manifest URLs (optional)
- `--verbose`: Show detailed progress

---

### validate_catalog.py

Validates catalog structure and basic requirements.

**Usage**:
```bash
python scripts/validate_catalog.py \
  --catalog servers \
  --index index.json
```

**Checks**:
- ✅ index.json exists and is valid JSON
- ✅ All manifests are valid JSON
- ✅ Required fields present (id, name, type)
- ✅ Reasonable values (non-empty names, valid IDs)

**Exit Codes**:
- `0`: Validation passed
- `1`: Validation failed (with error details)

---

### validate_schemas.py

Validates all manifests against JSON schema.

**Usage**:
```bash
python scripts/validate_schemas.py \
  --catalog servers \
  --schema schema/manifest.schema.json
```

**Checks**:
- ✅ All manifests conform to JSON schema
- ✅ Required fields have correct types
- ✅ Enum values are valid
- ✅ Patterns match (IDs, versions, etc.)

**Exit Codes**:
- `0`: All manifests valid
- `1`: Schema violations found

---

### check_duplicates.py

Checks for duplicate manifest IDs.

**Usage**:
```bash
python scripts/check_duplicates.py --catalog servers
```

**Checks**:
- ✅ No two manifests have the same ID
- ⚠️  Warns about manifests without IDs

**Exit Codes**:
- `0`: No duplicates
- `1`: Duplicates found

---

### check_index_consistency.py

Verifies index.json matches actual catalog contents.

**Usage**:
```bash
python scripts/check_index_consistency.py \
  --catalog servers \
  --index index.json
```

**Checks**:
- ✅ All manifests in catalog are listed in index
- ✅ All entries in index point to existing manifests

**Exit Codes**:
- `0`: Index consistent
- `1`: Inconsistencies found

---

## 📋 Schema Reference

### manifest.schema.json

Canonical JSON schema for MCP server manifests.

**Required Fields**:
- `schema_version`: Must be `1`
- `type`: Must be `"mcp_server"`, `"agent"`, or `"tool"`
- `id`: Unique identifier (alphanumeric, dots, dashes, underscores)
- `name`: Human-readable name (1-100 chars)

**Key Sections**:

#### Provenance (NEW in this version)
```json
{
  "provenance": {
    "harvested_at": "2025-12-28T10:00:00Z",
    "source_repo": "https://github.com/owner/repo",
    "source_ref": "main",
    "source_path": "src/server",
    "detector": "fastmcp",
    "confidence": 0.95,
    "stars": 1234,
    "forks": 56,
    "harvester": "mcp-ingest",
    "harvester_version": "0.1.0"
  }
}
```

#### MCP Registration
```json
{
  "mcp_registration": {
    "server": {
      "name": "my-server",
      "transport": "SSE",
      "url": "http://localhost:3000/sse"
    },
    "resources": [...],
    "prompts": [...],
    "tool": {...}
  }
}
```

#### Artifacts
```json
{
  "artifacts": [
    {
      "kind": "git",
      "spec": {
        "repo": "https://github.com/owner/repo",
        "ref": "v1.0.0"
      }
    }
  ]
}
```

---

## 🔄 Workflow: Daily Sync Process

Here's what happens during a typical daily sync:

### 1. **Harvest Phase** (2-5 minutes)
```
→ Checkout catalog repo
→ Install mcp_ingest
→ Run: mcp-ingest harvest-source <upstream-repo>
→ Output: .harvest/ directory with raw manifests
```

### 2. **Sync Phase** (1-2 minutes)
```
→ Deduplicate manifests (by source fingerprint)
→ Generate stable slugs for folders
→ Write to: servers/<slug>/manifest.json
→ Create per-folder index.json files
```

### 3. **Index Phase** (<1 minute)
```
→ Scan all manifest.json files
→ Generate deterministic index.json
→ Include absolute GitHub raw URLs
```

### 4. **Validation Phase** (1-2 minutes)
```
→ Validate structure (all manifests are valid JSON)
→ Validate schemas (conform to manifest.schema.json)
→ Check for duplicates
→ Verify index consistency
```

### 5. **PR Phase** (if changes)
```
→ Stage all changes
→ Create pull request with detailed description
→ Tag with: automated, catalog-sync, mcp-servers
→ Request review from catalog-maintainers
```

### 6. **Review & Merge**
```
→ Human reviews PR (or Guardian auto-approves)
→ Merge to main
→ Matrix Hub ingests updated catalog
```

---

## 🎯 Expected Results

After setup, you'll have:

### Daily Automation
- ✅ Daily PRs with catalog updates (if changes detected)
- ✅ Automatic deduplication and normalization
- ✅ Stable folder names (no thrashing between runs)
- ✅ Rich provenance metadata for all servers

### Quality Assurance
- ✅ All PRs validated before merge
- ✅ Schema enforcement
- ✅ Duplicate detection
- ✅ Consistency checks

### Integration Ready
- ✅ Matrix Hub can ingest from `index.json`
- ✅ Manifests compatible with Matrix Hub DB
- ✅ Absolute URLs for direct consumption
- ✅ Provenance for trust scoring and ranking

---

## 🐛 Troubleshooting

### Workflow fails with "permission denied"
**Solution**: Enable workflow permissions in Settings → Actions → General → Workflow permissions

### "No manifests found" error
**Solution**: Check that harvest step completed successfully and `.harvest/` directory contains `manifest.json` files

### Schema validation fails
**Solution**: Run locally to see detailed errors:
```bash
python scripts/validate_schemas.py --catalog servers --schema schema/manifest.schema.json
```

### Duplicate IDs detected
**Solution**: Run duplicate checker to find conflicts:
```bash
python scripts/check_duplicates.py --catalog servers
```
Then manually resolve by removing or renaming duplicate manifests.

### Index inconsistency
**Solution**: Rebuild index:
```bash
python scripts/rebuild_index.py --catalog servers --out index.json
```

---

## 📚 Additional Resources

- **mcp_ingest Documentation**: See main repo README for harvesting options
- **Matrix Hub Integration**: See Matrix Hub docs for catalog ingestion
- **GitHub Actions**: [GitHub Actions Documentation](https://docs.github.com/en/actions)
- **JSON Schema**: [JSON Schema Specification](https://json-schema.org/)

---

## 🔐 Security Notes

1. **GitHub Token**: Uses `${{ secrets.GITHUB_TOKEN }}` automatically (no setup needed)
2. **API Rate Limits**: HTTP caching reduces API calls by 90%+
3. **Sandboxing**: mcp_ingest runs in isolated GitHub Actions environment
4. **Validation**: All inputs validated before catalog updates
5. **Audit Trail**: All changes tracked via git history and PR descriptions

---

## 🚀 Next Steps

After copying these files to your catalog repo:

1. ✅ Test manually: Trigger workflow from Actions tab
2. ✅ Review first PR: Ensure manifests look correct
3. ✅ Configure Matrix Hub: Point to your catalog's index.json
4. ✅ Monitor daily runs: Check for errors or rate limits
5. ✅ Customize as needed: Adjust schedules, sources, validation rules

---

## 💡 Tips for Production

### Performance
- Increase `max_workers` for faster harvesting (8-16 workers typical)
- Use HTTP caching to avoid re-downloading unchanged files
- Schedule during off-peak hours (02:00-04:00 UTC recommended)

### Reliability
- Set workflow timeout to 60 minutes (handles large harvests)
- Use concurrency control to prevent overlapping runs
- Implement retry logic for network failures (already included)

### Maintainability
- Review PRs weekly to catch patterns/issues
- Update schema as manifest requirements evolve
- Archive old manifests periodically (retention policy)

### Governance
- Integrate Guardian for policy-based PR approval
- Set up alerts for validation failures
- Track metrics (servers added/updated/removed)

---

**Questions?** Check the [mcp_ingest repository](https://github.com/agent-matrix/mcp_ingest) or open an issue.
