# Catalog Deployment Guide for agent-matrix/catalog

## 🎯 Version 0.1.2 - Production Ready

This guide shows you how to deploy the automated sync workflow to your catalog repository.

---

## 📋 Prerequisites

Before deploying, ensure you have:

1. ✅ Admin access to `agent-matrix/catalog` repository
2. ✅ GitHub Actions enabled
3. ✅ Write permissions configured for GitHub Actions bot

---

## 🔧 Step 1: Configure Repository Permissions

**Critical:** GitHub Actions needs permission to create PRs.

1. Go to: https://github.com/agent-matrix/catalog/settings/actions
2. Navigate to: **Settings → Actions → General → Workflow permissions**
3. Select: ☑️ **Read and write permissions**
4. Enable: ☑️ **Allow GitHub Actions to create and approve pull requests**
5. Click **Save**

---

## 📁 Step 2: Copy Workflow and Scripts

From the `mcp_ingest` repository, copy these files to `catalog` repository:

```bash
# In your local environment
cd /path/to/mcp_ingest

# Copy workflow
cp examples/catalog-automation/.github/workflows/sync-catalog.yml \
   /path/to/catalog/.github/workflows/

# Copy all scripts
cp examples/catalog-automation/scripts/sync_mcp_servers.py \
   /path/to/catalog/scripts/

cp examples/catalog-automation/scripts/validate_catalog_*.py \
   /path/to/catalog/scripts/

# Copy schema (if not exists)
cp examples/catalog-automation/schema/mcp_server.schema.json \
   /path/to/catalog/schema/
```

**Or use the automated command:**

```bash
cd /path/to/mcp_ingest
make catalog-example
```

---

## ✅ Step 3: Verify Files in Catalog Repo

Your `catalog` repository should now have:

```
catalog/
├── .github/
│   └── workflows/
│       └── sync-catalog.yml          # ← NEW: Daily sync workflow
├── scripts/
│   ├── sync_mcp_servers.py           # ← NEW: Main sync script
│   ├── validate_catalog_structure.py # ← NEW: Structure validation
│   ├── validate_catalog_schemas.py   # ← NEW: Schema validation
│   └── validate_catalog_index.py     # ← NEW: Index validation
├── schema/
│   └── mcp_server.schema.json        # JSON schema for validation
├── servers/                           # Output directory
└── index.json                         # Top-level catalog index
```

---

## 🧪 Step 4: Test Locally (Recommended)

Before enabling automation, test the sync locally:

```bash
cd /path/to/catalog

# Install mcp_ingest from the fixed branch
pip install git+https://github.com/agent-matrix/mcp_ingest.git@claude/mcp-harvesting-summary-obDG0

# Install validation dependencies
pip install jsonschema ruff

# Run sync
python scripts/sync_mcp_servers.py \
  --source-repo "https://github.com/modelcontextprotocol/servers" \
  --catalog-root "." \
  --servers-dir "servers" \
  --index-file "index.json" \
  --max-parallel 4

# Validate results
python scripts/validate_catalog_structure.py
python scripts/validate_catalog_schemas.py
python scripts/validate_catalog_index.py

# Check what changed
git status
git diff index.json
```

**Expected Output:**

```
✅ Sync complete!
   Total items: 66
   Active manifests: 64
   Newly deprecated: 2
   Index written: ./index.json

✓ Catalog structure validation passed
✓ Index validation passed
✓ All manifests conform to schema
```

---

## 🚀 Step 5: Commit and Push Workflow

```bash
cd /path/to/catalog

git add .github/workflows/sync-catalog.yml
git add scripts/sync_mcp_servers.py
git add scripts/validate_*.py
git add schema/mcp_server.schema.json

git commit -m "feat: add automated catalog sync workflow

- Daily sync from modelcontextprotocol/servers
- Complete validation suite
- Python 3.11 compatible
- Auto-creates PRs with mcp_ingest v0.1.2
"

git push origin main
```

---

## 🤖 Step 6: Enable Automated Workflow

### Option A: Manual Trigger (Test First)

1. Go to: https://github.com/agent-matrix/catalog/actions
2. Click on "Sync MCP Servers Catalog"
3. Click "Run workflow" → "Run workflow"
4. Monitor the workflow run
5. Check the created PR

### Option B: Wait for Daily Schedule

The workflow runs automatically at **02:15 UTC daily**.

---

## 📊 What the Workflow Does

### Harvesting Phase
1. **Installs mcp_ingest** v0.1.2 from git (with all fixes)
2. **Harvests** from `modelcontextprotocol/servers`
3. **Resolves relative links** automatically
4. **Filters vendor directories** (no node_modules contamination)
5. **Adds provenance metadata** to all manifests

### Sync Phase
6. **Generates deterministic paths**: `servers/<owner>-<repo>/<repo>__<subpath>/`
7. **Tracks lifecycle**: active → deprecated (never delete)
8. **Detects ID collisions**: prevents database corruption
9. **Validates paths**: ensures no URLs in index.json

