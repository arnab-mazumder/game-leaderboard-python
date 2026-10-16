
from datetime import datetime, timedelta, timezone
import random
import pytest

from app.scoring import (
    MAX_SCORE,
    MIN_RUN_SECONDS,
    SEASON_EPOCH,
    ScoreError,
    check_pace,
    check_score,
    decode,
    encode,
    rank_board,
    validate_run,
    week_key,
)

from app.scoring import (
    elapsed_since_epoch,
    page_bounds,
    neighbours,
    week_ttl_seconds,
)


def valid_run():
    started = SEASON_EPOCH + timedelta(days=10)
    return {
        "player": "arnab",
        "run_id": "run-001",
        "region": "north",
        "score": 5000,
        "started_at": started,
        "finished_at": started + timedelta(seconds=60),
    }


# Score validation

@pytest.mark.parametrize("score", [0, 100, MAX_SCORE])
def test_valid_scores(score):
    assert check_score(score) == score


@pytest.mark.parametrize("score", [-1, MAX_SCORE + 1, 10.5, "invalid"])
def test_invalid_scores(score):
    with pytest.raises(ScoreError):
        check_score(score)


# Anti-cheat checks

def test_valid_pace():
    assert check_pace(5000, 60) is True


def test_run_too_short_is_rejected():
    with pytest.raises(ScoreError):
        check_pace(100, MIN_RUN_SECONDS - 1)


def test_impossible_scoring_rate_is_rejected():
    with pytest.raises(ScoreError):
        check_pace(50000, 30)


def test_run_too_long_is_rejected():
    with pytest.raises(ScoreError):
        check_pace(100, 4 * 60 * 60 + 1)


# Full run validation

def test_valid_run_is_normalized():
    result = validate_run(valid_run())
    assert result["player"] == "arnab"
    assert result["region"] == "north"
    assert result["seconds"] == 60


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("player", ""),
        ("run_id", ""),
        ("region", "moon"),
        ("score", -1),
        ("score", MAX_SCORE + 1),
    ],
)
def test_invalid_run_fields_are_rejected(field, value):
    run = valid_run()
    run[field] = value

    with pytest.raises(ScoreError):
        validate_run(run)


def test_duplicate_run_id_is_rejected():
    with pytest.raises(ScoreError):
        validate_run(valid_run(), seen_run_ids={"run-001"})


def test_run_finishing_before_starting_is_rejected():
    run = valid_run()
    run["finished_at"] = run["started_at"] - timedelta(seconds=1)

    with pytest.raises(ScoreError):
        validate_run(run)


def test_impossible_run_pace_is_rejected():
    run = valid_run()
    run["score"] = 50000
    run["finished_at"] = run["started_at"] + timedelta(seconds=30)

    with pytest.raises(ScoreError):
        validate_run(run)


# Encoding and decoding

def test_encode_decode_round_trip():
    finished = SEASON_EPOCH + timedelta(days=100, seconds=12345)

    packed = encode(123456, finished)
    decoded_score, decoded_time = decode(packed)

    assert decoded_score == 123456
    assert decoded_time == finished


def test_higher_score_always_ranks_higher():
    finished = SEASON_EPOCH + timedelta(days=10)

    assert encode(200, finished) > encode(100, finished)


def test_earlier_finish_wins_equal_score():
    earlier = SEASON_EPOCH + timedelta(days=10)
    later = earlier + timedelta(seconds=10)

    assert encode(1000, earlier) > encode(1000, later)


def test_encoded_score_stays_within_double_precision():
    packed = encode(MAX_SCORE, SEASON_EPOCH)

    assert packed < 2**53


# Leaderboard ranking

def test_competition_ranking_and_tie_breaking():
    early = SEASON_EPOCH + timedelta(days=1)
    later = early + timedelta(seconds=10)

    board = rank_board([
        {"player": "alice", "score": 900, "finished_at": later},
        {"player": "bob", "score": 900, "finished_at": early},
        {"player": "charlie", "score": 800, "finished_at": early},
    ])

    assert [entry["player"] for entry in board] == [
        "bob", "alice", "charlie"
    ]
    assert [entry["rank"] for entry in board] == [1, 1, 3]


# Weekly leaderboard keys

def test_week_key_changes_on_monday():
    sunday = datetime(2026, 1, 4, 23, 59, tzinfo=timezone.utc)
    monday = datetime(2026, 1, 5, 0, 0, tzinfo=timezone.utc)

    assert week_key(sunday) != week_key(monday)

def test_randomized_encode_decode_round_trips():
    rng = random.Random(42)

    for _ in range(5000):
        score = rng.randint(0, MAX_SCORE)
        seconds = rng.randint(0, 100_000_000)

        finished = SEASON_EPOCH + timedelta(seconds=seconds)

        packed = encode(score, finished)
        decoded_score, decoded_time = decode(packed)

        assert decoded_score == score
        assert decoded_time == finished


def test_score_ordering_property():
    rng = random.Random(42)
    finished = SEASON_EPOCH + timedelta(days=10)

    for _ in range(1000):
        lower = rng.randint(0, MAX_SCORE - 1)
        higher = rng.randint(lower + 1, MAX_SCORE)

        assert encode(higher, finished) > encode(lower, finished)


# Season time validation

def test_run_before_season_is_rejected():
    before_season = SEASON_EPOCH - timedelta(seconds=1)

    with pytest.raises(ScoreError):
        elapsed_since_epoch(before_season)


def test_run_beyond_season_clock_is_rejected():
    beyond_clock = SEASON_EPOCH + timedelta(seconds=2**32)

    with pytest.raises(ScoreError):
        elapsed_since_epoch(beyond_clock)


# Decode validation

def test_negative_encoded_score_is_rejected():
    with pytest.raises(ScoreError):
        decode(-1)


# Pagination

def test_page_bounds():
    assert page_bounds(2, 10) == (10, 19)


def test_invalid_page_size_is_rejected():
    with pytest.raises(ScoreError):
        page_bounds(1, 0)


# Nearby leaderboard positions

def test_neighbours_at_first_rank():
    assert neighbours(1) == (0, 2)


def test_invalid_rank_is_rejected():
    with pytest.raises(ScoreError):
        neighbours(0)


# Weekly board expiry

def test_week_ttl_includes_remaining_week_and_grace_period():
    when = datetime(2026, 1, 5, 0, 0, tzinfo=timezone.utc)

    assert week_ttl_seconds(when) == 7 * 86400 * 4
