from app.workflows import state_machine as sm


def test_pipeline_order_and_next():
    assert sm.next_stage(sm.CREATED) == sm.REQUIREMENT_ANALYSIS
    assert sm.next_stage(sm.TEST_GENERATION) == sm.TEST_REVIEW
    assert sm.next_stage(sm.DONE) == sm.DONE


def test_human_checkpoints():
    assert sm.TEST_REVIEW in sm.HUMAN_CHECKPOINTS
    assert sm.EVIDENCE_REVIEW in sm.HUMAN_CHECKPOINTS
    assert sm.ALM_APPROVAL in sm.HUMAN_CHECKPOINTS


def test_full_pipeline_reachable():
    stage, seen = sm.CREATED, [sm.CREATED]
    while stage != sm.DONE:
        stage = sm.next_stage(stage)
        seen.append(stage)
    assert seen[-1] == sm.DONE
    assert sm.EVIDENCE_GENERATION in seen
