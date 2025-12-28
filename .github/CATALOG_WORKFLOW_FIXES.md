# Catalog Workflow Fixes for agent-matrix/catalog

## Critical Issues Fixed in v0.1.1

### ✅ Issue 1: Python 3.11 Compatibility
**Problem:** `AttributeError: type object 'datetime.datetime' has no attribute 'UTC'`

**Root Cause:** `datetime.UTC` is only available in Python 3.12+, but GitHub Actions uses Python 3.11.

**Fix Applied:**
- Changed `datetime.UTC` → `timezone.utc` in all code
- Added `UP017` to ruff ignore list

**Impact:** Harvesting will now run successfully on Python 3.11

---

### ✅ Issue 2: node_modules Contamination
**Problem:** Catalog contains invalid entries like:
- `cp-pif__node_modules__type-is/manifest.json`
- `est-mcp-server/mcp-server__node_modules__shebang-command/manifest.json`

**Root Cause:** Harvester was scanning vendor directories and treating them as servers.

**Fix Applied:**
- Added `IGNORE_DIR_NAMES` set with node_modules, .git, .venv, dist, build, etc.
- Applied filtering in candidate discovery

**Impact:** No more vendor directory contamination in catalog

---

### ⚠️ Issue 3: GitHub Actions Permission Error
**Problem:** `Error: GitHub Actions is not permitted to create or approve pull requests.`

**Root Cause:** Repository settings don't allow GitHub Actions bot to create PRs.

**Fix Required in agent-matrix/catalog:**

Go to: **Settings → Actions → General → Workflow permissions**

Change to: **Read and write permissions** ✅ **Allow GitHub Actions to create and approve pull requests**

---

### ⚠️ Issue 4: Checkout Using Wrong Branch
**Problem:** Workflow tries to checkout `main` but repo uses `master`

**Fix Required in `.github/workflows/sync-mcp-servers.yml`:**

```yaml
# BEFORE:
- name: Checkout mcp_ingest (try git first, fallback to pip)
  uses: actions/checkout@v4
  with:
    repository: agent-matrix/mcp_ingest
    ref: main  # ❌ Wrong branch
    path: ./.tmp/mcp_ingest

# AFTER:
- name: Checkout mcp_ingest (try git first, fallback to pip)
  uses: actions/checkout@v4
  with:
    repository: agent-matrix/mcp_ingest
    ref: claude/mcp-harvesting-summary-obDG0  # ✅ Use feature branch until merged
    path: ./.tmp/mcp_ingest
```

**Alternative (after merging to main/master):**
```yaml
    ref: main  # or master, depending on your default branch
```

---

### ⚠️ Issue 5: Index.json Corruption (URLs + Missing Paths)
**Problem:**
- `manifests must be relative paths (found URL): https://raw.githubusercontent.com/...`
- `manifests path does not exist on disk: ...`

**Root Cause:** Sync script is preserving old/invalid index entries instead of rebuilding cleanly.

**Fix Required in `scripts/sync_mcp_servers.py`:**

Ensure your sync script:
1. **Always overwrites** `index.json` completely (never merge old entries)
2. **Only includes manifests** that exist on disk in current run
3. **Uses relative paths only** (no URLs)

**Validation guard to add:**
```python
# After building index.json, validate all entries
for manifest_path in index_data["manifests"]:
    # Check not a URL
    if manifest_path.startswith("http://") or manifest_path.startswith("https://"):
        raise SystemExit(f"BUG: manifest path is URL: {manifest_path}")

    # Check file exists
    full_path = Path(catalog_root) / manifest_path
    if not full_path.exists():
        raise SystemExit(f"BUG: manifest missing: {manifest_path}")
```

---

## Updated Workflow for agent-matrix/catalog

### Step 1: Update Repository Settings
- Go to Settings → Actions → General
- Enable "Read and write permissions"
- Enable "Allow GitHub Actions to create and approve pull requests"

### Step 2: Update Workflow File

Edit `.github/workflows/sync-mcp-servers.yml`:

```yaml
- name: Checkout mcp_ingest (try git first, fallback to pip)
  id: checkout-mcp-ingest
  continue-on-error: true
  uses: actions/checkout@v4
  with:
    repository: agent-matrix/mcp_ingest
    ref: claude/mcp-harvesting-summary-obDG0  # Use feature branch with fixes
    path: ./.tmp/mcp_ingest
```

### Step 3: Clean Existing Catalog

Remove contaminated entries:
```bash
# In your catalog repo
cd /path/to/catalog

# Remove node_modules contamination
find servers -name "*node_modules*" -type d -exec rm -rf {} +

# Rebuild clean index
python scripts/rebuild_index.py --catalog servers --out index.json --verbose

# Validate
python scripts/validate_catalog_index.py
```

### Step 4: Test Locally First

```bash
# Test the sync process locally
make test-sync

# If successful, commit
make commit-sync

# Push and create PR manually
git push origin your-test-branch
```

### Step 5: Enable Automated Workflow

Once everything works locally:
- Merge the test PR
- Let the daily cron run automatically
- Monitor the automated PRs

---

## Expected Behavior After Fixes

### ✅ Successful Harvest
```
🔍 HARVESTING MCP SERVERS
Source: https://github.com/modelcontextprotocol/servers
Workers: 8

✅ Harvested 66 manifests
   (no node_modules contamination)
```

### ✅ Clean Deduplication
```
📦 DEDUPLICATING AND SYNCING
📊 Found 66 manifests, 64 unique (2 duplicates)
✅ Synced 64 manifests to catalog
```

### ✅ Valid Index
```
📋 REBUILDING INDEX.JSON
✅ Index rebuilt with 64 manifests
   (all relative paths, all exist on disk)
```

### ✅ Successful PR Creation
```
Create or update the pull request
✅ Pull request created: #123
```

---

## Quick Checklist

- [ ] Python 3.11 compatibility fixed (v0.1.1)
- [ ] node_modules filtering added (v0.1.1)
- [ ] Repository permissions updated (Actions → Settings)
- [ ] Workflow uses correct branch (claude/mcp-harvesting-summary-obDG0)
- [ ] Existing catalog cleaned (no node_modules entries)
- [ ] Index validation added (guards against URLs/missing files)
- [ ] Local test successful (make test-sync)
- [ ] First automated PR verified

---

## Support

If you encounter issues:
1. Check GitHub Actions logs for detailed error messages
2. Run `make test-sync` locally to reproduce
3. Validate catalog with `python scripts/validate_catalog_index.py`
4. Open issue at https://github.com/agent-matrix/mcp_ingest/issues

---

## Version Info

**mcp-ingest version:** 0.1.1
**Python requirement:** 3.11, <3.13
**Release notes:** `.github/RELEASE_NOTES/v0.1.1.md`
