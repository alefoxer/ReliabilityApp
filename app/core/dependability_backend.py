import math
import itertools


# ==========================================
# 1. ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ (UTILS)
# ==========================================

def nCr(n: int, k: int) -> int:
    return math.comb(n, k)


def factorial(n: int) -> int:
    return math.factorial(n)


def _fix_overflow(val: float) -> float:
    """Коррекция float погрешностей для вероятности (0 <= P <= 1)"""
    if val > 1.0: return 1.0
    if val < 0.0: return 0.0
    return val


def _fix_overflow_with_tv(kg_val: float, t0_val: float) -> tuple[float, float]:
    """Специфическая коррекция Kg и пересчет Tv (логика из C++)"""
    tv_res = 0.0
    # В C++ логика: if(Kg > 1) { ... Tv = T0*(1-Kg)/Kg * (coef) ... }
    # Здесь упрощенная адаптация под Python, сохраняющая суть
    if kg_val > 1.0:
        kg_val = 0.999999  # Эмуляция отсечения

    if kg_val != 0:
        tv_res = t0_val * (1.0 - kg_val) / kg_val

    return kg_val, tv_res


# --- Внутренние математические утилиты (аналоги private функций C++) ---

def _calc_A(i: int, n: int, m: int, lam: float, t_v: float, t_obn: float, gamma: float) -> float:
    """Вспомогательная функция A из f2.cpp"""
    if i == 0: return 1.0
    N = n + m
    pr = 1.0
    for j in range(i):
        pr *= ((N - j) * t_v + (m - j) * gamma * t_obn)
    pr *= (lam ** i) / math.factorial(i)
    return pr


def _calc_P_internal(i: int, n: int, m: int, lam: float, t_v: float, t_obn: float, gamma: float) -> float:
    """Вспомогательная функция P_ из f2.cpp"""
    N = n + m
    denom_base = 1 + lam * t_v + gamma * lam * t_obn
    if i == 0:
        return 1.0 / (denom_base ** N)
    pr = 1.0
    for j in range(i):
        pr *= ((N - j) * t_v + (m - j) * gamma * t_obn)
    numerator = pr * (lam ** i)
    denominator = math.factorial(i) * (denom_base ** N)
    return numerator / denominator


def _calc_prob(n: int, m: int, t: float, lam_v: list[float]) -> float:
    """Аналог функции prob из f1.cpp (вероятность для разнородных элементов)"""
    N = n + m
    if len(lam_v) < N:
        lam_v = lam_v + [0.0] * (N - len(lam_v))

    lsum = sum(lam_v[:N])
    e_val = math.exp(-lsum * t)
    total_sum = 0.0

    if m > 0:
        for m0 in range(1, m + 1):
            for combo in itertools.combinations(range(N), m0):
                pr = 1.0
                for idx in combo:
                    val_exp = math.exp(-lam_v[idx] * t)
                    if val_exp != 0:
                        pr *= (1 - val_exp) / val_exp
                    else:
                        pr = 0
                total_sum += pr
    return (total_sum * e_val) + e_val


def delta_calc(t: int, n: int, m: int, lam_list: list[float], tv_list: list[float]) -> float:
    """F2.cpp -> delta"""
    if not lam_list or not tv_list: return 0.0
    min_l = min(lam_list)
    max_tv = max(tv_list)
    sum_harm = sum([1.0 / i for i in range(1, m + 1)])
    N = n + m
    term1 = (n * nCr(N, m) * ((min_l * max_tv) ** m)) ** 2
    term1 = term1 * min_l * t / N
    term2 = n * nCr(N, n) * ((min_l * max_tv) ** (m + 1)) * sum_harm
    return term1 + term2


# ==========================================
# 2. ГРУППА F1: Нерезервированные и простые
# ==========================================

