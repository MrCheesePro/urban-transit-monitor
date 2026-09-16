from app.worker.jobs import MAX_ERROR_LENGTH, JobOutcome, _as_outcome


# A job that just returns how many rows it wrote is a clean success, with nothing to report.
def test_plain_row_count_is_a_clean_success() -> None:
    outcome = _as_outcome(42)
    assert (outcome.rows, outcome.note) == (42, None)


# A job that reports something missing keeps its row count and its note; the note is what makes the
# run partial rather than a plain success.
def test_outcome_with_note_keeps_rows_and_note() -> None:
    outcome = _as_outcome(JobOutcome(rows=1620, note="Trip updates download failed"))
    assert (outcome.rows, outcome.note) == (1620, "Trip updates download failed")


# An outcome with no note is the same thing as a plain row count.
def test_outcome_without_note_is_a_clean_success() -> None:
    assert _as_outcome(JobOutcome(rows=7)).note is None


# Notes share the error column, so they are truncated the same way and cannot overflow it.
def test_long_note_is_truncated() -> None:
    outcome = _as_outcome(JobOutcome(rows=0, note="x" * (MAX_ERROR_LENGTH + 500)))
    assert outcome.note is not None
    assert len(outcome.note) == MAX_ERROR_LENGTH


# An empty note is not something to report, so it does not turn a success into a partial run.
def test_empty_note_is_treated_as_nothing_to_report() -> None:
    assert _as_outcome(JobOutcome(rows=3, note="")).note is None
