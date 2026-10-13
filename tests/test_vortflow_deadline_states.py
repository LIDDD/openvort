import pytest

from openvort.plugins.vortflow.engine import (
    STORY_DEVELOPMENT_PENDING_STATES,
    StoryState,
)


@pytest.mark.parametrize(
    "state",
    [
        StoryState.SUBMITTED,
        StoryState.INTAKE,
        StoryState.REVIEW,
        StoryState.PM_REFINE,
        StoryState.DESIGN,
        StoryState.DESIGN_DONE,
        StoryState.PENDING_DEV,
        StoryState.BREAKDOWN,
        StoryState.DEV_ASSIGN,
        StoryState.IN_PROGRESS,
    ],
)
def test_story_before_pending_test_uses_development_deadline(state: StoryState) -> None:
    assert state.value in STORY_DEVELOPMENT_PENDING_STATES


@pytest.mark.parametrize(
    "state",
    [
        StoryState.DEV_DONE,
        StoryState.REJECTED,
        StoryState.PENDING_TEST,
        StoryState.TESTING,
        StoryState.BUGFIX,
        StoryState.TEST_DONE,
        StoryState.REGRESSION,
        StoryState.PENDING_RELEASE,
        StoryState.RELEASED,
        StoryState.DONE,
        StoryState.SUSPENDED,
    ],
)
def test_story_outside_active_development_ignores_development_deadline(state: StoryState) -> None:
    assert state.value not in STORY_DEVELOPMENT_PENDING_STATES