def f11(t: int, lam_list: list[float]) -> dict:
    """Последовательное соединение (Existing)"""
    lsum = sum(lam_list)
    P = math.exp(-lsum * t)
    T0 = 1.0 / lsum if lsum != 0 else 0.0
    return {"P": _fix_overflow(P), "T0": T0}


def f12(cat3: int, t: int, n: int, m: int, lam: float = 0, lam_p: float = 0, lam_v: list[float] = None) -> dict:
    """Сложное резервирование (F1.cpp -> f12)"""
    P = 0.0;
    T0 = 0.0

    if cat3 == 1:  # Нагруженный резерв
        N = n + m
        for i in range(m + 1):
            P += nCr(N, i) * math.exp(-(N - i) * lam * t) * ((1 - math.exp(-lam * t)) ** i)
        t0_sum = sum([1.0 / (N - i) for i in range(m + 1) if (N - i) > 0])
        if lam > 0: T0 = t0_sum / lam

    elif cat3 == 2:  # Облегченный резерв
        if lam == 0: return {"P": 0, "T0": 0}
        a = lam_p / lam
        pr = 1.0
        for i in range(m + 1): pr *= (n + i * a)
        denom = (a ** m) * factorial(m)
        pr = pr / denom if denom != 0 else 0

        sum_val = 0.0
        for i in range(m + 1):
            denom_sum = (n + i * a)
            if denom_sum != 0:
                sum_val += ((-1) ** i) * nCr(m, i) * math.exp(-(n + i * a) * lam * t) / denom_sum
        P = pr * sum_val

        t0_sum = sum([1.0 / (n + i * a) for i in range(m + 1) if (n + i * a) != 0])
        T0 = t0_sum / lam

    elif cat3 == 3:  # Ненагруженный резерв
        term_sum = sum([((n * lam * t) ** i) / factorial(i) for i in range(m + 1)])
        P = term_sum * math.exp(-n * lam * t)
        if n * lam != 0: T0 = (m + 1) / (n * lam)

    elif cat3 == 4:  # Разные элементы (интеграл Симпсона)
        if lam_v is None: lam_v = []
        P = _calc_prob(n, m, t, lam_v)
        a_lim, b_lim, N_steps = 0, 100000, 100
        h = (b_lim - a_lim) // N_steps
        sum_integral = 0.0
        t0_curr = a_lim + h
        while t0_curr < b_lim:
            sum_integral += 4 * _calc_prob(n, m, t0_curr, lam_v)
            t0_curr += h
            if t0_curr >= b_lim: break
            sum_integral += 2 * _calc_prob(n, m, t0_curr, lam_v)
            t0_curr += h
        T0 = (h / 3) * (sum_integral + _calc_prob(n, m, a_lim, lam_v) + _calc_prob(n, m, b_lim, lam_v))

    return {"P": _fix_overflow(P), "T0": T0}


def f13(t: int, lam: float, lam_s: float) -> dict:
    """Дублирование с переключателем (F1.cpp -> f13)"""
    d1, d2 = 3 * lam + lam_s, 2 * lam + lam_s
    if d1 == 0 or d2 == 0: return {"P": 0, "T0": 0}

    P = (3 * lam / d1) * (math.exp(-lam * t) - math.exp(-(2 * lam + lam_s) * t)) + \
        (1 / d2) * (lam_s * math.exp(-lam * t) + 2 * lam * math.exp(-(3 * lam + lam_s) * t))
    T0 = 1 / d1 + (9 * lam) / (d1 * d2) + (lam_s / d1) * (1 / lam + 3 / d2) if lam != 0 else 0
    return {"P": _fix_overflow(P), "T0": T0}


def f14(t: int, lam1: float, lam2: float) -> dict:
    P = (math.exp(-3 * lam1 * t) + 3 * math.exp(-2 * lam1 * t) * (1 - math.exp(-lam1 * t))) * math.exp(-lam2 * t)
    denom1, denom2 = 2 * lam1 + lam2, 3 * lam1 + lam2
    T0 = 3 / denom1 - 2 / denom2 if denom1 != 0 and denom2 != 0 else 0
    return {"P": _fix_overflow(P), "T0": T0}