### Validation Phase
10. **Structure validation**: required fields, correct types
11. **Schema validation**: JSON schema compliance
12. **Index validation**: path existence, no duplicates
13. **Consistency checks**: active manifests match index

### PR Creation Phase
14. **Creates pull request** with detailed changes
15. **Labels**: `automated`, `sync`, `catalog`
16. **Branch**: `bot/sync-mcp-servers`
17. **Auto-deletes branch** after merge

---

## 🔍 Monitoring and Maintenance

### Check Workflow Status

```bash
# View recent workflow runs
gh run list --workflow=sync-catalog.yml --limit 5

# View specific run
gh run view <run-id>

# Download logs
gh run download <run-id>
```

### Review Automated PRs

1. Go to: https://github.com/agent-matrix/catalog/pulls
2. Look for PRs with label: `automated`
3. Review changes in:
   - `servers/` directory (new/updated manifests)
   - `index.json` (manifest list updates)
4. Check PR description for:
   - Total items count
   - Active manifests count
   - Newly deprecated count

### Merge Automated PRs

```bash
# Approve and merge via CLI
gh pr review <pr-number> --approve
gh pr merge <pr-number> --squash

# Or use GitHub UI
```

---

## 🐛 Troubleshooting

### Issue: Workflow Fails with "GitHub Actions is not permitted to create PRs"

**Solution:**
1. Go to Settings → Actions → General
2. Enable "Allow GitHub Actions to create and approve pull requests"
3. Re-run the workflow

### Issue: Python 3.11 Compatibility Errors

**Solution:**
The workflow now uses `git+https://github.com/agent-matrix/mcp_ingest.git@claude/mcp-harvesting-summary-obDG0` which has all fixes. Ensure you're not falling back to PyPI.

### Issue: node_modules Contamination

**Solution:**
Version 0.1.2 filters vendor directories automatically. Clean existing contamination:

```bash
find servers -name "*node_modules*" -type d -exec rm -rf {} +
```

### Issue: Index Contains URLs

**Solution:**
The new sync script validates this. If you see URLs:
1. Delete corrupted `index.json`
2. Re-run sync: `python scripts/sync_mcp_servers.py ...`
3. Validation will fail if URLs appear

### Issue: Duplicate IDs

**Solution:**
The sync script fails hard on ID collisions. Fix upstream by:
1. Checking the error message for conflicting servers
2. Manually assigning unique IDs
3. Or skipping one of the duplicates

---

## 📈 Expected Results

### First Sync

```
📊 Summary:
   Total items: 66
   Active manifests: 64
   Newly deprecated: 0

📁 Directory structure:
servers/
├── modelcontextprotocol-servers/
│   ├── servers__.
│   │   └── manifest.json
│   ├── servers__src__brave-search/
│   │   └── manifest.json
│   ├── servers__src__sqlite/
│   │   └── manifest.json
│   └── ...
```

### Subsequent Syncs

```
📊 Summary:
   Total items: 68        (2 new servers added)
   Active manifests: 66   (2 new active)
   Newly deprecated: 1    (1 removed from upstream)
```

---

## 🎯 Success Criteria

After deployment, verify:

- ☑️ Workflow runs successfully (green checkmark)
- ☑️ PR created automatically
- ☑️ No node_modules entries in catalog
- ☑️ All index.json paths are relative
- ☑️ All paths exist on disk
- ☑️ No duplicate IDs
- ☑️ Validation passes

---

## 🔄 Updating the Workflow

When new features are added to `mcp_ingest`:

1. Update the branch/tag in workflow:
   ```yaml
   pip install git+https://github.com/agent-matrix/mcp_ingest.git@main
   ```

2. Or pin to a specific version:
   ```yaml
   pip install mcp-ingest==0.1.2
   ```

---

## 📚 Additional Resources

- **Workflow file**: `examples/catalog-automation/.github/workflows/sync-catalog.yml`
- **Scripts**: `examples/catalog-automation/scripts/`
- **Troubleshooting**: `.github/CATALOG_WORKFLOW_FIXES.md`
- **Release notes**: `.github/RELEASE_NOTES/v0.1.2.md` (coming soon)

---

## 🙋 Support

If you encounter issues:

1. Check GitHub Actions logs
2. Review `.github/CATALOG_WORKFLOW_FIXES.md`
3. Test locally with the commands above
4. Open issue: https://github.com/agent-matrix/mcp_ingest/issues

---

## ✅ Deployment Checklist

- [ ] Repository permissions configured (write + PR creation)
- [ ] Workflow file copied to `.github/workflows/`
- [ ] Scripts copied to `scripts/`
- [ ] Schema copied to `schema/`
- [ ] Local test completed successfully
- [ ] Files committed and pushed
- [ ] First workflow run triggered manually
- [ ] First PR reviewed and merged
- [ ] Daily automation enabled
- [ ] Monitoring set up

**Ready for production! 🚀**
