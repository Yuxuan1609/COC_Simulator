"""三层信息引擎."""
from module_designer.l1_player import SceneL1, Perceptible, NPCAppearance, load_l1, save_l1
from module_designer.l2_keeper import (
    SceneL2, Encounter, SceneWeapon, AutoTrigger, NPCProfile, load_l2, save_l2,
)
from module_designer.l3_designer import (
    L3Designer, ModuleMeta, WorldRule, LogicChain, Branch,
    SceneIntent, EndingCondition, ToneConstraints, load_l3, save_l3,
)
from module_designer.layered_schema import (
    validate_l1, validate_l2, validate_l3, validate_all, is_valid,
    SchemaReport, SchemaViolation,
)
from module_designer.layered_parser import (
    parse_l1, parse_l2, parse_l3, parse_module, save_module,
    build_l1_prompt, build_l2_prompt, build_l3_prompt,
)
from module_designer.layered_pipeline import (
    run_pipeline, cross_validate_layers, PipelineResult,
    CrossRefReport, CrossRefIssue,
)
