import pytest
from datetime import datetime, timezone

from corral.tools.cron_parser import parse_field, validate_cron, next_fire_time

def test_parse_field():
    assert parse_field("*", 0, 59) == set(range(60))
    assert parse_field("15", 0, 59) == {15}
    assert parse_field("1,15,30", 0, 59) == {1, 15, 30}
    assert parse_field("1-5", 0, 59) == {1, 2, 3, 4, 5}
    assert parse_field("*/15", 0, 59) == {0, 15, 30, 45}
    assert parse_field("10-20/5", 0, 59) == {10, 15, 20}

def test_validate_cron():
    assert validate_cron("0 * * * *") == True
    assert validate_cron("0 0 1 1 *") == True
    assert validate_cron("invalid") == False
    assert validate_cron("* * * *") == False
    assert validate_cron("60 * * * *") == False # out of range minute
    assert validate_cron("* 24 * * *") == False # out of range hour

def test_next_fire_time():
    # Fixed base time: 2024-01-01 12:00:00 UTC (Monday)
    base_time = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)

    # Every minute
    assert next_fire_time("* * * * *", base_time) == datetime(2024, 1, 1, 12, 1, 0, tzinfo=timezone.utc)
    
    # Next hour at minute 0
    assert next_fire_time("0 * * * *", base_time) == datetime(2024, 1, 1, 13, 0, 0, tzinfo=timezone.utc)
    
    # Specific time: 14:30 daily
    assert next_fire_time("30 14 * * *", base_time) == datetime(2024, 1, 1, 14, 30, 0, tzinfo=timezone.utc)
    
    # Specific time that passed today: 10:30 daily (should fire tomorrow)
    assert next_fire_time("30 10 * * *", base_time) == datetime(2024, 1, 2, 10, 30, 0, tzinfo=timezone.utc)
    
    # Day of week: Every Sunday at midnight
    assert next_fire_time("0 0 * * 0", base_time) == datetime(2024, 1, 7, 0, 0, 0, tzinfo=timezone.utc)
    
    # Day of week: Every Sunday at midnight (using 7)
    assert next_fire_time("0 0 * * 7", base_time) == datetime(2024, 1, 7, 0, 0, 0, tzinfo=timezone.utc)
    
    # Specific month and day: Jan 15th at midnight
    assert next_fire_time("0 0 15 1 *", base_time) == datetime(2024, 1, 15, 0, 0, 0, tzinfo=timezone.utc)
