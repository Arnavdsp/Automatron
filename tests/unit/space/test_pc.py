"""Probability of collision, checked against the case where an analytic answer exists."""

import math

import numpy as np
import pytest

import automatron_space as space

HBR = 20.0


def pc(rel_pos, rel_vel, cov1, cov2, hbr=HBR):
    return space.compute_pc_2d.invoke(
        {
            "rel_pos_m": list(rel_pos),
            "rel_vel_mps": list(rel_vel),
            "cov1_m2": [list(r) for r in cov1],
            "cov2_m2": [list(r) for r in cov2],
            "hbr_m": hbr,
        }
    )


def isotropic(sigma):
    return (np.eye(3) * sigma**2).tolist()


@pytest.mark.parametrize(
    "sigma,miss,radius", [(500.0, 300.0, 5.0), (1000.0, 1200.0, 10.0), (250.0, 100.0, 2.0)]
)
def test_matches_the_small_body_approximation(sigma, miss, radius):
    """For a radius far below the uncertainty, Pc has a closed form to compare against."""
    result = pc(
        [miss, 0.0, 0.0], [0.0, 0.0, 7000.0], isotropic(sigma), np.zeros((3, 3)).tolist(), radius
    )
    analytic = (radius**2 / (2 * sigma**2)) * math.exp(-(miss**2) / (2 * sigma**2))
    assert result["pc"] == pytest.approx(analytic, rel=0.05)


def test_vanishes_when_the_miss_dwarfs_the_uncertainty():
    result = pc([6000.0, 0.0, 0.0], [0.0, 0.0, 7000.0], isotropic(100.0), np.zeros((3, 3)).tolist())
    assert result["pc"] < 1e-30


def test_rises_as_the_miss_shrinks():
    far = pc([800.0, 0, 0], [0, 0, 7000.0], isotropic(300.0), np.zeros((3, 3)).tolist())["pc"]
    near = pc([100.0, 0, 0], [0, 0, 7000.0], isotropic(300.0), np.zeros((3, 3)).tolist())["pc"]
    assert near > far


def test_covariances_combine_additively():
    """Splitting one covariance across both objects must not change the answer."""
    both = pc([200.0, 0, 0], [0, 0, 7000.0], isotropic(200.0), isotropic(200.0))
    combined = pc(
        [200.0, 0, 0],
        [0, 0, 7000.0],
        (np.eye(3) * (2 * 200.0**2)).tolist(),
        np.zeros((3, 3)).tolist(),
    )
    assert both["pc"] == pytest.approx(combined["pc"], rel=1e-6)


def test_a_larger_hard_body_radius_raises_the_probability():
    small = pc([300.0, 0, 0], [0, 0, 7000.0], isotropic(400.0), np.zeros((3, 3)).tolist(), 5.0)
    large = pc([300.0, 0, 0], [0, 0, 7000.0], isotropic(400.0), np.zeros((3, 3)).tolist(), 50.0)
    assert large["pc"] > small["pc"]


def test_reports_its_method_and_assumptions():
    result = pc([300.0, 0, 0], [0, 0, 7000.0], isotropic(400.0), np.zeros((3, 3)).tolist())
    assert "encounter plane" in result["method"]
    assert any("Gaussian" in a for a in result["assumptions"])
    assert result["pc_scientific"].count("e") == 1


def test_a_singular_covariance_is_reported_not_raised():
    result = pc([300.0, 0, 0], [0, 0, 7000.0], np.zeros((3, 3)).tolist(), np.zeros((3, 3)).tolist())
    assert "error" in result


def test_zero_relative_velocity_is_reported_not_raised():
    result = pc([300.0, 0, 0], [0.0, 0.0, 0.0], isotropic(200.0), np.zeros((3, 3)).tolist())
    assert "error" in result
