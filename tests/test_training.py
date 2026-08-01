import numpy as np
import pytest

from training.train import assert_group_isolation


def test_recording_cannot_appear_in_both_folds() -> None:
    groups = np.array(["a01", "a01", "b01", "b01"])
    assert_group_isolation(groups, np.array([0, 1]), np.array([2, 3]))
    with pytest.raises(AssertionError, match="both"):
        assert_group_isolation(groups, np.array([0, 2]), np.array([1, 3]))
