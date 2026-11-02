import numpy as np

from sanae.avatar.outfit import nearest, refit, snug


def test_nearest_finds_closest_points():
    to = np.array([[0, 0, 0], [1, 0, 0], [5, 0, 0]], float)
    idx, dist = nearest(np.array([[0.9, 0, 0]]), to, 2)
    assert set(idx[0]) == {0, 1}
    assert np.isclose(dist[0].min(), 0.1)


def test_refit_follows_the_body_change():
    donor = np.array([[x, y, 0] for x in range(-2, 3) for y in range(-2, 3)], float)
    body = donor + [0, 0.1, 0.02]                         # higher up, moved forward
    body[12] += [0, 0, 0.5]                               # one far-off vertex moved a lot
    cloth = np.array([[-2.0, -2.0, 0.05]])
    out = refit(cloth, donor, body)
    assert np.allclose(out, [[-2.0, -1.9, 0.07]], atol=1e-3)   # follows the body right under it


def test_snug_only_shrinks_the_gap_off_the_skin():
    body = np.array([[x, y, 0] for x in np.linspace(-1, 1, 5) for y in np.linspace(-1, 1, 5)], float)
    normals = np.tile([0, 0, 1.0], (len(body), 1))
    cloth = np.array([[0.0, 0.0, 0.10], [0.0, 0.0, 0.005], [0.5, 0.5, -0.05]])
    out = snug(cloth, body, normals, keep=0.5)
    assert np.allclose(out[0], [0, 0, 0.05])                  # half the gap kept, same spot
    assert np.allclose(out[1], cloth[1])                      # already close: left alone
    assert np.allclose(out[2], cloth[2])                      # behind the skin: left alone
    assert np.isclose(snug(np.array([[0, 0, 0.012]]), body, normals, keep=0.1)[0, 2], 0.008)
