prelaunch-gate:
	@if [ -z "$(SUMMARY)" ]; then \
		echo "usage: make prelaunch-gate SUMMARY=.cache/prelaunch/<timestamp>/final-summary.json [ARGS='--require-check full_rollout_rehearsal']"; \
		exit 2; \
	fi
	@./scripts/prelaunch_gate.sh "$(SUMMARY)" $(ARGS)