def f15(t: int, lam1: float, lam2: float) -> dict:
    part1 = math.exp(-3 * lam1 * t) + 3 * math.exp(-2 * lam1 * t) * (1 - math.exp(-lam1 * t))
    part2 = math.exp(-3 * lam2 * t) + 3 * math.exp(-2 * lam2 * t) * (1 - math.exp(-lam2 * t))
    P = part1 * part2
    d1, d2, d3 = lam1 + lam2, 2 * lam1 + 3 * lam2, 3 * lam1 + 2 * lam2
    T0 = 35 / (6 * d1) - 6 / d2 - 6 / d3 if d1 * d2 * d3 != 0 else 0
    return {"P": _fix_overflow(P), "T0": T0}


# ==========================================
# 3. ГРУППА F2: Восстанавливаемые системы
# ==========================================

def f21(cat3: int, t: int, n: int, t_v_list: list[float], t_0_list: list[float], lam_list: list[float]) -> dict:
    """Расчет восстанавливаемых систем (mw_2 logic) - Existing"""
    T0 = 0.0;
    Tv = 0.0;
    Kg = 1.0;
    Kog = 1.0;
    P = 1.0
    count = min(n, len(lam_list), len(t_v_list), len(t_0_list))

    if cat3 == 1:  # Независимое восстановление
        sum_t0_inv = 0.0
        for i in range(count):
            k_g_i = 1.0 / (1.0 + lam_list[i] * t_v_list[i])
            Kg *= k_g_i
            if t_0_list[i] > 0:
                sum_t0_inv += 1.0 / t_0_list[i]
                P *= math.exp(-t / t_0_list[i])
                Kog *= k_g_i * math.exp(-t / t_0_list[i])

        if sum_t0_inv != 0: T0 = 1.0 / sum_t0_inv
        if Kg > 1:
            Kg, Tv = _fix_overflow_with_tv(Kg, T0)
        elif Kg != 0:
            Tv = T0 * (1 - Kg) / Kg

    elif cat3 == 2:  # Одновременный простой
        sum_tv_ratio = 0.0;
        sum_t0_inv = 0.0
        for i in range(count):
            if t_0_list[i] > 0:
                sum_t0_inv += 1.0 / t_0_list[i]
                sum_tv_ratio += t_v_list[i] / t_0_list[i]

        if sum_t0_inv != 0:
            T0 = 1.0 / sum_t0_inv
            Tv = sum_tv_ratio / sum_t0_inv
        if (1 + Tv / T0) != 0: Kg = 1.0 / (1 + Tv / T0)

        Kg = _fix_overflow(Kg)
        P = math.exp(-t / T0) if T0 != 0 else 0
        Kog = Kg * P

    return {"T0": T0, "Tv": Tv, "Kg": Kg, "Kog": Kog, "P": P}


