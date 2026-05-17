#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_DIR"

mkdir -p outputs \
  outputs/audit_context \
  outputs/evidence_scope \
  outputs/google_ai_mode \
  outputs/content_intelligence \
  outputs/external_pages \
  outputs/visibility \
  outputs/source_landscape \
  outputs/page_scores \
  outputs/recommendations \
  outputs/dashboard \
  outputs/bodhi \
  outputs/control

echo "{\"status\":\"success\",\"project_dir\":\"$PROJECT_DIR\",\"outputs_dir\":\"$PROJECT_DIR/outputs\"}"

python3 scripts/build_query_workbench_bundle.py --project-root . --brand "${BRAND:-Nissan}" --market "${MARKET:-Japan}" --domain "${DOMAIN:-https://www.nissan.co.jp}"
