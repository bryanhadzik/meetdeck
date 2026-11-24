import meetdb


def test_three_watches_take_the_middle():
    assert meetdb.timers_time(65.10, 65.40, 65.22) == 65.22
    assert meetdb.timers_time(65.10, 65.41) == 65.25      # two: averaged, thousandths dropped
    assert meetdb.timers_time(0, 65.41, 0) == 65.41