def f22(cat3: int, t: int, n: int, m: int, t_v: float, lam: float, lam_p: float = 0, lam_s: float = 0) -> dict:
    T0 = 0.0;
    Tv = 0.0;
    Kg = 1.0;
    Kog = 1.0;
    P = 1.0
    N = n + m

    if cat3 == 1:  # Нагруженный
        sum_t0 = sum([nCr(N, i) * ((lam * t_v) ** i) for i in range(m + 1)])
        denom = n * lam * nCr(N, m) * ((lam * t_v) ** m)
        if denom != 0: T0 = sum_t0 / denom
        Tv = t_v / (m + 1)

    elif cat3 == 2:  # Облегченный
        a = lam_p / lam if lam != 0 else 0
        sum_val = 0.0
        for i in range(1, m + 1):
            pr_up = 1.0
            for j in range(1, i + 1): pr_up *= (n + (m + 1 - j) * a)
            sum_val += pr_up * ((lam * t_v) ** i) / factorial(i)

        pr_down = 1.0
        for i in range(1, m + 2): pr_down *= (n + (m + 1 - i) * a)
        pr_down *= (lam * t_v) ** m

        if lam * pr_down != 0: T0 = factorial(m) * (sum_val + 1) / (lam * pr_down)
        Tv = t_v / (m + 1)

    elif cat3 == 3:  # Ненагруженный
        for i in range(m + 1):
            denom = (n * lam * t_v) ** i
            if denom != 0: T0 += nCr(m, i) * factorial(i) / denom
        if n * lam != 0: T0 /= (n * lam)
        Tv = t_v / (m + 1)

    elif cat3 == 4:  # Ненадежный переключатель
        sum_up = 0.0;
        sum_d1 = 0.0;
        sum_d2 = 0.0
        for i in range(m):
            term = nCr(N, i) * ((lam * t_v) ** i)
            sum_up += term * (1 + lam_s * t_v / (i + 1))
            sum_d1 += term / (i + 1)
            sum_d2 += term * (lam_s * t_v) * (1 / (i + 1) + n * factorial(i) * lam * t_v / factorial(i + 2))

        last = nCr(N, m) * ((lam * t_v) ** m)
        sum_up += last
        sum_d1 = sum_d1 * lam_s * t_v + last
        sum_d2 += (1 + lam * t_v) ** N

        if n * lam * sum_d1 != 0: T0 = sum_up / (n * lam * sum_d1)
        if sum_d2 != 0: Kg = sum_up / sum_d2

    if cat3 in (1, 2, 3):
        Kg = T0 / (T0 + Tv) if (T0 + Tv) != 0 else 0
        Kg = _fix_overflow(Kg)
    elif cat3 == 4:
        Kg, Tv = _fix_overflow_with_tv(Kg, T0)

    if T0 != 0: P = math.exp(-t / T0)
    Kog = Kg * P
    return {"T0": T0, "Tv": Tv, "Kg": Kg, "Kog": Kog, "P": P}


def f23(t: int, m: int, lam_list: list[float], tv_list: list[float]) -> dict:
    T0 = 0.0;
    Tv_res = 0.0;
    Kg = 1.0;
    Kog = 1.0;
    P = 1.0
    count = min(len(lam_list), len(tv_list), m + 1)

    pr1, pr2 = 1.0, 1.0
    for i in range(count):
        val = lam_list[i] * tv_list[i]
        pr1 *= (1 + val)
        pr2 *= val

    sum_val = 0.0
    for i in range(count):
        pr = 1.0
        for j in range(count): pr *= lam_list[j] * tv_list[j]
        if tv_list[i] > 0:
            sum_val += pr / tv_list[i]
            Tv_res += 1.0 / tv_list[i]

    if sum_val != 0: T0 = (pr1 - pr2) / sum_val
    if Tv_res != 0: Tv_res = 1.0 / Tv_res

    pr_kg = 1.0
    for i in range(count):
        val = lam_list[i] * tv_list[i]
        pr_kg *= val / (1 + val)
    Kg = 1.0 - pr_kg

    if T0 != 0: P = math.exp(-t / T0)
    Kog = Kg * P
    return {"T0": T0, "Tv": Tv_res, "Kg": Kg, "Kog": Kog, "P": P}


