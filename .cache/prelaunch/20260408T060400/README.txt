HANNA pre-launch bundle

Generated: 20260408T060400
Root: /Users/admin/Desktop/hanna-v3-2-clean

Artifacts:
- run_discovery.list.txt / .err
- hanna_ui.help.txt / .err
- inventory.json
- preflight.json
- status.txt
- summary.json
- pytest.txt


Interpretation:
- Any non-empty *.err should be reviewed.
- preflight.json must not show blocking dependency failures for the intended rollout preset.
- pytest.txt must end with all selected tests passing.
