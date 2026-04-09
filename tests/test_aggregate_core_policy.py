from runners.aggregate import AggregateRunner


def test_aggregate_defers_non_core_modules(monkeypatch):
    captured = {}

    def fake_build_tasks(module_names, target_name, known_phones, known_usernames, proxy, timeout, leak_dir):
        captured["module_names"] = list(module_names)
        return [], []

    class _Scheduled:
        modules_run = []
        all_hits = []
        task_results = []

    monkeypatch.setattr("runners.aggregate.build_tasks", fake_build_tasks)
    monkeypatch.setattr("runners.aggregate.LaneScheduler.dispatch", lambda **kwargs: _Scheduled())

    result = AggregateRunner(max_workers=1).run(
        target_name="example.com",
        modules=["subfinder", "shodan", "nmap"],
    )

    assert captured["module_names"] == ["subfinder", "nmap"]
    assert result.extra["deferred_modules"] == ["shodan"]
    assert result.extra["core_snapshot"] is True


def test_aggregate_runs_requested_modules_when_no_core_present(monkeypatch):
    captured = {}

    def fake_build_tasks(module_names, target_name, known_phones, known_usernames, proxy, timeout, leak_dir):
        captured["module_names"] = list(module_names)
        return [], []

    class _Scheduled:
        modules_run = []
        all_hits = []
        task_results = []

    monkeypatch.setattr("runners.aggregate.build_tasks", fake_build_tasks)
    monkeypatch.setattr("runners.aggregate.LaneScheduler.dispatch", lambda **kwargs: _Scheduled())

    result = AggregateRunner(max_workers=1).run(
        target_name="example.com",
        modules=["shodan", "censys"],
    )

    assert captured["module_names"] == ["shodan", "censys"]
    assert result.extra["deferred_modules"] == []
    assert result.extra["core_snapshot"] is False