def f24(cat3: int, t: int, n: int, m: int, lam: float, t_v: float, t_obn: float, gamma: float,
        lam_s: float = 0) -> dict:
    T0 = 0.0;
    Tv = 0.0;
    Kg = 0.0;
    Kog = 1.0;
    P = 1.0
    N = n + m
    if cat3 == 1:
        sum1 = 0.0;
        sum2 = 0.0;
        sum3 = 0.0
        for i in range(m):
            A = _calc_A(i, n, m, lam, t_v, t_obn, gamma)
            sum1 += A / (i + 1)
            sum2 += A * (1 + lam_s * t_v / (i + 1))
            sum3 += A * (lam_s * t_v / (i + 1) + n * factorial(i) * (
                        lam * t_v + gamma * lam * t_obn) * lam_s * t_v / factorial(i + 2))
        A_m = _calc_A(m, n, m, lam, t_v, t_obn, gamma)
        sum1 = sum1 * lam_s * t_v + A_m
        sum2 += A_m
        sum3 += (1 + lam * t_v + gamma * lam * t_obn) ** N

        if sum2 != 0:
            denom = n * gamma * lam + n * (1 - gamma) * lam * sum1 / sum2
            if denom != 0: T0 = 1.0 / denom
        if sum3 != 0: Kg = sum2 / sum3

    elif cat3 == 2:
        for i in range(m + 1): Kg += _calc_P_internal(i, n, m, lam, t_v, t_obn, gamma)
        P_m = _calc_P_internal(m, n, m, lam, t_v, t_obn, gamma)
        if Kg != 0:
            denom = n * lam * (gamma + (1 - gamma) * P_m / Kg)
            if denom != 0: T0 = 1.0 / denom

    Kg, Tv = _fix_overflow_with_tv(Kg, T0)
    if T0 != 0: P = math.exp(-t / T0)
    Kog = Kg * P
    return {"T0": T0, "Tv": Tv, "Kg": Kg, "Kog": Kog, "P": P}


def f25(cat3: int, t: int, n: int, lam: float, t_v: float, t_obn: float, t_vp: float, gamma: float, p_s: float,
        lam_p: float = 0) -> dict:
    if cat3 == 1: lam_p = lam
    alpha = lam_p / lam if lam != 0 else 0
    a1 = lam * t_v * (n + alpha)
    a2 = gamma * lam * t_obn / (1 + n * lam * t_obn)
    denom_a3 = 1 + (n - 1) * (1 + alpha) * lam * t_vp
    a3 = n * lam * (1 - p_s) / denom_a3 if denom_a3 != 0 else 0
    a4 = lam * t_v * ((n - 1 + alpha) * a3 + n * (a1 + a2)) / 2

    denom_t0 = n * lam * (1 - p_s + a1 + a2)
    T0 = (1 + a1 + a2) / denom_t0 if denom_t0 != 0 else 0
    denom_kg = 1 + a1 + a2 + a3 + a4
    Kg = (1 + a1 + a2) / denom_kg if denom_kg != 0 else 0
    Kg = _fix_overflow(Kg)
    Tv = (a3 + a4) / denom_t0 if denom_t0 != 0 else 0
    P = math.exp(-t / T0) if T0 != 0 else 0
    Kog = Kg * P
    return {"T0": T0, "Tv": Tv, "Kg": Kg, "Kog": Kog, "P": P}


def f26(t: int, lam1: float, lam2: float, t_v1: float, t_v2: float) -> dict:
    denom = 6 * (lam1 ** 2) * t_v1 + (1 + 3 * lam1 * t_v1) * lam2
    T0 = (1 + 3 * lam1 * t_v1) / denom if denom != 0 else 0
    num_tv = (1 + 3 * lam1 * t_v1) * lam2 * t_v2 + 3 * (lam1 ** 2) * (t_v1 ** 2)
    Tv = num_tv / denom if denom != 0 else 0
    Kg = 1.0 / (1 + Tv / T0) if (1 + Tv / T0) != 0 else 0
    Kg = _fix_overflow(Kg)
    P = math.exp(-t / T0) if T0 != 0 else 0
    Kog = Kg * P
    return {"T0": T0, "Tv": Tv, "Kg": Kg, "Kog": Kog, "P": P}


