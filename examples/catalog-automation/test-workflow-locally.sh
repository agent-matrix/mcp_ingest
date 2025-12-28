#!/bin/bash
# Test the catalog automation workflow locally before deploying to GitHub Actions
#
# Usage:
#   ./test-workflow-locally.sh [source-repo-url]
#
# Example:
#   ./test-workflow-locally.sh https://github.com/modelcontextprotocol/servers

set -e

# Configuration
SOURCE_REPO="${1:-https://github.com/modelcontextprotocol/servers}"
MAX_WORKERS="8"
TEST_DIR="./test-catalog"

echo "🧪 Testing Catalog Automation Workflow Locally"
echo "================================================"
echo "Source: $SOURCE_REPO"
echo "Output: $TEST_DIR"
echo ""

# Clean previous test run
if [ -d "$TEST_DIR" ]; then
    echo "🗑️  Cleaning previous test directory..."
    rm -rf "$TEST_DIR"
fi

# Create test directories
mkdir -p "$TEST_DIR"/{.harvest,servers,schema,scripts}

# Step 1: Install dependencies
echo ""
echo "📦 Step 1: Installing dependencies..."
if ! command -v mcp-ingest &> /dev/null; then
    echo "   Installing mcp-ingest..."
    pip install -e "." -q
fi

pip install jsonschema pydantic ruff -q
echo "   ✅ Dependencies installed"

# Step 2: Copy scripts and schema
echo ""
echo "📝 Step 2: Setting up scripts and schema..."
cp scripts/*.py "$TEST_DIR/scripts/"
cp schema/*.json "$TEST_DIR/schema/"
chmod +x "$TEST_DIR/scripts/"*.py
echo "   ✅ Scripts and schema ready"

# Step 3: Harvest
echo ""
echo "🔍 Step 3: Harvesting from $SOURCE_REPO..."
mcp-ingest harvest-source "$SOURCE_REPO" \
    --out "$TEST_DIR/.harvest" \
    --max-parallel "$MAX_WORKERS" \
    --yes

if [ ! -d "$TEST_DIR/.harvest" ] || [ -z "$(ls -A "$TEST_DIR/.harvest")" ]; then
    echo "   ❌ Harvest failed or produced no results"
    exit 1
fi

HARVEST_COUNT=$(find "$TEST_DIR/.harvest" -name "manifest.json" | wc -l)
echo "   ✅ Harvested $HARVEST_COUNT manifests"

# Step 4: Sync
echo ""
echo "📦 Step 4: Syncing into catalog structure..."
python "$TEST_DIR/scripts/sync_from_harvest.py" \
    --harvest "$TEST_DIR/.harvest" \
    --catalog "$TEST_DIR/servers" \
    --verbose

SYNC_COUNT=$(find "$TEST_DIR/servers" -name "manifest.json" | wc -l)
echo "   ✅ Synced $SYNC_COUNT manifests"

# Step 5: Rebuild index
echo ""
echo "📋 Step 5: Rebuilding index.json..."
python "$TEST_DIR/scripts/rebuild_index.py" \
    --catalog "$TEST_DIR/servers" \
    --out "$TEST_DIR/index.json" \
    --base-url "https://raw.githubusercontent.com/agent-matrix/catalog/refs/heads/main" \
    --verbose

if [ ! -f "$TEST_DIR/index.json" ]; then
    echo "   ❌ Index file not created"
    exit 1
fi

INDEX_COUNT=$(jq '.manifest_count' "$TEST_DIR/index.json" 2>/dev/null || echo "0")
echo "   ✅ Index created with $INDEX_COUNT manifests"

# Step 6: Validate structure
echo ""
echo "🔍 Step 6: Validating catalog structure..."
python "$TEST_DIR/scripts/validate_catalog.py" \
    --catalog "$TEST_DIR/servers" \
    --index "$TEST_DIR/index.json"

# Step 7: Validate schemas
echo ""
echo "🔍 Step 7: Validating manifest schemas..."
python "$TEST_DIR/scripts/validate_schemas.py" \
    --catalog "$TEST_DIR/servers" \
    --schema "$TEST_DIR/schema/manifest.schema.json"

# Step 8: Check duplicates
echo ""
echo "🔍 Step 8: Checking for duplicates..."
python "$TEST_DIR/scripts/check_duplicates.py" \
    --catalog "$TEST_DIR/servers"

# Step 9: Check index consistency
echo ""
echo "🔍 Step 9: Checking index consistency..."
python "$TEST_DIR/scripts/check_index_consistency.py" \
    --catalog "$TEST_DIR/servers" \
    --index "$TEST_DIR/index.json"

# Summary
echo ""
echo "================================================"
echo "✅ ALL TESTS PASSED!"
echo "================================================"
echo ""
echo "📊 Summary:"
echo "   - Harvested: $HARVEST_COUNT manifests"
echo "   - Synced: $SYNC_COUNT manifests"
echo "   - Indexed: $INDEX_COUNT manifests"
echo "   - All validations passed"
echo ""
echo "📁 Test output in: $TEST_DIR"
echo ""
echo "🎯 Next steps:"
echo "   1. Review manifests: ls $TEST_DIR/servers/"
echo "   2. Check index: cat $TEST_DIR/index.json | jq '.manifests[0]'"
echo "   3. Deploy to GitHub Actions if everything looks good"
echo ""
