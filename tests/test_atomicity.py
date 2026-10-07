"""Proves the recall is all-or-nothing on Couchbase CE: break statement 3, statements 1-2 must roll back.
Run against a freshly reset dataset:  uv run coffee reset && uv run python tests/test_atomicity.py"""

from coffee import actions, config


def count(stmt: str) -> int:
    return next(iter(actions.cluster().query(stmt)))


def main() -> None:
    held = "SELECT RAW COUNT(*) FROM `store`.ops.deliveries WHERE status = 'on_hold'"
    flagged = "SELECT RAW COUNT(*) FROM `store`.ops.feedback WHERE status = 'credit_offered'"
    before = (count(held), count(flagged))

    original = config.sql
    config.sql = lambda name: original(name).replace(
        "UPDATE `store`.ops.roast_lots", "UPDATE `store`.ops.no_such_collection"
    )
    try:
        actions.hold_roast_lots(["RL-4471", "RL-4480"], "GB-88", "atomicity test", "test")
        raise SystemExit("FAIL: transaction should have failed")
    except Exception as e:
        print(f"statement 3 failed as intended: {type(e).__name__}")
    finally:
        config.sql = original

    after = (count(held), count(flagged))
    assert before == after, f"FAIL: partial write survived {before} -> {after}"
    print(f"PASS: nothing changed (on_hold, credit_offered) = {after} - statements 1 and 2 were rolled back")


if __name__ == "__main__":
    main()