def f27(t: int, lam1: float, lam2: float, t_v1: float, t_v2: float) -> dict:
    term1 = 6 * (lam1 ** 2) * t_v1 * (1 + 3 * lam2 * t_v2)
    term2 = 6 * (lam2 ** 2) * t_v2 * (1 + 3 * lam1 * t_v1)
    denom = term1 + term2
    T0 = (1 + 3 * lam1 * t_v1) * (1 + 3 * lam2 * t_v2) / denom if denom != 0 else 0
    num_tv = 3 * (lam2 ** 2) * (t_v2 ** 2) * (1 + 3 * lam1 * t_v1) + 3 * (lam1 ** 2) * (t_v1 ** 2) * (
                1 + 3 * lam2 * t_v2)
    Tv = num_tv / denom if denom != 0 else 0
    Kg = 1.0 / (1 + Tv / T0) if (1 + Tv / T0) != 0 else 0
    Kg = _fix_overflow(Kg)
    P = math.exp(-t / T0) if T0 != 0 else 0
    Kog = Kg * P
    return {"T0": T0, "Tv": Tv, "Kg": Kg, "Kog": Kog, "P": P}


# ==========================================
# 4. ГРУППА F3-F5: Периодический контроль и др.
# ==========================================

def f31(cat3: int, t: int, n: int, m: int, lam: float, t_p: float, Tv_: float = 0) -> dict:
    T0 = 0.0;
    Tv = 0.0;
    Kg = 0.0;
    Kog = 1.0;
    P = 1.0
    N = n + m
    sum1 = 0.0
    for i in range(m + 1):
        sum2 = 0.0
        for j in range(i + 1):
            d = N - i + j
            if d != 0: sum2 += ((-1) ** j) * nCr(i, j) * (1 - math.exp(-d * lam * t_p)) / d
        sum1 += sum2 * nCr(N, i)

    sum3 = 0.0
    for j in range(m + 1):
        if (n + j) != 0: sum3 += ((-1) ** j) * nCr(m, j) * (1 - math.exp(-(n + j) * lam * t_p)) / (n + j)
    sum3 *= n * lam * nCr(N, m)

    if sum3 != 0: T0 = sum1 / sum3

    if cat3 == 1:
        if lam * t_p != 0: Kg = sum1 / (lam * t_p)
        Kg, Tv = _fix_overflow_with_tv(Kg, T0)
    else:
        Tv = Tv_
        if (T0 + Tv) != 0: Kg = T0 / (T0 + Tv)

    K = int(t / t_p) if t_p != 0 else 0
    K1 = int((t + 0.5 * t_p) / t_p) if t_p != 0 else 0
    sum4, sum5, sum6 = 0.0, 0.0, 0.0

    for i in range(m + 1):
        tc = nCr(N, i)
        sum4 += tc * math.exp(-(N - i) * lam * t_p) * ((1 - math.exp(-lam * t_p)) ** i)

        t_r = t - K * t_p
        sum5 += tc * math.exp(-(N - i) * lam * t_r) * ((1 - math.exp(-lam * t_r)) ** i)

        t_calc = t - t_p * (K - 0.5) if cat3 == 1 else t - t_p * (K1 - 0.5)
        sum6 += tc * math.exp(-(N - i) * lam * t_calc) * ((1 - math.exp(-lam * t_calc)) ** i)

    P = _fix_overflow((sum4 ** K) * sum5)
    Kog = _fix_overflow(Kg * (sum4 ** (K if cat3 == 1 else K1)) * sum6)
    return {"T0": T0, "Tv": Tv, "Kg": Kg, "Kog": Kog, "P": P}


