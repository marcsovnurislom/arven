import json

from arven.dashboard.data import list_runs, load_csv, load_decisions, load_manifest, run_dir_for


def write_jsonl(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r) + "\n")


def test_list_runs_is_empty_when_the_index_does_not_exist(tmp_path):
    assert list_runs(tmp_path / "runs.jsonl") == []


def test_list_runs_returns_newest_first(tmp_path):
    index = tmp_path / "runs.jsonl"
    write_jsonl(index, [{"run_id": "a"}, {"run_id": "b"}, {"run_id": "c"}])
    assert [r["run_id"] for r in list_runs(index)] == ["c", "b", "a"]


def test_run_dir_for_prefers_the_entrys_own_dir_over_run_id(tmp_path):
    assert run_dir_for(tmp_path, {"run_id": "x", "dir": "baselines-x/no_trade"}) == tmp_path / "baselines-x/no_trade"
    assert run_dir_for(tmp_path, {"run_id": "x"}) == tmp_path / "x"
    assert run_dir_for(tmp_path, {"run_id": "x", "dir": None}) == tmp_path / "x"


def test_load_manifest_is_none_when_missing(tmp_path):
    assert load_manifest(tmp_path / "nope") is None


def test_load_manifest_reads_run_json(tmp_path):
    run_dir = tmp_path / "run-1"
    run_dir.mkdir()
    (run_dir / "run.json").write_text(json.dumps({"run_id": "run-1", "metrics": {"n_trades": 2}}), encoding="utf-8")
    assert load_manifest(run_dir) == {"run_id": "run-1", "metrics": {"n_trades": 2}}


def test_load_csv_is_an_empty_frame_when_missing(tmp_path):
    df = load_csv(tmp_path, "equity.csv")
    assert df.empty


def test_load_csv_reads_an_existing_file(tmp_path):
    (tmp_path / "equity.csv").write_text("time_ms,equity\n0,10000\n3600000,10050\n", encoding="utf-8")
    df = load_csv(tmp_path, "equity.csv")
    assert list(df.columns) == ["time_ms", "equity"]
    assert len(df) == 2


def test_load_decisions_is_empty_when_missing(tmp_path):
    assert load_decisions(tmp_path) == []


def test_load_decisions_reads_every_line(tmp_path):
    run_dir = tmp_path
    with (run_dir / "decisions.jsonl").open("w", encoding="utf-8") as fh:
        fh.write(json.dumps({"t_ms": 0}) + "\n")
        fh.write(json.dumps({"t_ms": 1}) + "\n")
    assert load_decisions(run_dir) == [{"t_ms": 0}, {"t_ms": 1}]
