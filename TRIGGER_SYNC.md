# How to Trigger Catalog Sync

The catalog sync workflow has been added to this repository and is ready to use!

---

## ✅ What's Been Set Up

**Workflow File**: `.github/workflows/sync-to-catalog.yml`
- ✅ Runs daily at 02:15 UTC
- ✅ Can be triggered manually
- ✅ Syncs to `agent-matrix/catalog`
- ✅ Creates PRs automatically

**Makefile Commands**:
- ✅ `make catalog-sync` - Trigger workflow
- ✅ `make catalog-sync-watch` - Trigger and watch
- ✅ `make catalog-sync-status` - Check status
- ✅ `make catalog-help` - See all commands

---

## 🚀 How to Trigger the Workflow

### Option 1: GitHub Web UI (Easiest)

1. **Go to Actions page**:
   ```
   https://github.com/agent-matrix/mcp_ingest/actions/workflows/sync-to-catalog.yml
   ```

2. **Click "Run workflow"** button (top right)

3. **Configure inputs** (optional):
   - Catalog repository: `agent-matrix/catalog` (default)
   - Source repository: `https://github.com/modelcontextprotocol/servers` (default)

4. **Click "Run workflow"** (green button)

5. **Watch it run**:
   - Click on the workflow run that appears
   - Monitor each step in real-time
   - Check the summary at the end

6. **View the PR**:
   ```
   https://github.com/agent-matrix/catalog/pulls
   ```
   - Look for PR with label: `automated`
   - Branch: `bot/sync-mcp-servers`

---

### Option 2: GitHub CLI (From Your Machine)

If you have GitHub CLI installed locally:

```bash
# Trigger the workflow
gh workflow run sync-to-catalog.yml \
  --repo agent-matrix/mcp_ingest \
  --ref claude/mcp-harvesting-summary-obDG0 \
  -f catalog_repo="agent-matrix/catalog" \
  -f source_repo="https://github.com/modelcontextprotocol/servers"

# Watch it run
gh run watch --repo agent-matrix/mcp_ingest

# Check status
gh run list --repo agent-matrix/mcp_ingest \
  --workflow=sync-to-catalog.yml \
  --limit 5
```

**Or use the Makefile** (from mcp_ingest directory):

```bash
cd /path/to/mcp_ingest
make catalog-sync-watch
```

---

### Option 3: API Call (Advanced)

```bash
# Set your GitHub token
export GITHUB_TOKEN="your_token_here"

# Trigger workflow
curl -X POST \
  -H "Accept: application/vnd.github+json" \
  -H "Authorization: Bearer $GITHUB_TOKEN" \
  -H "X-GitHub-Api-Version: 2022-11-28" \
  https://api.github.com/repos/agent-matrix/mcp_ingest/actions/workflows/sync-to-catalog.yml/dispatches \
  -d '{
    "ref":"claude/mcp-harvesting-summary-obDG0",
    "inputs":{
      "catalog_repo":"agent-matrix/catalog",
      "source_repo":"https://github.com/modelcontextprotocol/servers"
    }
  }'
```

---

## 📊 What to Expect

### Workflow Steps

1. **Checkout repositories** (mcp_ingest + catalog)
2. **Install dependencies** (Python 3.11, mcp_ingest, validation tools)
3. **Copy scripts** to catalog repo
4. **Run sync** (harvest → dedupe → validate)
5. **Validate catalog** (structure, schema, index)
6. **Create PR** (if changes detected)
7. **Summary** (counts and stats)

### Expected Output

```
✅ Sync complete!
   Total items: 66
   Active manifests: 64
   Newly deprecated: 2
   Index written: ./index.json

✓ Catalog structure validation passed
✓ Index validation passed
✓ All manifests conform to schema

✅ Pull request created: #123
```

### PR in agent-matrix/catalog

You should see a PR with:
- **Title**: "chore(sync): automated catalog sync from mcp_ingest"
- **Labels**: `automated`, `sync`, `catalog`
- **Branch**: `bot/sync-mcp-servers`
- **Changes**:
  - `servers/**` directory (manifest files)
  - `index.json` (updated manifest list)

---

## 🔍 Monitoring

### Check Workflow Status

**Via GitHub UI**:
1. Go to: https://github.com/agent-matrix/mcp_ingest/actions
2. Click on "Sync to Catalog Repo"
3. View recent runs

