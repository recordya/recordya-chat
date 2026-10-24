from src.llm.repetition import repeated_tail_start


def test_finds_the_start_of_a_repeated_run_at_the_end():
    text = "Numer repertorium: A 2425/2019.\n\ncase_id: 17" + "393847" * 100

    start = repeated_tail_start(text)

    assert start is not None
    assert text[:start] == "Numer repertorium: A 2425/2019.\n\ncase_id: 1"


def test_ignores_short_repetition_and_ordinary_text():
    assert repeated_tail_start("ha" * 50) is None
    assert repeated_tail_start("| a | b |\n|---|---|\n| 1 | 2 |\n" * 3) is None
    prose = " ".join(f"Akapit {n} umowy najmu lokalu, paragraf {n}." for n in range(60))
    assert repeated_tail_start(prose) is None


def test_a_loop_must_reach_the_end_of_the_text():
    text = "x" * 1000 + " i dalej normalna odpowiedź " + "abc"

    assert repeated_tail_start(text) is None
