def test_football_freshness_eval_outputs_confusion_matrix():
    from tools.evaluate_football_freshness import evaluate_records

    records = [
        {
            "message": "萨卡怎么没上",
            "label": "WEB_REQUIRED",
            "expected_intent": "lineup",
        },
        {
            "message": "高位逼抢为什么怕长传",
            "label": "WEB_NOT_NEEDED",
            "expected_intent": "stable_football_knowledge",
        },
        {
            "message": "他怎么没上",
            "replied_message": "阿森纳首发出来了，萨卡不在大名单。",
            "label": "WEB_REQUIRED",
            "expected_intent": "lineup",
            "expected_entity": "Bukayo Saka",
        },
    ]

    report = evaluate_records(records)

    assert report["total"] == 3
    assert report["confusion_matrix"]["WEB_REQUIRED"]["WEB_REQUIRED"] == 2
    assert report["confusion_matrix"]["WEB_NOT_NEEDED"]["WEB_NOT_NEEDED"] == 1
    assert report["required_recall"] == 1.0
    assert report["required_precision"] == 1.0
    assert report["mismatches"] == []


def test_football_freshness_seed_fixture_has_no_required_misses():
    from pathlib import Path

    from tools.evaluate_football_freshness import evaluate_records, load_records

    dataset = Path("tests/fixtures/agent_freshness_eval.json")
    report = evaluate_records(load_records(str(dataset)))

    assert report["total"] == 30
    assert report["required_recall"] >= 0.95
    assert report["required_precision"] >= 0.80
    assert report["confusion_matrix"]["WEB_NOT_NEEDED"]["WEB_REQUIRED"] == 0
    assert report["mismatches"] == []
