# 🚀 Test Catalog Sync NOW

Everything is ready! Follow these steps to test the catalog sync workflow.

## ✅ What's Ready

- ✅ Workflow created: `.github/workflows/sync-to-catalog.yml`
- ✅ Makefile targets added: `catalog-sync`, `catalog-sync-watch`
- ✅ Scripts created in `examples/catalog-automation/scripts/`
- ✅ Version bumped to 0.1.2
- ✅ All Python 3.11 fixes applied
- ✅ Vendor directory filtering enabled
- ✅ All changes committed and pushed to `claude/mcp-harvesting-summary-obDG0`

---

## 🎯 Test Method 1: GitHub Web UI (RECOMMENDED - No Setup)

### Step 1: Open the Workflow Page
```
https://github.com/agent-matrix/mcp_ingest/actions/workflows/sync-to-catalog.yml
```

### Step 2: Click "Run workflow"
- Look for the green button on the right side that says "Run workflow"

### Step 3: Configure (or leave defaults)
- **Use workflow from**: `Branch: claude/mcp-harvesting-summary-obDG0`
- **Catalog repository**: `agent-matrix/catalog` (default)
- **Source repository**: `https://github.com/modelcontextprotocol/servers` (default)

### Step 4: Click "Run workflow" (green button)

### Step 5: Watch it run
- Click on the workflow run that appears
- Monitor the progress (should take ~5 minutes)

### Step 6: Verify the PR was created
```
https://github.com/agent-matrix/catalog/pulls
```

**Look for:**
- New PR with label `automated`
- Branch: `bot/sync-mcp-servers`
- Title: "chore(sync): automated catalog sync from mcp_ingest"

---

## 🎯 Test Method 2: Using Local Makefile (Requires `gh` CLI)

If you have GitHub CLI installed locally:

```bash
# 1. Pull latest changes
cd /path/to/mcp_ingest
git checkout claude/mcp-harvesting-summary-obDG0
git pull

# 2. Trigger and watch
make catalog-sync-watch

# 3. Check for PR
open https://github.com/agent-matrix/catalog/pulls
```

---

## ✅ Expected Results

### During Workflow Run
You should see these steps complete successfully:
1. ✓ Checkout mcp_ingest repository
2. ✓ Checkout catalog repository
3. ✓ Setup Python 3.11
4. ✓ Install mcp_ingest from source
5. ✓ Copy scripts to catalog
6. ✓ Run catalog sync
7. ✓ Validate catalog structure
8. ✓ Validate catalog schemas
9. ✓ Validate catalog index
10. ✓ Create pull request

### After Workflow Completes

**In the workflow summary:**
```
✅ Sync complete!
   Total items: ~66
   Active manifests: ~64
   Newly deprecated: ~2
   Index written: ./index.json

✓ Catalog structure validation passed
✓ Index validation passed
✓ All manifests conform to schema

✅ Pull request created!
```

**In agent-matrix/catalog:**
- ✅ New PR appears
- ✅ Labels: `automated`, `sync`, `catalog`
- ✅ Files changed:
  - `servers/**` - manifest files
  - `index.json` - updated index

**PR Description will show:**
```
📊 Sync Summary:
- Total items: ~66
- Active manifests: ~64
- Newly deprecated: ~2

🔧 Changes:
- Updated manifest files in servers/
- Regenerated index.json
```

---

## 🔍 Verification Checklist

After the workflow runs, verify:

- [ ] Workflow completed without errors (green checkmark ✓)
- [ ] All validation steps passed
- [ ] PR created in agent-matrix/catalog
- [ ] PR has correct labels and branch name
- [ ] `servers/` directory populated with manifests
- [ ] `index.json` updated
- [ ] No `node_modules` entries in catalog
- [ ] All paths in `index.json` are relative (no URLs)
- [ ] No duplicate IDs reported

---

## 🐛 If Something Goes Wrong

### Workflow Fails
1. Click on the failed workflow run
2. Expand the failed step to see error message
3. Check `.github/CATALOG_WORKFLOW_FIXES.md` for solutions

### No PR Created
**Possible reasons:**
1. No changes detected (catalog already up-to-date)
2. Permission issues (needs `CATALOG_PAT` secret)
3. Check workflow logs for details

### Permission Error
If you see: "GitHub Actions is not permitted to create pull requests"

**Solution:**
1. Go to: https://github.com/agent-matrix/catalog/settings/actions
2. Navigate to: Actions → General → Workflow permissions
3. Select: ☑️ "Read and write permissions"
4. Enable: ☑️ "Allow GitHub Actions to create and approve pull requests"
5. Save and re-run workflow

---

## 📊 What Happens During Sync

```
mcp_ingest repo
  ↓
  Installs mcp_ingest v0.1.2 (Python 3.11 compatible)
  ↓
  Copies scripts to catalog repo
  ↓
  Runs harvester on modelcontextprotocol/servers
  ↓
  Filters vendor directories (no node_modules)
  ↓
  Generates manifests with relative links
  ↓
  Adds provenance metadata
  ↓
  Validates everything
  ↓
  Creates PR in catalog repo
  ↓
agent-matrix/catalog
  (ready to review and merge)
```

---

## 🎉 Success!

If the workflow completes and PR is created, you have successfully:

✅ Automated catalog syncing from mcp_ingest
✅ Verified Python 3.11 compatibility
✅ Prevented node_modules contamination
✅ Enabled daily automated syncing
✅ Set up proper validation pipeline

---

## 📚 Next Steps

1. **Review the PR** in agent-matrix/catalog
2. **Merge the PR** if everything looks good
3. **Enable daily sync** (already configured for 02:15 UTC)
4. **Monitor future syncs** via Actions tab

---

## 📞 Quick Links

- **Trigger workflow**: https://github.com/agent-matrix/mcp_ingest/actions/workflows/sync-to-catalog.yml
- **Check PRs**: https://github.com/agent-matrix/catalog/pulls
- **View runs**: https://github.com/agent-matrix/mcp_ingest/actions
- **Troubleshooting**: `.github/CATALOG_WORKFLOW_FIXES.md`
- **Full guide**: `TRIGGER_SYNC.md`
- **Deployment**: `CATALOG_DEPLOYMENT.md`

---

**🚀 Ready to test! Click the link above and trigger the workflow!**