def f41(t: int, n: int, m: int, lam1: float, lam2: float, t_v2: float, t_p: float) -> dict:
    T0 = 0.0;
    Tv = 0.0;
    Kg = 0.0;
    Kog = 1.0;
    P = 1.0
    N = n + m
    term_a = (1 - math.exp(-lam1 * t_p))
    term_b = (lam1 * t_p * (1 + lam2 * t_v2))
    frac = term_a / term_b if term_b != 0 else 0

    sum1, sum2, sum3 = 0.0, 0.0, 0.0
    exp_sum = math.exp(-(lam1 + lam2) * t)

    for i in range(m + 1):
        b = nCr(N, i)
        sum1 += b * (frac ** (N - i)) * ((1 - frac) ** i)
        sum2 += b * math.exp(-(N - i) * (lam1 + lam2) * t) * ((1 - exp_sum) ** i)
        f3 = frac * exp_sum
        sum3 += b * (f3 ** (N - i)) * ((1 - f3) ** i)

    denom = n * (lam1 + lam2) * nCr(N, m) * (frac ** n) * ((1 - frac) ** m)
    if denom != 0: T0 = sum1 / denom
    Kg, Tv = _fix_overflow_with_tv(sum1, T0)
    P = _fix_overflow(sum2)
    Kog = _fix_overflow(sum3)
    return {"T0": T0, "Tv": Tv, "Kg": Kg, "Kog": Kog, "P": P}


def f51(t: int, lam: float, t_dop: float, Tv_in: float) -> dict:
    T0 = math.exp(t_dop / Tv_in) / lam if lam != 0 and Tv_in != 0 else 0
    Tpr = Tv_in * math.exp(-t_dop / Tv_in) if Tv_in != 0 else 0
    P = math.exp(-t / T0) if T0 != 0 else 0
    Kg = T0 / (T0 + Tpr) if (T0 + Tpr) != 0 else 0
    Kog = Kg * math.exp(-t / T0) if T0 != 0 else 0
    return {"T0": T0, "Tpr": Tpr, "Kg": Kg, "Kog": Kog, "P": P}


# ==========================================
# 5. ГРУППА F6-F7: Структурная надежность
# ==========================================

def f61(t: int, r1: int, m: int, lambda_upr: float, lam: float) -> dict:
    """Структурная надежность (Existing)"""
    T0 = 0.0;
    P = 0.0
    sum_p = 0.0
    for i in range(m + 1):
        sum_p += nCr(r1, i) * math.exp(-(r1 - i) * lam * t) * ((1 - math.exp(-lam * t)) ** i)
    P = sum_p * math.exp(-lambda_upr * t)

    for i in range(m + 1):
        s = 0.0
        for j in range(i + 1):
            denom = lambda_upr + (r1 - i + j) * lam
            if denom != 0: s += nCr(i, j) * ((-1) ** j) / denom
        T0 += s * nCr(r1, i)
    return {"P": _fix_overflow(P), "T0": T0}


def f62(t: int, r1: int, r2: int, m: int, lam1: float, lam2: float, t_upr: float) -> dict:
    T0 = 0.0;
    P = 1.0
    i_up = m // r2
    sum1 = 0.0
    for i in range(i_up + 1):
        sum2 = 0.0
        limit_j = m - i * r2
        for j in range(limit_j + 1):
            t2 = nCr((r1 - i) * r2, j) * math.exp(-((r1 - i) * r2 - j) * lam2 * t) * ((1 - math.exp(-lam2 * t)) ** j)
            sum2 += t2
        sum1 += sum2 * nCr(r1, i) * math.exp(-(r1 - i) * lam1 * t) * ((1 - math.exp(-lam1 * t)) ** i)

    P = _fix_overflow(sum1 * math.exp(-t / t_upr))

    for k in range(i_up + 1):
        sum3 = 0.0
        for l1 in range(k + 1):
            sum2 = 0.0
            limit_j = m - k * r2
            for j in range(limit_j + 1):
                sum1_in = 0.0
                for l2 in range(j + 1):
                    d = (1 / t_upr + lam1 * (r1 - k + l1) + lam2 * ((r1 - k) * r2 - j + l2))
                    if d != 0: sum1_in += ((-1) ** l2) * nCr(j, l2) / d
                sum2 += sum1_in * nCr((r1 - k) * r2, j)
            sum3 += sum2 * ((-1) ** l1) * nCr(k, l1)
        T0 += sum3 * nCr(r1, k)
    return {"P": P, "T0": T0}


