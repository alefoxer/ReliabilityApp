import math

import app.core.dependability_backend as backend


def assert_close(actual, expected, rel_tol=1e-12, abs_tol=1e-12):
    assert math.isclose(actual, expected, rel_tol=rel_tol, abs_tol=abs_tol)


def test_f11_matches_manual_series_formula():
    result = backend.f11(t=100, lam_list=[0.001, 0.002])
    expected_p = math.exp(-(0.001 + 0.002) * 100)
    expected_t0 = 1 / 0.003
    assert_close(result["P"], expected_p)
    assert_close(result["T0"], expected_t0)


def test_f51_produces_non_negative_indicators():
    result = backend.f51(t=100, lam=0.001, t_dop=10, Tv_in=5)
    for key in ("P", "T0", "Tpr", "Kg", "Kog"):
        assert result[key] >= 0
    assert_close(result["Kg"], result["T0"] / (result["T0"] + result["Tpr"]))


def expected_f22_t0_cat1(n, m, t_v, lam):
    N = n + m
    numerator = sum(backend.nCr(N, i) * ((lam * t_v) ** i) for i in range(m + 1))
    denominator = n * lam * backend.nCr(N, m) * ((lam * t_v) ** m)
    return numerator / denominator


def expected_f22_t0_cat2(n, m, t_v, lam, lam_p):
    a = lam_p / lam
    sum_val = 0.0
    for i in range(1, m + 1):
        pr_up = 1.0
        for j in range(1, i + 1):
            pr_up *= n + (m + 1 - j) * a
        sum_val += pr_up * ((lam * t_v) ** i) / backend.factorial(i)

    pr_down = 1.0
    for i in range(1, m + 2):
        pr_down *= n + (m + 1 - i) * a
    pr_down *= (lam * t_v) ** m
    return backend.factorial(m) * (sum_val + 1) / (lam * pr_down)


def expected_f22_t0_cat3(n, m, t_v, lam):
    total = 0.0
    for i in range(m + 1):
        total += backend.nCr(m, i) * backend.factorial(i) / ((n * lam * t_v) ** i)
    return total / (n * lam)


def assert_f22_cat123_matches_normative_postprocessing(result, expected_t0, t, t_v, m):
    expected_tv = t_v / (m + 1)
    expected_kg = expected_t0 / (expected_t0 + expected_tv)
    expected_p = math.exp(-t / expected_t0)

    assert_close(result["T0"], expected_t0)
    assert_close(result["Tv"], expected_tv)
    assert_close(result["Kg"], expected_kg)
    assert result["Kg"] < 1.0
    assert_close(result["P"], expected_p)
    assert_close(result["Kog"], result["Kg"] * result["P"])


def test_f22_cat1_preserves_normative_tv_and_kg():
    params = {"cat3": 1, "t": 100, "n": 2, "m": 1, "t_v": 5, "lam": 0.001}
    result = backend.f22(**params)
    expected_t0 = expected_f22_t0_cat1(params["n"], params["m"], params["t_v"], params["lam"])
    assert_f22_cat123_matches_normative_postprocessing(result, expected_t0, params["t"], params["t_v"], params["m"])


def test_f22_cat2_preserves_normative_tv_and_kg():
    params = {"cat3": 2, "t": 100, "n": 2, "m": 1, "t_v": 5, "lam": 0.001, "lam_p": 0.0005}
    result = backend.f22(**params)
    expected_t0 = expected_f22_t0_cat2(params["n"], params["m"], params["t_v"], params["lam"], params["lam_p"])
    assert_f22_cat123_matches_normative_postprocessing(result, expected_t0, params["t"], params["t_v"], params["m"])


def test_f22_cat3_preserves_normative_tv_and_kg():
    params = {"cat3": 3, "t": 100, "n": 2, "m": 1, "t_v": 5, "lam": 0.001}
    result = backend.f22(**params)
    expected_t0 = expected_f22_t0_cat3(params["n"], params["m"], params["t_v"], params["lam"])
    assert_f22_cat123_matches_normative_postprocessing(result, expected_t0, params["t"], params["t_v"], params["m"])


def test_f63_documents_partial_implementation_shape():
    result = backend.f63(t=100, r1=3, r2=2, r3=2, m=1, lam1=0.001, lam2=0.0015, lam3=0.002, t_upr=1000)
    assert 0.0 <= result["P"] <= 1.0
    assert result["T0"] == 0.0
