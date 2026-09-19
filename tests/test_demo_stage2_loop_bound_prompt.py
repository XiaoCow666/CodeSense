"""Regression for the stage-2 loop-bound fill-in prompt.

During a real guided-learning run the fill-in question asks the student to
"计算到第 N 项" (uppercase N), but the accepted answer is the lowercase
identifier ``n`` because the reference program declares ``int n;``. The
question context only shows ``for (int i = 2; i < __; ++i)`` -- the variable
declaration is not visible -- so a student following the question's own wording
types ``N`` and is marked wrong for a "case error" created by the content
itself.

Fix contract: the question prompt must state explicitly that the program's
variable is lowercase ``n``, while ``correct_answer`` stays ``n`` (the value
that actually compiles).

Stdlib only: this test reads the seeder source text. It does not import Flask,
open a database/Redis connection, or start the application.
"""
import re
from pathlib import Path

SOURCE = (
    Path(__file__).resolve().parents[1]
    / "services"
    / "demo_experience.py"
)


def _loop_bound_step_block():
    """Return the source text of the step_id 2 quiz-step dict."""
    text = SOURCE.read_text(encoding="utf-8")
    start = text.index("'step_id': 2")
    end = text.index("'step_id': 3", start)
    return text[start:end]


def test_loop_bound_question_names_lowercase_variable():
    block = _loop_bound_step_block()
    question_match = re.search(r"'question':\s*'([^']*)'", block)
    assert question_match is not None
    question = question_match.group(1)
    # The prompt keeps the math symbol N but must tell the student what the
    # program variable is called, so the natural answer matches correct_answer.
    assert "第 N 项" in question
    assert "小写 n" in question


def test_loop_bound_correct_answer_stays_lowercase_n():
    # n must remain the accepted answer: the reference program reads into a
    # variable declared as `int n;`, so only n keeps the generated code valid.
    block = _loop_bound_step_block()
    assert re.search(r"'correct_answer':\s*'n'", block) is not None
