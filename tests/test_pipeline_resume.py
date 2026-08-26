import json, sys, os
from pathlib import Path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
from run_pipeline import InteractiveRunner, PipelineConfig, _apply_step_artifact, _hydrate_prior_steps

def _runner(tmp_path):
    cfg = PipelineConfig(output_dir=str(tmp_path), module_name="t")
    r = InteractiveRunner.__new__(InteractiveRunner)
    r.config = cfg
    r.output_dir = Path(tmp_path)
    r.step1a = {}; r.scenes = []; r.characters = []
    r.step1b = {}; r.chapters = {}
    r.interactions = []; r.scene_movements = {}
    r.events = []; r.auto_triggers = []
    r.l1_data = {}; r.l3_data = {}
    r.npc_profiles = {}; r.l2_assembled = {}
    r.dep_graph = None; r.phase1_clean = {}
    return r

def test_apply_1a_reloads_scenes(tmp_path):
    p = tmp_path / "1a_structured_extraction.json"
    p.write_text(json.dumps({"scenes": [{"name": "A"}], "characters": [{"name": "B"}]}), encoding="utf-8")
    r = _runner(tmp_path)
    _apply_step_artifact(r, p)
    assert r.scenes == [{"name": "A"}]
    assert r.characters == [{"name": "B"}]
    assert r.step1a["scenes"][0]["name"] == "A"

def test_apply_2a_reloads_interactions(tmp_path):
    p = tmp_path / "2a_interactions.json"
    p.write_text(json.dumps({"interactions": [{"id": "IT1"}], "scene_movements": {"x": 1}}), encoding="utf-8")
    r = _runner(tmp_path)
    _apply_step_artifact(r, p)
    assert r.interactions == [{"id": "IT1"}]
    assert r.scene_movements == {"x": 1}

def test_apply_missing_file_raises(tmp_path):
    import pytest
    r = _runner(tmp_path)
    with pytest.raises(FileNotFoundError):
        _apply_step_artifact(r, tmp_path / "nope.json")

def test_apply_unknown_filename_raises(tmp_path):
    import pytest
    p = tmp_path / "unknown_artifact.json"
    p.write_text("{}", encoding="utf-8")
    r = _runner(tmp_path)
    with pytest.raises(ValueError, match="无法回灌"):
        _apply_step_artifact(r, p)

def test_apply_bad_json_raises(tmp_path):
    import pytest
    p = tmp_path / "2a_interactions.json"
    p.write_text("{not json", encoding="utf-8")
    r = _runner(tmp_path)
    with pytest.raises(ValueError, match="中间文件损坏"):
        _apply_step_artifact(r, p)

def test_hydrate_from_step1_then_start_2a(tmp_path):
    run_dir = tmp_path / "20260101_000000"
    (run_dir / "step_1").mkdir(parents=True)
    (run_dir / "step_1" / "1a_structured_extraction.json").write_text(
        json.dumps({"scenes": [{"name": "S"}], "characters": []}), encoding="utf-8")
    (run_dir / "step_1" / "1b_condensed_text.txt").write_text("## 章\n正文", encoding="utf-8")
    r = _runner(tmp_path)
    r.output_dir = run_dir
    _hydrate_prior_steps(r, start_from="step_2a")
    assert r.scenes == [{"name": "S"}]
    assert r.step1a["scenes"][0]["name"] == "S"

def test_runner_resume_dir_reuses_existing(tmp_path):
    run_dir = tmp_path / "20260101_000000"
    run_dir.mkdir()
    cfg = PipelineConfig(output_dir=str(tmp_path), start_from="step_2a",
                         resume_dir=str(run_dir))
    r = InteractiveRunner(cfg)
    assert r.output_dir.resolve() == run_dir.resolve()
    assert not (tmp_path / r.timestamp).exists() or r.timestamp == "20260101_000000"

def test_hydrate_missing_prior_raises(tmp_path):
    import pytest
    r = _runner(tmp_path)
    r.output_dir = tmp_path / "empty"
    r.output_dir.mkdir()
    with pytest.raises(FileNotFoundError):
        _hydrate_prior_steps(r, start_from="step_2a")