def f63(t: int, r1: int, r2: int, r3: int, m: int, lam1: float, lam2: float, lam3: float, t_upr: float) -> dict:
    """Трехуровневая мажоритарность (только P, T0 не реализован из-за сложности)"""
    T0 = 0.0
    up1, up2 = m // (r2 * r3), m // r3
    sum3 = 0.0
    for k1 in range(up1 + 1):
        sum2 = 0.0
        for k2 in range(up2 - k1 * r2 + 1):
            sum1 = 0.0
            limit_j = m - k1 * r2 * r3 - k2 * r3
            for j in range(limit_j + 1):
                v = ((r1 - k1) * r2 - k2) * r3
                sum1 += nCr(v, j) * math.exp(-(v - j) * lam3 * t) * ((1 - math.exp(-lam3 * t)) ** j)
            sum2 += sum1 * nCr((r1 - k1) * r2, k2) * math.exp(-((r1 - k1) * r2 - k2) * lam2 * t) * (
                        (1 - math.exp(-lam2 * t)) ** k2)
        sum3 += sum2 * nCr(r1, k1) * math.exp(-(r1 - k1) * lam1 * t) * ((1 - math.exp(-lam1 * t)) ** k1)
    P = _fix_overflow(sum3 * math.exp(-t / t_upr))
    return {"P": P, "T0": T0}


def f71(r1: int, m: int, t_upr: float, k_upr: float, ko_upr: float, t_1: float, k_1: float, ko_1: float) -> dict:
    Kg = 0.0;
    Kog = 0.0
    for i in range(m + 1):
        term = nCr(r1, i)
        Kg += term * (k_1 ** (r1 - i)) * ((1 - k_1) ** i)
        Kog += term * (ko_1 ** (r1 - i)) * ((1 - ko_1) ** i)
    Kg = _fix_overflow(Kg * k_upr)
    Kog = _fix_overflow(Kog * ko_upr)
    denom = k_upr * nCr(r1, m) * (k_1 ** (r1 - m)) * ((1 - k_1) ** m) * (1 / t_upr + (r1 - m) / t_1)
    T0 = Kg / denom if denom != 0 else 0
    return {"T0": T0, "Kg": Kg, "Kog": Kog}


def f72(r1: int, r2: int, m: int, t_upr: float, k_upr: float, ko_upr: float,
        t_1: float, k_1: float, ko_1: float, t_2: float, k_2: float, ko_2: float) -> dict:
    Kg = 0.0;
    Kog = 0.0
    up = m // r2
    for i in range(up + 1):
        s1, s2 = 0.0, 0.0
        limit_j = m - i * r2
        for j in range(limit_j + 1):
            t2 = nCr((r1 - i) * r2, j)
            s1 += t2 * (k_2 ** ((r1 - i) * r2 - j)) * ((1 - k_2) ** j)
            s2 += t2 * (ko_2 ** ((r1 - i) * r2 - j)) * ((1 - ko_2) ** j)
        to = nCr(r1, i)
        Kg += s1 * to * (k_1 ** (r1 - i)) * ((1 - k_1) ** i)
        Kog += s2 * to * (ko_1 ** (r1 - i)) * ((1 - ko_1) ** i)
    Kg = _fix_overflow(Kg * k_upr)
    Kog = _fix_overflow(Kog * ko_upr)

    sd = 0.0
    for i in range(up + 1):
        t = nCr(r1, i) * nCr((r1 - i) * r2, m - i * r2)
        t *= (k_1 ** (r1 - i)) * ((1 - k_1) ** i)
        t *= (k_2 ** (r1 * r2 - m + i * r2)) * ((1 - k_2) ** (m - i * r2))
        t *= (1 / t_upr + (r1 - i) / t_1 + (r1 * r2 - m + i * r2) / t_2)
        sd += t
    T0 = Kg / (k_upr * sd) if sd != 0 else 0
    return {"T0": T0, "Kg": Kg, "Kog": Kog}
