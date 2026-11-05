"""
Mesin PLS-SEM untuk SEM-PLS Studio (versi Streamlit).

Algoritma mengikuti paket R `seminr` (estimate_pls, PLSc, bootstrap_model,
predict_pls) agar hasilnya sebanding dengan versi Shiny:
- skema inner path weighting / factorial
- outer weights mode A (reflektif/komposit) dan mode B (formatif)
- koreksi PLSc (Dijkstra & Henseler) untuk konstruk reflektif
- reliabilitas (alpha, rhoA, rhoC, AVE), HTMT, Fornell-Larcker, VIF, f2
- bootstrapping persentil, efek tidak langsung spesifik, PLSpredict, SRMR
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
from scipy import stats


# ----------------------------------------------------------------------
# Spesifikasi model
# ----------------------------------------------------------------------
@dataclass
class ModelSpec:
    constructs: List[str]
    items: Dict[str, List[str]]
    mode: Dict[str, str]                      # "A" reflektif, "B" formatif
    paths: List[Tuple[str, str]] = field(default_factory=list)

    @property
    def all_items(self) -> List[str]:
        out: List[str] = []
        for c in self.constructs:
            out += self.items[c]
        return out

    def endogenous(self) -> List[str]:
        seen: List[str] = []
        for _, t in self.paths:
            if t not in seen:
                seen.append(t)
        return seen

    def antecedents(self, c: str) -> List[str]:
        return [f for f, t in self.paths if t == c]


class Structure:
    """Bentuk numerik dari ModelSpec (dipakai berulang saat bootstrap)."""

    def __init__(self, spec: ModelSpec, algorithm: str = "pls"):
        self.spec = spec
        self.cons = list(spec.constructs)
        self.K = len(self.cons)
        self.cidx = {c: k for k, c in enumerate(self.cons)}
        self.items = spec.all_items
        self.p = len(self.items)
        self.blocks: List[np.ndarray] = []
        pos = 0
        for c in self.cons:
            n = len(spec.items[c])
            self.blocks.append(np.arange(pos, pos + n))
            pos += n
        self.item_con = np.concatenate([[k] * len(b) for k, b in enumerate(self.blocks)]).astype(int)
        self.mask = np.zeros((self.p, self.K))
        for k, b in enumerate(self.blocks):
            self.mask[b, k] = 1.0
        # mode efektif: item tunggal selalu mode A
        self.modeB = np.array([spec.mode.get(c, "A") == "B" and len(spec.items[c]) > 1 for c in self.cons])
        self.single = np.array([len(spec.items[c]) == 1 for c in self.cons])
        # tipe C (common factor, dikoreksi PLSc)
        self.typeC = np.array([algorithm == "plsc" and not self.modeB[k] and not self.single[k] for k in range(self.K)])
        self.P = np.zeros((self.K, self.K))
        for f, t in spec.paths:
            self.P[self.cidx[f], self.cidx[t]] = 1.0
        self.endo = [k for k in range(self.K) if self.P[:, k].any()]
        self.ante = {k: np.where(self.P[:, k] > 0)[0] for k in self.endo}


# ----------------------------------------------------------------------
# Utilitas
# ----------------------------------------------------------------------
def _scale(X: np.ndarray):
    m = X.mean(axis=0)
    s = X.std(axis=0, ddof=1)
    if np.any(~np.isfinite(s)) or np.any(s == 0):
        raise ValueError("Ada indikator dengan varians nol; tidak bisa distandardisasi.")
    return (X - m) / s, m, s


def _corr(Y: np.ndarray) -> np.ndarray:
    return np.corrcoef(Y, rowvar=False)


def _rsq_from_cor(R: np.ndarray, ante: np.ndarray, dv: int) -> float:
    idx = np.concatenate([ante, [dv]])
    inv = np.linalg.inv(R[np.ix_(idx, idx)])
    return float(1 - 1 / inv[-1, -1])


# ----------------------------------------------------------------------
# Inti algoritma PLS
# ----------------------------------------------------------------------
def pls_core(X: np.ndarray, S: Structure, inner: str = "path", maxit: int = 300, stop: int = 7):
    """Estimasi PLS pada data mentah X (n x p, urutan kolom = S.items)."""
    Z, mean, sd = _scale(X)
    n = Z.shape[0]
    W = S.mask.copy()
    tol = 10.0 ** (-stop)
    it = 0
    for it in range(maxit + 1):
        Y = Z @ W
        Y = (Y - Y.mean(0)) / Y.std(0, ddof=1)
        R = (Y.T @ Y) / (n - 1)
        if inner == "factorial":
            E = R * (S.P + S.P.T)
        else:
            E = R * S.P.T
            for j in S.endo:
                a = S.ante[j]
                Xa = Y[:, a]
                E[a, j] = np.linalg.solve(Xa.T @ Xa, Xa.T @ Y[:, j])
        Zp = Y @ E
        Zp = (Zp - Zp.mean(0)) / Zp.std(0, ddof=1)
        W_old = W
        W = np.zeros_like(W_old)
        for k, b in enumerate(S.blocks):
            if S.modeB[k]:
                Rxx = (Z[:, b].T @ Z[:, b]) / (n - 1)
                rxz = (Z[:, b].T @ Zp[:, k]) / (n - 1)
                W[b, k] = np.linalg.solve(Rxx, rxz)
            else:
                W[b, k] = (Z[:, b].T @ Zp[:, k]) / (n - 1)
        sc = Z @ W
        W = W / np.sqrt((sc * sc).sum(0) / (n - 1))
        if np.abs(W - W_old).sum() < tol:
            break
    Y = Z @ W
    L = ((Z.T @ Y) / (n - 1)) * S.mask
    R = _corr(Y)
    return dict(Z=Z, mean=mean, sd=sd, W=W, Y=Y, L=L, R=R, iterations=it)


def rho_a(Z: np.ndarray, W: np.ndarray, S: Structure) -> np.ndarray:
    out = np.ones(S.K)
    Rz = _corr(Z)
    for k, b in enumerate(S.blocks):
        if S.modeB[k] or S.single[k]:
            continue
        w = W[b, k][:, None]
        Sm = Rz[np.ix_(b, b)].copy()
        np.fill_diagonal(Sm, 0)
        AA = w @ w.T
        np.fill_diagonal(AA, 0)
        out[k] = ((w.T @ w) ** 2 * ((w.T @ Sm @ w) / (w.T @ AA @ w))).item()
    return out


def structural(core: dict, S: Structure, n: int):
    """Koefisien jalur, R2, loadings final (dengan koreksi PLSc bila perlu)."""
    R = core["R"]
    rho = rho_a(core["Z"], core["W"], S)
    L = core["L"].copy()
    if S.typeC.any():
        q = np.where(S.typeC, np.sqrt(np.clip(rho, 1e-12, None)), 1.0)
        Rc = R / np.outer(q, q)
        np.fill_diagonal(Rc, 1.0)
        for k, b in enumerate(S.blocks):
            if S.typeC[k]:
                w = core["W"][b, k]
                L[b, k] = w * (np.sqrt(rho[k]) / (w @ w))
    else:
        Rc = R
    B = np.zeros((S.K, S.K))
    r2 = {}
    for j in S.endo:
        a = S.ante[j]
        B[a, j] = np.linalg.solve(Rc[np.ix_(a, a)], Rc[a, j])
        rsq = _rsq_from_cor(Rc, a, j)
        r2[j] = (rsq, 1 - (1 - rsq) * ((n - 1) / (n - len(a) - 1)))
    return dict(B=B, Rc=Rc, L=L, rho=rho, r2=r2)


def fit_arrays(X: np.ndarray, S: Structure, inner="path", maxit=300, stop=7):
    core = pls_core(X, S, inner, maxit, stop)
    st = structural(core, S, X.shape[0])
    core.update(st)
    return core


# ----------------------------------------------------------------------
# Ukuran evaluasi
# ----------------------------------------------------------------------
def htmt_matrix(Z: np.ndarray, S: Structure) -> np.ndarray:
    C = np.abs(_corr(Z))
    K = S.K
    H = np.full((K, K), np.nan)
    mono = []
    for b in S.blocks:
        if len(b) > 1:
            sub = C[np.ix_(b, b)]
            k = len(b)
            mono.append((sub.sum() - np.trace(sub)) / (k * (k - 1)))
        else:
            mono.append(1.0)
    for i in range(K):
        for j in range(i + 1, K):
            hthm = C[np.ix_(S.blocks[i], S.blocks[j])].mean()
            H[j, i] = hthm / np.sqrt(mono[i] * mono[j])
    return H


def total_effects(B: np.ndarray) -> np.ndarray:
    K = B.shape[0]
    return np.linalg.inv(np.eye(K) - B) - np.eye(K)


def srmr(fit: dict, S: Structure) -> float:
    Rz = _corr(fit["Z"])
    lam = fit["L"][np.arange(S.p), S.item_con]
    Rc = fit["Rc"]
    Sig = np.outer(lam, lam) * Rc[np.ix_(S.item_con, S.item_con)]
    same = S.item_con[:, None] == S.item_con[None, :]
    formB = S.modeB[S.item_con][:, None] & same
    Sig[formB] = Rz[formB]
    np.fill_diagonal(Sig, 1.0)
    iu = np.tril_indices(S.p)
    d = (Rz - Sig)[iu]
    return float(np.sqrt(np.mean(d ** 2)))


def vif_from_cor(R: np.ndarray) -> np.ndarray:
    return np.diag(np.linalg.inv(R))


@dataclass
class PLSResult:
    spec: ModelSpec
    S: Structure
    settings: dict
    data: pd.DataFrame            # data yang dipakai (sudah ditangani missing-nya)
    fit: dict
    tables: dict


def estimate(data: pd.DataFrame, spec: ModelSpec, algorithm="pls", inner="path",
             maxit=300, stop=7, fsquare=True) -> PLSResult:
    S = Structure(spec, algorithm)
    X = data[S.items].to_numpy(dtype=float)
    n = X.shape[0]
    fit = fit_arrays(X, S, inner, maxit, stop)
    cons, items = S.cons, S.items
    Z, W, L, Y = fit["Z"], fit["W"], fit["L"], fit["Y"]

    # reliabilitas
    Rz = _corr(Z)
    rel_rows = []
    for k, c in enumerate(cons):
        b = S.blocks[k]
        lam = L[b, k]
        if len(b) > 1:
            sub = Rz[np.ix_(b, b)]
            kk = len(b)
            alpha = kk / (kk - 1) * (1 - kk / sub.sum())
        else:
            alpha = 1.0
        s1 = lam.sum() ** 2
        rhoc = s1 / (s1 + (1 - lam ** 2).sum())
        ave = float(np.mean(lam ** 2))
        rel_rows.append(dict(Konstruk=c, alpha=alpha, rhoA=fit["rho"][k], rhoC=rhoc, AVE=ave))
    reliab = pd.DataFrame(rel_rows)

    # matriks
    H = htmt_matrix(Z, S)
    Rc = fit["Rc"]
    FL = np.full((S.K, S.K), np.nan)
    for i in range(S.K):
        FL[i, i] = np.sqrt(reliab.loc[i, "AVE"])
        for j in range(i):
            FL[i, j] = fit["R"][i, j]          # seminr: korelasi skor tanpa koreksi
    cross = (Z.T @ Y) / (n - 1)

    # VIF
    vif_items = []
    for k, c in enumerate(cons):
        b = S.blocks[k]
        if len(b) > 1:
            v = vif_from_cor(Rz[np.ix_(b, b)])
            vif_items += [dict(Konstruk=c, Indikator=items[i], VIF=float(x)) for i, x in zip(b, v)]
    R = fit["R"]
    vif_inner = []
    for j in S.endo:
        a = S.ante[j]
        if len(a) > 1:
            v = vif_from_cor(R[np.ix_(a, a)])
            vif_inner += [dict(Ke=cons[j], Prediktor=cons[i], VIF=float(x)) for i, x in zip(a, v)]

    # f2 (estimasi ulang tanpa jalur, seperti seminr)
    f2 = {}
    if fsquare:
        for f, t in spec.paths:
            jt = S.cidx[t]
            r2_with = fit["r2"][jt][0]
            rest = [pth for pth in spec.paths if pth != (f, t)]
            if not any(tt == t for _, tt in rest):
                r2_wo = 0.0
            else:
                spec2 = ModelSpec(spec.constructs, spec.items, spec.mode, rest)
                S2 = Structure(spec2, algorithm)
                try:
                    fit2 = fit_arrays(X, S2, inner, maxit, stop)
                    r2_wo = fit2["r2"][jt][0]
                except Exception:
                    r2_wo = np.nan
            f2[(f, t)] = (r2_with - r2_wo) / (1 - r2_with)

    T = total_effects(fit["B"])
    tables = dict(
        reliab=reliab, htmt=pd.DataFrame(H, index=cons, columns=cons),
        fl=pd.DataFrame(FL, index=cons, columns=cons),
        cross=pd.DataFrame(cross, index=items, columns=cons),
        vif_items=pd.DataFrame(vif_items), vif_inner=pd.DataFrame(vif_inner),
        f2=f2, total=pd.DataFrame(T, index=cons, columns=cons),
        indirect=pd.DataFrame(T - fit["B"], index=cons, columns=cons),
        srmr=srmr(fit, S),
        scores=pd.DataFrame(Y, columns=cons),
    )
    # AIC/BIC per konstruk endogen (rumus seminr)
    ic = {}
    for j in S.endo:
        k_ = len(S.ante[j])
        sse = (1 - _rsq_from_cor(fit["R"], S.ante[j], j)) * (n - 1)
        ll = n * np.log(sse / n)
        ic[cons[j]] = (ll + 2 * (k_ + 1), ll + (k_ + 1) * np.log(n))
    tables["it_criteria"] = pd.DataFrame(ic, index=["AIC", "BIC"])
    settings = dict(algorithm=algorithm, inner=inner, maxit=maxit, stop=stop)
    return PLSResult(spec, S, settings, data, fit, tables)


# ----------------------------------------------------------------------
# Bootstrapping
# ----------------------------------------------------------------------
def enumerate_chains(paths: List[Tuple[str, str]], max_n: int = 300, max_len: int = 6):
    adj: Dict[str, List[str]] = {}
    for f, t in paths:
        adj.setdefault(f, []).append(t)
    res: List[List[str]] = []

    def walk(path):
        if len(res) >= max_n:
            return
        for nx in adj.get(path[-1], []):
            if nx in path:
                continue
            np_ = path + [nx]
            if len(np_) >= 3:
                res.append(np_)
            if len(np_) < max_len:
                walk(np_)

    for s in dict.fromkeys(f for f, _ in paths):
        walk([s])
    return res


def bootstrap(res: PLSResult, nboot=1000, seed=123, progress: Optional[Callable[[float], None]] = None):
    S, st = res.S, res.settings
    X = res.data[S.items].to_numpy(dtype=float)
    n = X.shape[0]
    rng = np.random.default_rng(seed)
    paths = res.spec.paths
    pidx = [(S.cidx[f], S.cidx[t]) for f, t in paths]
    chains = enumerate_chains(paths)
    cidx_chain = [[S.cidx[c] for c in ch] for ch in chains]
    item_pos = np.arange(S.p)
    B_s, L_s, W_s, H_s, T_s, I_s = [], [], [], [], [], []
    dropped = 0
    for b in range(nboot):
        idx = rng.integers(0, n, n)
        try:
            f = fit_arrays(X[idx], S, st["inner"], st["maxit"], st["stop"])
            B = f["B"]
            T = total_effects(B)
            B_s.append(B[tuple(np.array(pidx).T)] if pidx else np.array([]))
            L_s.append(f["L"][item_pos, S.item_con])
            W_s.append(f["W"][item_pos, S.item_con])
            H_s.append(htmt_matrix(f["Z"], S)[np.tril_indices(S.K, -1)])
            T_s.append((T - B)[np.tril_indices(S.K, -1)] if False else (T - B).ravel())
            I_s.append([np.prod([B[c[i], c[i + 1]] for i in range(len(c) - 1)]) for c in cidx_chain])
        except Exception:
            dropped += 1
        if progress and (b % 25 == 0 or b == nboot - 1):
            progress((b + 1) / nboot)
    return dict(paths=np.array(B_s), loadings=np.array(L_s), weights=np.array(W_s), htmt=np.array(H_s),
                indirect_total=np.array(T_s), specific=np.array(I_s), chains=chains,
                nboot=len(B_s), requested=nboot, dropped=dropped)


def summarize_boot(original: np.ndarray, samples: np.ndarray, alpha=0.05, tail="two") -> pd.DataFrame:
    """Kolom: Original, Rata_boot, SD_boot, t_stat, p_value, CI_bawah, CI_atas."""
    nb = samples.shape[0]
    sd = samples.std(axis=0, ddof=1)
    with np.errstate(divide="ignore", invalid="ignore"):
        t = original / sd
    p2 = 2 * stats.t.sf(np.abs(t), df=max(nb - 1, 1))
    p = p2 / 2 if tail == "one" else p2
    a = 2 * alpha if tail == "one" else alpha
    lo = np.quantile(samples, a / 2, axis=0)
    hi = np.quantile(samples, 1 - a / 2, axis=0)
    return pd.DataFrame(dict(Original=original, Rata_boot=samples.mean(0), SD_boot=sd, t_stat=t,
                             p_value=p, CI_bawah=lo, CI_atas=hi))


# ----------------------------------------------------------------------
# PLSpredict (pendekatan direct antecedent, k-fold)
# ----------------------------------------------------------------------
def plspredict(res: PLSResult, folds=10, reps=1, seed=123) -> pd.DataFrame:
    S, st = res.S, res.settings
    X = res.data[S.items].to_numpy(dtype=float)
    n = X.shape[0]
    endo_items = [i for i in range(S.p) if S.item_con[i] in S.endo]
    rng = np.random.default_rng(seed)
    sse_pls = np.zeros(len(endo_items)); sae_pls = np.zeros(len(endo_items))
    sse_lm = np.zeros(len(endo_items)); sae_lm = np.zeros(len(endo_items))
    sse_naive = np.zeros(len(endo_items)); count = 0
    for _ in range(max(1, reps)):
        perm = rng.permutation(n)
        for k in range(folds):
            test = perm[k::folds]
            train = np.setdiff1d(perm, test)
            f = fit_arrays(X[train], S, st["inner"], st["maxit"], st["stop"])
            Zt = (X[test] - f["mean"]) / f["sd"]
            Yt = Zt @ f["W"]
            Yhat = Yt.copy()
            for j in S.endo:
                Yhat[:, j] = Yt @ f["B"][:, j]
            for m, i in enumerate(endo_items):
                c = S.item_con[i]
                pred = Yhat[:, c] * f["L"][i, c] * f["sd"][i] + f["mean"][i]
                act = X[test, i]
                e = act - pred
                sse_pls[m] += (e ** 2).sum(); sae_pls[m] += np.abs(e).sum()
                sse_naive[m] += ((act - X[train, i].mean()) ** 2).sum()
                # LM benchmark: item endogen ~ item konstruk anteseden
                a_items = np.where(np.isin(S.item_con, S.ante[c]))[0]
                A = np.column_stack([np.ones(len(train)), X[np.ix_(train, a_items)]])
                beta, *_ = np.linalg.lstsq(A, X[train, i], rcond=None)
                e_lm = act - np.column_stack([np.ones(len(test)), X[np.ix_(test, a_items)]]) @ beta
                sse_lm[m] += (e_lm ** 2).sum(); sae_lm[m] += np.abs(e_lm).sum()
        count += n
    out = pd.DataFrame(dict(
        Konstruk=[S.cons[S.item_con[i]] for i in endo_items],
        Indikator=[S.items[i] for i in endo_items],
        Q2_predict=1 - sse_pls / sse_naive,
        RMSE_PLS=np.sqrt(sse_pls / count), RMSE_LM=np.sqrt(sse_lm / count),
        MAE_PLS=sae_pls / count, MAE_LM=sae_lm / count))
    out["PLS_lebih_baik"] = np.where(out.RMSE_PLS < out.RMSE_LM, "Ya", "Tidak")
    return out
