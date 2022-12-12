import pytest

import numpy as np
import scipy.stats

from big_rl.minigrid.envs import RewardNoise


n_repeats = 100


def test_no_noise():
    noise = RewardNoise(None)

    assert noise(0) == 0
    assert noise(1) == 1
    assert noise(12.3) == 12.3


def test_zero_noise_p_1():
    # Always set to 0
    noise = RewardNoise('zero', 1.0, 'probability')

    assert noise(0) == 0
    assert noise(1) == 0
    assert noise(12.3) == 0


def test_zero_noise_p_1():
    # Never set to 0
    noise = RewardNoise('zero', 0.0, 'probability')

    assert noise(0) == 0
    assert noise(1) == 1
    assert noise(12.3) == 12.3


def test_zero_noise_50_50():
    # 50% chance to set to 0
    noise = RewardNoise('zero', 0.5, 'probability')

    output = np.array([noise(1) for _ in range(n_repeats)])

    assert scipy.stats.binomtest(output.sum(), n=n_repeats, p=0.5).pvalue > 0.05


def test_zero_noise_cycle_steps_0_0_errors():
    # 50% chance to set to 0
    noise = RewardNoise('zero', (0, 0), 'cycle_steps')

    with pytest.raises(Exception):
        noise(1)


def test_zero_noise_cycle_steps_1_1():
    # 1 step with reward, 1 step without reward
    noise = RewardNoise('zero', (1, 1), 'cycle_steps')

    assert noise(1) == 1
    assert noise(2) == 0
    assert noise(3) == 3
    assert noise(4) == 0
    assert noise(5) == 5
    assert noise(6) == 0


def test_zero_noise_cycle_steps_1_2():
    # 1 step with reward, 2 steps without reward
    noise = RewardNoise('zero', (1, 2), 'cycle_steps')

    assert noise(1) == 1
    assert noise(2) == 0
    assert noise(3) == 0
    assert noise(4) == 4
    assert noise(5) == 0
    assert noise(6) == 0
    assert noise(7) == 7


def test_zero_noise_cycle_steps_2_3():
    noise = RewardNoise('zero', (2, 3), 'cycle_steps')

    assert noise(1) == 1
    assert noise(2) == 2

    assert noise(3) == 0
    assert noise(4) == 0
    assert noise(5) == 0

    assert noise(6) == 6
    assert noise(7) == 7

    assert noise(8) == 0
    assert noise(9) == 0
    assert noise(10) == 0


def test_zero_noise_cycle_trials_0_0_errors():
    # 50% chance to set to 0
    noise = RewardNoise('zero', (0, 0), 'cycle_steps')

    with pytest.raises(Exception):
        noise(1)


def test_zero_noise_cycle_trials_1_1():
    # 1 trial with reward, 1 trial without reward
    noise = RewardNoise('zero', (1, 1), 'cycle_trials')

    assert noise(1) == 1

    noise.trial_finished()

    assert noise(2) == 0
    assert noise(3) == 0

    noise.trial_finished()

    assert noise(4) == 4
    assert noise(5) == 5
    assert noise(6) == 6

    noise.trial_finished()

    assert noise(7) == 0

    noise.trial_finished()

    assert noise(8) == 8
    assert noise(9) == 9


def test_gaussian_noise():
    # Make sure the data is normal
    noise = RewardNoise('gaussian', 1.0)

    output = [noise(0.5) for _ in range(n_repeats)]

    assert scipy.stats.normaltest(output).pvalue > 0.05


def test_stop_noise_never_zero():
    noise = RewardNoise('stop', 0.0, 'probability')

    assert noise(0) == 0
    assert noise(1) == 1
    assert noise(12.3) == 12.3


def test_stop_noise_always_zero():
    noise = RewardNoise('stop', 1.0, 'probability')

    assert noise(0) == 0
    assert noise(1) == 0
    assert noise(12.3) == 0


def test_stop_noise_0_steps():
    noise = RewardNoise('stop', 0, 'steps')

    assert noise(1) == 0
    assert noise(2) == 0
    assert noise(3) == 0
    assert noise(4) == 0
    assert noise(5) == 0
    assert noise(6) == 0


def test_stop_noise_1_steps():
    noise = RewardNoise('stop', 1, 'steps')

    assert noise(1) == 1
    assert noise(2) == 0
    assert noise(3) == 0
    assert noise(4) == 0
    assert noise(5) == 0
    assert noise(6) == 0


def test_stop_noise_3_steps():
    noise = RewardNoise('stop', 3, 'steps')

    assert noise(1) == 1
    assert noise(2) == 2
    assert noise(3) == 3

    assert noise(4) == 0
    assert noise(5) == 0
    assert noise(6) == 0


def test_stop_noise_0_trials():
    noise = RewardNoise('stop', 0, 'trials')

    assert noise(1) == 0
    assert noise(2) == 0
    assert noise(3) == 0

    noise.trial_finished()

    assert noise(4) == 0
    assert noise(5) == 0
    assert noise(6) == 0


def test_stop_noise_1_trials():
    noise = RewardNoise('stop', 1, 'trials')

    assert noise(1) == 1
    assert noise(2) == 2
    assert noise(3) == 3

    noise.trial_finished()

    assert noise(4) == 0
    assert noise(5) == 0
    assert noise(6) == 0


def test_stop_noise_3_trials():
    noise = RewardNoise('stop', 3, 'trials')

    assert noise(1) == 1
    assert noise(2) == 2
    assert noise(3) == 3

    noise.trial_finished()

    assert noise(4) == 4
    assert noise(5) == 5
    assert noise(6) == 6

    noise.trial_finished()

    assert noise(7) == 7
    assert noise(8) == 8
    assert noise(9) == 9

    noise.trial_finished()

    assert noise(10) == 0
    assert noise(11) == 0
    assert noise(12) == 0