**Via GitHub CLI**:
```bash
# List recent runs
gh run list --repo agent-matrix/mcp_ingest \
  --workflow=sync-to-catalog.yml \
  --limit 5

# View specific run
gh run view <run-id> --repo agent-matrix/mcp_ingest

# View logs
gh run view <run-id> --log --repo agent-matrix/mcp_ingest
```

### Check Created PRs

**Via GitHub UI**:
1. Go to: https://github.com/agent-matrix/catalog/pulls
2. Filter by label: `automated`

**Via GitHub CLI**:
```bash
gh pr list --repo agent-matrix/catalog \
  --label automated \
  --limit 5
```

---

## ⚙️ Configuration

### Required Secrets (Optional)

For cross-repo PR creation, you may need to add a secret:

1. **Create Personal Access Token** (classic):
   - Go to: https://github.com/settings/tokens
   - Generate new token (classic)
   - Scopes: `repo`, `workflow`
   - Copy the token

2. **Add to Repository Secrets**:
   - Go to: https://github.com/agent-matrix/mcp_ingest/settings/secrets/actions
   - Click "New repository secret"
   - Name: `CATALOG_PAT`
   - Value: (paste token)

**Note**: The workflow will try to use `CATALOG_PAT` first, then fall back to `GITHUB_TOKEN`.

### Repository Permissions

Ensure the catalog repo allows PR creation:
1. Go to: https://github.com/agent-matrix/catalog/settings/actions
2. Navigate to: **Actions → General → Workflow permissions**
3. Select: ☑️ **Read and write permissions**
4. Enable: ☑️ **Allow GitHub Actions to create and approve pull requests**

---

## 🐛 Troubleshooting

### Issue: Workflow Not Visible

**Solution**: Make sure you're on the correct branch:
```bash
git checkout claude/mcp-harvesting-summary-obDG0
git pull
```

### Issue: Workflow Fails with Permission Error

**Solution**: Add `CATALOG_PAT` secret (see Configuration above)

### Issue: No PR Created

**Possible causes**:
1. No changes detected (catalog already up-to-date)
2. Check workflow logs for errors
3. Verify repository permissions

**Check**:
```bash
gh run view --log --repo agent-matrix/mcp_ingest
```

### Issue: Validation Fails

**Check**:
- node_modules contamination
- URL corruption in index.json
- Duplicate IDs

**Solution**: Workflow should prevent these, but if they occur:
1. Check workflow logs
2. Review PR changes before merging
3. Report issue if validation passed incorrectly

---

## ✅ Success Checklist

After triggering the workflow:

- [ ] Workflow runs successfully (green checkmark)
- [ ] All validation steps pass
- [ ] PR created in agent-matrix/catalog
- [ ] PR has correct labels (`automated`, `sync`, `catalog`)
- [ ] PR description shows counts and changes
- [ ] No node_modules entries in catalog
- [ ] All index.json paths are relative
- [ ] No duplicate IDs reported

---

## 📈 Next Steps

Once the PR is created:

1. **Review the PR**:
   - Check the changes look correct
   - Verify counts match expectations
   - Confirm no unexpected files

2. **Merge the PR**:
   ```bash
   gh pr review <pr-number> --repo agent-matrix/catalog --approve
   gh pr merge <pr-number> --repo agent-matrix/catalog --squash
   ```

3. **Monitor Daily Syncs**:
   - Workflow runs automatically at 02:15 UTC daily
   - Check for new PRs regularly
   - Merge when ready

---

## 📚 Additional Resources

- **Workflow file**: `.github/workflows/sync-to-catalog.yml`
- **Deployment guide**: `CATALOG_DEPLOYMENT.md`
- **Troubleshooting**: `.github/CATALOG_WORKFLOW_FIXES.md`
- **Scripts**: `examples/catalog-automation/scripts/`

---

## 🎯 Quick Command Reference

```bash
# From your local machine (with gh CLI installed)

# Trigger sync
make catalog-sync

# Trigger and watch
make catalog-sync-watch

# Check status
make catalog-sync-status

# View all catalog commands
make catalog-help
```

---

**Ready to sync! 🚀**

Use any of the methods above to trigger the workflow and verify the PR is created in agent-matrix/catalog.
