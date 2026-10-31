#!/usr/bin/env bash
# 一鍵示範：產生假資料 → 執行引擎 → 跑驗收測試
set -euo pipefail
cd "$(dirname "$0")"
python3 -c "import openpyxl" 2>/dev/null || pip install -q openpyxl
python3 tools/make_demo_data.py
python3 -m finreport.cli --config config/demo_config.json --audit output/Audit_Error_Log.csv
python3 tests/test_acceptance.py
