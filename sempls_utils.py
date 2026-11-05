"""Fungsi pendukung SEM-PLS Studio (Streamlit): data, model, hasil, narasi, kode R."""
from __future__ import annotations

import io
import json
import re
from datetime import datetime
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from pls_engine import ModelSpec, PLSResult, bootstrap, estimate, summarize_boot

ST_OK, ST_WARN, ST_BAD, ST_NA = "\u2713 Memenuhi", "\u26a0 Perlu dicek", "\u2717 Tidak memenuhi", "\u2014"
ARROW = "\u2192"
NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_. ]*$")
NA_TOKENS = {"", "NA", "N/A", "na", "n/a", "NaN", "nan", "-", ".", "#N/A", "NULL", "null", "?"}


def fmt_id(x, d=3) -> str:
    if x is None or (isinstance(x, float) and np.isnan(x)):
        return "-"
    return f"{x:.{d}f}".replace(".", ",")


def fmt_p_id(p) -> str:
    if p is None or np.isnan(p):
        return "-"
    return "< 0,001" if p < 0.001 else "= " + fmt_id(p)


def fmt_range(x) -> str:
    x = pd.Series(x).dropna()
    return f"{fmt_id(x.min())}\u2013{fmt_id(x.max())}"


# =====================================================================
# 1. DATA
# =====================================================================
def clean_names(names) -> Tuple[List[str], List[Tuple[str, str]]]:
    out, seen, renamed = [], {}, []
    for i, nm in enumerate(names):
        old = "" if nm is None else str(nm).strip()
        new = old if old else f"V{i + 1}"
        new = re.sub(r"[^A-Za-z0-9_.]", "_", new)
        new = re.sub(r"_+", "_", new)
        if not re.match(r"^[A-Za-z]", new):
            new = "X" + new
        base, k = new, 1
        while new in seen:
            new = f"{base}_{k}"; k += 1
        seen[new] = True
        out.append(new)
        if new != old:
            renamed.append((old, new))
    return out, renamed


def to_numeric_col(s: pd.Series) -> Tuple[bool, pd.Series]:
    if pd.api.types.is_bool_dtype(s):
        return False, s
    if pd.api.types.is_numeric_dtype(s):
        return True, s.astype(float)
    v = s.astype("string").str.strip()
    v = v.where(~v.isin(NA_TOKENS), pd.NA)
    nn = v.notna()
    if not nn.any():
        return True, pd.Series(np.nan, index=s.index)
    a = pd.to_numeric(v, errors="coerce")
    if a[nn].notna().all():
        return True, a.astype(float)
    v2 = v.where(~v.fillna("").str.match(r"^-?[0-9]*,[0-9]+$"), v.str.replace(",", ".", n=1, regex=False))
    b = pd.to_numeric(v2, errors="coerce")
    if b[nn].notna().all():
        return True, b.astype(float)
    return False, s


def read_delim_auto(text: str, header=True) -> Tuple[pd.DataFrame, str]:
    text = text.lstrip("\ufeff")
    lines = [l for l in text.replace("\r", "").split("\n") if l.strip()]
    if not lines:
        raise ValueError("Teks data kosong.")
    smp = lines[:30]
    sep = None
    for ch in ["\t", ";", ",", "|"]:
        k = [l.count(ch) for l in smp]
        if all(x > 0 for x in k) and len(set(k)) == 1:
            sep = ch; break
    if sep is None:
        med = {ch: float(np.median([l.count(ch) for l in smp])) for ch in ["\t", ";", ",", "|"]}
        sep = max(med, key=med.get) if max(med.values()) > 0 else r"\s+"
    df = pd.read_csv(io.StringIO("\n".join(lines)), sep=sep, header=0 if header else None, dtype=str,
                     keep_default_na=False, engine="python", skipinitialspace=True)
    return df, sep


def read_uploaded(data: bytes, name: str, sheet=None, header=True) -> Tuple[pd.DataFrame, Optional[str]]:
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    if ext in ("xlsx", "xlsm", "xls"):
        df = pd.read_excel(io.BytesIO(data), sheet_name=sheet if sheet is not None else 0, header=0 if header else None)
        return df, None
    if ext in ("csv", "txt", "tsv", "dat"):
        try:
            txt = data.decode("utf-8")
        except UnicodeDecodeError:
            txt = data.decode("latin-1")
        return read_delim_auto(txt, header)
    if ext in ("sav", "zsav"):
        try:
            import pyreadstat  # noqa: F401
        except ImportError as e:
            raise ValueError("Membaca file SPSS butuh paket 'pyreadstat' (pip install pyreadstat).") from e
        import tempfile, os
        with tempfile.NamedTemporaryFile(suffix="." + ext, delete=False) as tf:
            tf.write(data); path = tf.name
        try:
            df, _ = pyreadstat.read_sav(path, apply_value_formats=False)
        finally:
            os.unlink(path)
        return df, None
    raise ValueError(f"Format .{ext} belum didukung. Gunakan xlsx, xls, csv, txt, atau sav.")


def excel_sheets(data: bytes, name: str) -> List[str]:
    ext = name.rsplit(".", 1)[-1].lower()
    if ext not in ("xlsx", "xlsm", "xls"):
        return []
    try:
        return list(pd.ExcelFile(io.BytesIO(data)).sheet_names)
    except Exception:
        return []


def prepare_data(df: pd.DataFrame, sep: Optional[str] = None) -> dict:
    df = df.copy()
    if df.shape[1] == 0:
        raise ValueError("Data tidak memiliki kolom.")
    new, renamed = clean_names(list(df.columns))
    df.columns = new
    blank = df.apply(lambda c: c.isna() | c.astype("string").str.strip().isin(NA_TOKENS))
    df = df.loc[:, ~blank.all(axis=0)]
    blank = blank.loc[:, df.columns]
    df = df.loc[~blank.all(axis=1)].reset_index(drop=True)
    if df.shape[0] == 0 or df.shape[1] == 0:
        raise ValueError("Data tidak memiliki baris/kolom yang berisi.")
    non_num = []
    for c in df.columns:
        ok, s = to_numeric_col(df[c])
        if ok:
            df[c] = s
        else:
            non_num.append(c)
    num = [c for c in df.columns if c not in non_num]
    const = [c for c in num if not np.isfinite(df[c].std(ddof=1)) or df[c].std(ddof=1) == 0]
    return dict(data=df, vars=[c for c in num if c not in const], non_numeric=non_num, constant=const,
                renamed=[r for r in renamed if r[0] in [o for o, _ in renamed]], n=len(df), sep=sep)


def describe_data(df: pd.DataFrame, vars_: List[str]) -> pd.DataFrame:
    rows = []
    for v in vars_:
        x = df[v]; y = x.dropna()
        rows.append(dict(Indikator=v, N=int(y.size), Missing=int(x.isna().sum()), Mean=y.mean(), Median=y.median(),
                         SD=y.std(ddof=1), Min=y.min(), Max=y.max(), Skewness=y.skew(), Kurtosis=y.kurt()))
    return pd.DataFrame(rows)


# =====================================================================
# 2. MODEL
# =====================================================================
def empty_model() -> dict:
    return {"constructs": [], "items": {}, "mode": {}, "paths": []}


def model_from_editor(j: Optional[dict]) -> dict:
    if not j:
        return empty_model()
    cons = j.get("constructs") or []
    idmap = {str(c.get("id")): str(c.get("name", "")).strip() for c in cons}
    m = empty_model()
    for c in cons:
        nm = str(c.get("name", "")).strip()
        m["constructs"].append(nm)
        m["items"][nm] = [str(i) for i in (c.get("items") or [])]
        m["mode"][nm] = "B" if c.get("mode") == "B" else "A"
    seen = set()
    for p in j.get("paths") or []:
        f = idmap.get(str(p.get("from")), p.get("from_name"))
        t = idmap.get(str(p.get("to")), p.get("to_name"))
        if f and t and (f, t) not in seen:
            seen.add((f, t)); m["paths"].append((f, t))
    return m


def model_for_editor(m: dict) -> dict:
    return {"constructs": [{"name": c, "mode": m["mode"].get(c, "A"), "side": "auto", "items": list(m["items"][c])}
                           for c in m["constructs"]],
            "paths": [{"from": f, "to": t} for f, t in m["paths"]]}


def model_signature(m: dict) -> str:
    a = sorted(f"{c}|{m['mode'].get(c, 'A')}|{','.join(m['items'][c])}" for c in m["constructs"])
    b = sorted(f"{f}>{t}" for f, t in m["paths"])
    return ";".join(a + b)


def to_spec(m: dict) -> ModelSpec:
    return ModelSpec(list(m["constructs"]), {c: list(m["items"][c]) for c in m["constructs"]},
                     dict(m["mode"]), list(m["paths"]))


def parse_syntax(txt: str, vars_: List[str]) -> dict:
    raw = (txt or "").replace("\r", "")
    pieces = []
    for ln, line in enumerate(raw.split("\n"), start=1):
        for part in line.split(";"):
            part = re.sub(r"#.*$", "", part).strip()
            if part:
                pieces.append((ln, part))
    if not pieces:
        raise ValueError("Sintaks masih kosong.")
    m = empty_model()
    paths: List[Tuple[str, str]] = []

    def terms(s):
        return [z.strip() for z in re.split(r"[+,]", s) if z.strip()]

    def expand(tokens, ln):
        out = []
        for tk in tokens:
            if ":" in tk:
                a, b = [z.strip() for z in tk.split(":", 1)]
                if a not in vars_ or b not in vars_:
                    raise ValueError(f"Baris {ln}: rentang '{tk}' tidak dikenali. Kedua nama kolom harus ada di data.")
                i1, i2 = vars_.index(a), vars_.index(b)
                out += vars_[i1:i2 + 1]
            else:
                out.append(tk)
        return out

    for ln, l in pieces:
        if "=~" in l or "<~" in l:
            op = "<~" if "<~" in l else "=~"
            lhs, rhs = l.split(op, 1)
            lhs = lhs.strip(); its = expand(terms(rhs), ln)
            if not lhs or not its:
                raise ValueError(f"Baris {ln} belum lengkap: '{l}'.")
            if not NAME_RE.match(lhs):
                raise ValueError(f"Baris {ln}: nama konstruk '{lhs}' tidak valid (diawali huruf; hanya huruf, angka, spasi, titik, garis bawah).")
            if lhs in m["items"]:
                m["items"][lhs] = list(dict.fromkeys(m["items"][lhs] + its))
            else:
                m["constructs"].append(lhs); m["items"][lhs] = list(dict.fromkeys(its))
            m["mode"][lhs] = "B" if op == "<~" else "A"
        elif "->" in l:
            segs = [z.strip() for z in l.split("->")]
            if len(segs) < 2 or not all(segs):
                raise ValueError(f"Baris {ln} belum lengkap: '{l}'.")
            for s in range(len(segs) - 1):
                for x in terms(segs[s]):
                    for y in terms(segs[s + 1]):
                        paths.append((x, y))
        elif "~" in l:
            lhs, rhs = l.split("~", 1)
            if not terms(lhs) or not terms(rhs):
                raise ValueError(f"Baris {ln} belum lengkap: '{l}'.")
            for y in terms(lhs):
                for x in terms(rhs):
                    paths.append((x, y))
        else:
            raise ValueError(f"Baris {ln} tidak dikenali: '{l}'. Gunakan =~ (reflektif), <~ (formatif), ~ atau -> (jalur struktural).")
    m["paths"] = list(dict.fromkeys(paths))
    undefined = sorted({c for p in m["paths"] for c in p} - set(m["constructs"]))
    if undefined:
        raise ValueError("Konstruk berikut dipakai pada jalur tetapi belum punya indikator: " + ", ".join(undefined)
                         + f". Tambahkan baris seperti: {undefined[0]} =~ item1 + item2")
    if any(f == t for f, t in m["paths"]):
        raise ValueError("Jalur tidak boleh dari konstruk ke dirinya sendiri.")
    return m


def model_to_syntax(m: dict) -> str:
    if not m["constructs"]:
        return ""
    w = max(len(c) for c in m["constructs"])
    meas = [f"{c.ljust(w)} {'<~' if m['mode'].get(c) == 'B' else '=~'} {' + '.join(m['items'][c])}" for c in m["constructs"]]
    tos = list(dict.fromkeys(t for _, t in m["paths"]))
    struct = [f"{t.ljust(w)} ~ {' + '.join(f for f, tt in m['paths'] if tt == t)}" for t in tos]
    return "\n".join(["# Model pengukuran (=~ reflektif, <~ formatif)"] + meas + ["", "# Model struktural (Y ~ X1 + X2)"] + struct)


def has_cycle(paths) -> bool:
    nodes = {c for p in paths for c in p}
    indeg = {n: 0 for n in nodes}
    for _, t in paths:
        indeg[t] += 1
    q = [n for n in nodes if indeg[n] == 0]; e = list(paths); seen = 0
    while q:
        n = q.pop(); seen += 1
        outs = [t for f, t in e if f == n]
        e = [(f, t) for f, t in e if f != n]
        for t in outs:
            indeg[t] -= 1
            if indeg[t] == 0:
                q.append(t)
    return seen < len(nodes)


def validate_model(m: dict, prep: Optional[dict]) -> Tuple[List[Tuple[str, str]], bool]:
    out: List[Tuple[str, str]] = []
    add = lambda lv, msg: out.append((lv, msg))
    if prep is None:
        add("err", "Data belum dimuat (menu 1 \u00b7 Data).")
    else:
        add("ok", f"Data: {prep['n']} baris, {len(prep['vars'])} indikator numerik.")
    nc, np_ = len(m["constructs"]), len(m["paths"])
    add("err", "Model butuh minimal 2 konstruk.") if nc < 2 else add("ok", f"{nc} konstruk.")
    add("err", "Belum ada jalur antar konstruk.") if np_ < 1 else add("ok", f"{np_} jalur struktural.")
    if nc:
        low = [c.lower() for c in m["constructs"]]
        dup = sorted({c for c in m["constructs"] if low.count(c.lower()) > 1})
        if dup: add("err", "Nama konstruk ganda: " + ", ".join(dup) + ".")
        bad = [c for c in m["constructs"] if not NAME_RE.match(c)]
        if bad: add("err", "Nama konstruk tidak valid: " + ", ".join(bad) + ".")
        noitem = [c for c in m["constructs"] if not m["items"][c]]
        if noitem: add("err", "Konstruk tanpa indikator: " + ", ".join(noitem) + ". Seret indikator ke konstruk tersebut.")
        else: add("ok", "Semua konstruk punya indikator.")
        all_items = [i for c in m["constructs"] for i in m["items"][c]]
        dupi = sorted({i for i in all_items if all_items.count(i) > 1})
        if dupi: add("err", "Indikator dipakai lebih dari satu konstruk: " + ", ".join(dupi) + ".")
        if prep is not None and all_items:
            miss = [i for i in all_items if i not in prep["data"].columns]
            if miss: add("err", "Indikator tidak ada di data: " + ", ".join(miss) + ".")
            nn = [i for i in all_items if i in prep["non_numeric"]]
            if nn: add("err", "Indikator bukan angka: " + ", ".join(nn) + ".")
            cc = [i for i in all_items if i in prep["constant"]]
            if cc: add("err", "Indikator bernilai konstan (varians 0): " + ", ".join(cc) + ".")
            used = [i for i in all_items if i in prep["vars"]]
            if used:
                nas = int(prep["data"][used].isna().sum().sum())
                if nas: add("warn", f"Ada {nas} sel kosong pada indikator; ditangani sesuai pilihan missing value di menu Data.")
        single = [c for c in m["constructs"] if len(m["items"][c]) == 1]
        if single: add("warn", "Konstruk item tunggal: " + ", ".join(single) + " (loading = 1; tidak dinilai reliabilitas/AVE).")
        if np_:
            used = {c for p in m["paths"] for c in p}
            iso = [c for c in m["constructs"] if c not in used]
            if iso: add("err", "Konstruk belum terhubung ke jalur mana pun: " + ", ".join(iso) + ".")
            unk = sorted(used - set(m["constructs"]))
            if unk: add("err", "Jalur merujuk konstruk yang tidak ada: " + ", ".join(unk) + ".")
            if has_cycle(m["paths"]): add("err", "Model mengandung putaran (loop); PLS-SEM hanya untuk model rekursif.")
            if prep is not None:
                maxin = max(sum(1 for _, t in m["paths"] if t == c) for c in {t for _, t in m["paths"]})
                formB = [c for c in m["constructs"] if m["mode"].get(c) == "B"]
                maxf = max([len(m["items"][c]) for c in formB], default=0)
                need = 10 * max(maxin, maxf)
                if prep["n"] < need:
                    add("warn", f"Ukuran sampel {prep['n']} < {need} (aturan 10 kali jumlah panah terbanyak ke satu konstruk).")
    return out, not any(lv == "err" for lv, _ in out)


# =====================================================================
# 3. ESTIMASI & HASIL
# =====================================================================
def prepare_estimation_data(prep: dict, m: dict, missing: str) -> Tuple[pd.DataFrame, int]:
    items = list(dict.fromkeys(i for c in m["constructs"] for i in m["items"][c]))
    d = prep["data"][items].astype(float)
    n0 = len(d)
    if missing == "listwise":
        d = d.dropna()
    else:
        d = d.fillna(d.mean())
    if len(d) < 10:
        raise ValueError(f"Data valid terlalu sedikit ({len(d)} baris) setelah penanganan missing value.")
    return d.reset_index(drop=True), n0 - len(d)


def cat_r2(x): return ST_NA if pd.isna(x) else ("Substansial" if x >= .75 else "Moderat" if x >= .5 else "Lemah" if x >= .25 else "Sangat lemah")
def cat_f2(x): return ST_NA if pd.isna(x) else ("Besar" if x >= .35 else "Sedang" if x >= .15 else "Kecil" if x >= .02 else "Tidak berarti")
def cat_vif(x): return ST_NA if pd.isna(x) else ("\u2713 Ideal (< 3)" if x < 3 else "\u26a0 Dapat diterima (3\u20135)" if x < 5 else "\u2717 Kolinearitas tinggi (\u2265 5)")


def classify_mediation(ind_sig, ind_est, dir_exists, dir_sig, dir_est) -> str:
    if not ind_sig: return "Tidak ada mediasi"
    if not dir_exists: return "Mediasi (jalur langsung tidak dimodelkan)"
    if not dir_sig: return "Mediasi penuh (indirect-only)"
    return "Mediasi parsial komplementer" if np.sign(ind_est) == np.sign(dir_est) else "Mediasi parsial kompetitif"


def compute_results(r: PLSResult, boot: Optional[dict], alpha=0.05, tail="two", n_dropped=0) -> dict:
    S, f, T = r.S, r.fit, r.tables
    cons, items = S.cons, S.items
    formative = {c: bool(S.modeB[k]) for k, c in enumerate(cons)}
    single = {c: bool(S.single[k]) for k, c in enumerate(cons)}
    ipos = np.arange(S.p)
    tipe = ["Formatif" if formative[cons[k]] else ("Item tunggal" if single[cons[k]] else "Reflektif") for k in S.item_con]
    load = pd.DataFrame(dict(Konstruk=[cons[k] for k in S.item_con], Indikator=items, Tipe=tipe,
                             Loading=f["L"][ipos, S.item_con], Weight=f["W"][ipos, S.item_con]))
    load["Status"] = [(ST_OK if l >= .7 else ST_WARN if l >= .4 else ST_BAD) if t == "Reflektif" else ST_NA
                      for l, t in zip(load.Loading, load.Tipe)]

    rel = T["reliab"].copy()
    rel["Dinilai"] = [not formative[c] and not single[c] for c in rel.Konstruk]
    def rel_status(row):
        if not row.Dinilai: return ST_NA
        if row.alpha >= .7 and row.rhoC >= .7:
            return "\u26a0 > 0,95 (item mungkin redundan)" if row.rhoC > .95 else ST_OK
        return ST_WARN if row.rhoC >= .6 else ST_BAD
    rel["Reliabilitas"] = rel.apply(rel_status, axis=1)
    rel["Validitas_konvergen"] = [ST_NA if not d else (ST_OK if a >= .5 else ST_BAD) for d, a in zip(rel.Dinilai, rel.AVE)]
    rel["Keterangan"] = ["Formatif: dinilai lewat weight & VIF" if formative[c] else ("Item tunggal" if single[c] else "") for c in rel.Konstruk]
    rel.loc[~rel.Dinilai, ["alpha", "rhoA", "rhoC", "AVE"]] = np.nan

    H = T["htmt"]
    refl = [c for c in cons if not formative[c]]
    htmt_max, htmt_pair = np.nan, ""
    if len(refl) > 1:
        Hs = H.loc[refl, refl]
        if Hs.notna().any().any():
            htmt_max = float(np.nanmax(Hs.values))
            i, j = np.argwhere(Hs.values == htmt_max)[0]
            htmt_pair = f"{Hs.columns[j]} \u2013 {Hs.index[i]}"
    FL = T["fl"]
    fl_ok = {}
    for c in cons:
        if formative[c]: fl_ok[c] = None; continue
        others = pd.concat([FL.loc[c].drop(c), FL[c].drop(c)]).dropna()
        fl_ok[c] = bool((others.abs() < FL.loc[c, c]).all())
    CL = T["cross"]
    own = [cons[k] for k in S.item_con]
    cross_ok = {it: bool((CL.loc[it].abs().drop(o) < abs(CL.loc[it, o])).all()) for it, o in zip(items, own)}

    vif_items = T["vif_items"].copy()
    if len(vif_items): vif_items["Status"] = vif_items.VIF.map(cat_vif)
    vif_inner = T["vif_inner"].copy()
    if len(vif_inner): vif_inner["Status"] = vif_inner.VIF.map(cat_vif)

    P = r.spec.paths
    paths = pd.DataFrame(dict(Hipotesis=[f"H{i + 1}" for i in range(len(P))], Dari=[a for a, _ in P], Ke=[b for _, b in P],
                              Jalur=[f"{a} {ARROW} {b}" for a, b in P],
                              Koefisien=[f["B"][S.cidx[a], S.cidx[b]] for a, b in P],
                              f2=[T["f2"].get((a, b), np.nan) for a, b in P]))
    paths["Efek_f2"] = paths.f2.map(cat_f2)
    endo = list(dict.fromkeys(b for _, b in P))
    r2 = pd.DataFrame(dict(Konstruk=endo, R2=[f["r2"][S.cidx[c]][0] for c in endo], R2_adj=[f["r2"][S.cidx[c]][1] for c in endo]))
    r2["Kategori"] = r2.R2.map(cat_r2)

    def long_eff(M):
        rows = [(a, b, M.loc[a, b]) for a in M.index for b in M.columns if abs(M.loc[a, b]) > 1e-10]
        return pd.DataFrame(rows, columns=["Dari", "Ke", "Efek"]) if rows else None

    res = dict(loadings=load, reliab=rel, htmt=H, htmt_max=htmt_max, htmt_pair=htmt_pair, fl=FL, fl_ok=fl_ok,
               cross=CL, cross_own=own, cross_ok=cross_ok, vif_items=vif_items, paths=paths, r2=r2,
               vif_inner=vif_inner, total=long_eff(T["total"]), total_ind=long_eff(T["indirect"]),
               srmr=T["srmr"], it_criteria=T["it_criteria"], formative=formative, single=single,
               scores=T["scores"], n_used=len(r.data), n_dropped=n_dropped, iterations=f["iterations"],
               alpha=alpha, tail=tail, has_boot=False, boot=None)

    if boot is not None and boot["nboot"] > 1:
        bp = summarize_boot(paths.Koefisien.to_numpy(), boot["paths"], alpha, tail)
        for c in ["Rata_boot", "SD_boot", "t_stat", "p_value", "CI_bawah", "CI_atas"]:
            res["paths"][c] = bp[c].values
        res["paths"]["Signifikan"] = res["paths"].p_value < alpha
        res["paths"]["Keputusan"] = np.where(res["paths"].Signifikan, "\u2713 Diterima (signifikan)", "\u2717 Ditolak (tidak signifikan)")
        lab = pd.DataFrame(dict(Indikator=items, Konstruk=own))
        bl = pd.concat([lab, summarize_boot(load.Loading.to_numpy(), boot["loadings"], alpha, tail)], axis=1)
        bw = pd.concat([lab, summarize_boot(load.Weight.to_numpy(), boot["weights"], alpha, tail)], axis=1)
        tri = np.tril_indices(S.K, -1)
        hh = pd.DataFrame({"Konstruk 1": [cons[j] for j in tri[1]], "Konstruk 2": [cons[i] for i in tri[0]]})
        bh = pd.concat([hh, summarize_boot(H.values[tri], boot["htmt"], alpha, tail)], axis=1)
        Ti = (T["indirect"].values).ravel()
        keep = np.where(np.abs(Ti) > 1e-10)[0]
        bti = None
        if len(keep):
            bti = pd.concat([pd.DataFrame(dict(Dari=[cons[k // S.K] for k in keep], Ke=[cons[k % S.K] for k in keep])),
                             summarize_boot(Ti[keep], boot["indirect_total"][:, keep], alpha, tail)], axis=1)
        ind = None
        if boot["chains"]:
            orig = np.array([np.prod([f["B"][S.cidx[ch[i]], S.cidx[ch[i + 1]]] for i in range(len(ch) - 1)]) for ch in boot["chains"]])
            ind = pd.concat([pd.DataFrame(dict(Jalur=[f" {ARROW} ".join(ch) for ch in boot["chains"]],
                                               Dari=[ch[0] for ch in boot["chains"]], Ke=[ch[-1] for ch in boot["chains"]])),
                             summarize_boot(orig, boot["specific"], alpha, tail)], axis=1)
            ind["Signifikan"] = ind.p_value < alpha
            pp = res["paths"].set_index(["Dari", "Ke"])
            ind["Mediasi"] = [classify_mediation(s, o, (a, b) in pp.index,
                                                 bool(pp.loc[(a, b), "Signifikan"]) if (a, b) in pp.index else None,
                                                 pp.loc[(a, b), "Koefisien"] if (a, b) in pp.index else None)
                              for s, o, a, b in zip(ind.Signifikan, ind.Original, ind.Dari, ind.Ke)]
        res.update(has_boot=True, boot=dict(loadings=bl, weights=bw, htmt=bh, total_indirect=bti, indirect=ind,
                                            nboot=boot["nboot"], dropped=boot["dropped"], alpha=alpha, tail=tail))
    res["js"] = results_for_editor(res)
    return res


def results_for_editor(res: dict) -> dict:
    def clean(d): return {k: (None if v is None or (isinstance(v, float) and np.isnan(v)) else v) for k, v in d.items()}
    pth = {}
    for row in res["paths"].itertuples():
        d = dict(beta=float(row.Koefisien))
        if res["has_boot"]:
            d.update(t=float(row.t_stat), p=float(row.p_value), sig=bool(row.Signifikan))
        pth[f"{row.Dari}->{row.Ke}"] = clean(d)
    items = {}
    for row in res["loadings"].itertuples():
        form = row.Tipe == "Formatif"
        d = dict(value=float(row.Weight if form else row.Loading))
        if res["has_boot"]:
            b = res["boot"]["weights" if form else "loadings"]
            k = b[(b.Indikator == row.Indikator) & (b.Konstruk == row.Konstruk)]
            if len(k):
                d.update(t=float(k.t_stat.iloc[0]), p=float(k.p_value.iloc[0]), sig=bool(k.p_value.iloc[0] < res["alpha"]))
        items[row.Indikator] = clean(d)
    return dict(paths=pth, r2={r.Konstruk: float(r.R2) for r in res["r2"].itertuples()}, items=items, boot=res["has_boot"])


# =====================================================================
# 4. NARASI
# =====================================================================
def build_narrative(res: dict, s: dict) -> List[str]:
    out = []
    L = res["loadings"][res["loadings"].Tipe == "Reflektif"]
    if len(L):
        low = L[L.Loading < .7]
        if not len(low):
            out.append(f"Pada evaluasi model pengukuran, seluruh {len(L)} indikator reflektif memiliki outer loading \u2265 0,70 "
                       f"(rentang {fmt_range(L.Loading)}), sehingga validitas konvergen pada level indikator terpenuhi.")
        else:
            lst = ", ".join(f"{a} ({fmt_id(b)})" for a, b in zip(low.Indikator, low.Loading))
            out.append(f"Pada evaluasi model pengukuran, {len(L) - len(low)} dari {len(L)} indikator reflektif memiliki outer loading \u2265 0,70. "
                       f"Indikator dengan loading di bawah 0,70 adalah {lst}. Indikator dengan loading 0,40\u20130,70 dapat dipertahankan apabila "
                       f"AVE dan composite reliability konstruknya sudah memenuhi; bila belum, pertimbangkan untuk menghapusnya satu per satu.")
    R = res["reliab"][res["reliab"].Dinilai]
    if len(R):
        bad_rel = R.Konstruk[(R.alpha < .7) | (R.rhoC < .7)].tolist()
        bad_ave = R.Konstruk[R.AVE < .5].tolist()
        out.append(f"Nilai Cronbach's alpha berkisar {fmt_range(R.alpha)} dan composite reliability (\u03c1C) berkisar {fmt_range(R.rhoC)}; "
                   + ("seluruh konstruk melampaui 0,70 sehingga dinyatakan reliabel. " if not bad_rel else f"konstruk yang belum mencapai 0,70 adalah {', '.join(bad_rel)}. ")
                   + f"Nilai AVE berkisar {fmt_range(R.AVE)}; "
                   + ("seluruh konstruk \u2265 0,50 sehingga validitas konvergen terpenuhi." if not bad_ave
                      else f"konstruk dengan AVE < 0,50 adalah {', '.join(bad_ave)}, sehingga validitas konvergennya belum terpenuhi."))
    if not np.isnan(res["htmt_max"]):
        out.append(f"Validitas diskriminan diuji dengan HTMT. Nilai HTMT tertinggi adalah {fmt_id(res['htmt_max'])} ({res['htmt_pair']}), "
                   + ("berada di bawah batas 0,90 sehingga validitas diskriminan terpenuhi." if res["htmt_max"] < .9
                      else "melebihi batas 0,90 sehingga kedua konstruk tersebut belum terbedakan dengan baik secara empiris."))
    vi = res["vif_inner"]
    if len(vi):
        v = vi.VIF.max()
        out.append(f"Pada model struktural, nilai VIF antarkonstruk prediktor maksimum {fmt_id(v)}, "
                   + ("sehingga tidak terdapat masalah kolinearitas." if v < 3 else "masih dalam batas yang dapat diterima (< 5)." if v < 5
                      else "yang menandakan kolinearitas tinggi dan perlu ditangani."))
    out.append("Nilai R\u00b2 untuk konstruk endogen: " + "; ".join(f"{a} = {fmt_id(b)} ({c.lower()})" for a, b, c in zip(res["r2"].Konstruk, res["r2"].R2, res["r2"].Kategori))
               + ". Kategori mengikuti batas 0,75 (substansial), 0,50 (moderat), dan 0,25 (lemah).")
    if res["has_boot"]:
        p = res["paths"]
        uji = "satu arah" if s.get("tail") == "one" else "dua arah"
        out.append(f"Pengujian hipotesis menggunakan bootstrapping {res['boot']['nboot']} subsampel (uji {uji}, \u03b1 = {fmt_id(s['alpha'], 2)}). "
                   f"Sebanyak {int(p.Signifikan.sum())} dari {len(p)} hipotesis didukung data.")
        out.append(" ".join(
            f"{r.Hipotesis}: {r.Dari} berpengaruh {'positif' if r.Koefisien >= 0 else 'negatif'} terhadap {r.Ke} dan "
            f"{'signifikan' if r.Signifikan else 'tidak signifikan'} (\u03b2 = {fmt_id(r.Koefisien)}; t = {fmt_id(r.t_stat)}; p {fmt_p_id(r.p_value)}), "
            f"sehingga {r.Hipotesis} {'diterima' if r.Signifikan else 'ditolak'}." for r in p.itertuples()))
        ind = res["boot"]["indirect"]
        if ind is not None and len(ind):
            nmed = ind.Jalur.str.count(ARROW) - 1
            simple, ser = ind[nmed == 1], ind[nmed > 1]
            sig = simple[simple.Signifikan]
            txt = ("Efek tidak langsung (satu mediator) yang signifikan: " + "; ".join(
                f"{r.Jalur} (\u03b2 = {fmt_id(r.Original)}; p {fmt_p_id(r.p_value)}; {r.Mediasi.lower()})" for r in sig.itertuples()) + "."
                   ) if len(sig) else ("Tidak ada efek tidak langsung satu mediator yang signifikan." if len(simple) else "")
            if len(ser):
                txt += f" Terdapat pula {len(ser)} jalur mediasi berantai (serial), {int(ser.Signifikan.sum())} di antaranya signifikan; rinciannya ada di tab Bootstrapping."
            out.append(txt.strip())
    else:
        out.append("Signifikansi koefisien jalur belum diuji. Jalankan bootstrapping untuk memperoleh t-statistik dan p-value setiap hipotesis.")
    return out


# =====================================================================
# 5. KODE R (seminr) & LAPORAN EXCEL
# =====================================================================
def gen_r_code(m: dict, s: dict, src: Optional[dict], prep: Optional[dict]) -> str:
    q = lambda x: f'"{x}"'
    vec = lambda xs: q(xs[0]) if len(xs) == 1 else "c(" + ", ".join(q(x) for x in xs) + ")"
    src = src or {"type": "none"}
    t = src.get("type")
    if t == "file":
        ext = src.get("ext", "")
        if ext in ("xlsx", "xls", "xlsm"):
            read = ["library(readxl)", f"data <- as.data.frame(read_excel({q(src['name'])}"
                    + (f", sheet = {q(src['sheet'])}" if src.get("sheet") else "") + "))  # sesuaikan lokasi file"]
        elif ext in ("sav", "zsav"):
            read = [f"data <- as.data.frame(haven::zap_labels(haven::read_sav({q(src['name'])})))  # sesuaikan lokasi file"]
        else:
            sep = (prep or {}).get("sep") or ","
            sep_txt = '"\\t"' if sep == "\t" else q(sep)
            read = [f"data <- read.table({q(src['name'])}, header = TRUE, sep = {sep_txt}, check.names = FALSE)  # sesuaikan lokasi file"]
    elif t == "paste":
        read = ["# Data ditempel dari Excel. Simpan data Anda sebagai CSV, lalu baca, misalnya:",
                'data <- read.csv("data_saya.csv", check.names = FALSE)']
    elif t == "demo_is":
        read = ['data <- read.csv("demo_is_success.csv")']
    elif t == "demo_mobi":
        read = ["data <- seminr::mobi"]
    else:
        read = ['data <- read.csv("data_saya.csv")']
    ren = []
    if prep and prep.get("renamed"):
        ren = ["# Nama kolom disesuaikan agar valid di R (sama seperti di aplikasi):"] + \
              [f"names(data)[names(data) == {q(a)}] <- {q(b)}" for a, b in prep["renamed"]]
    items = list(dict.fromkeys(i for c in m["constructs"] for i in m["items"][c]))
    cons_lines = []
    for c in m["constructs"]:
        it = m["items"][c]
        if len(it) == 1: cons_lines.append(f"  composite({q(c)}, single_item({q(it[0])}))")
        elif m["mode"].get(c) == "B": cons_lines.append(f"  composite({q(c)}, {vec(it)}, weights = mode_B)")
        elif s.get("algorithm") == "plsc": cons_lines.append(f"  reflective({q(c)}, {vec(it)})")
        else: cons_lines.append(f"  composite({q(c)}, {vec(it)}, weights = mode_A)")
    tos = list(dict.fromkeys(b for _, b in m["paths"]))
    path_lines = [f"  paths(from = {vec([a for a, bb in m['paths'] if bb == t_])}, to = {q(t_)})" for t_ in tos]
    alpha_ci = 2 * s["alpha"] if s.get("tail") == "one" else s["alpha"]
    lines = [
        "# ==================================================================",
        "# Analisis SEM-PLS dengan paket seminr",
        f"# Dibuat otomatis oleh SEM-PLS Studio (Streamlit), {datetime.now():%d-%m-%Y %H:%M}",
        "# Algoritma: " + ("PLSc (consistent PLS)" if s.get("algorithm") == "plsc" else "PLS-SEM standar (composite, mode A untuk reflektif)"),
        "# ==================================================================", "", "library(seminr)", "",
        "# ---- 1. Data ----", *read, *ren,
        *([f"items <- {vec(items)}", "data <- na.omit(data[, items])"] if s.get("missing") == "listwise" else []), "",
        "# ---- 2. Model pengukuran (outer model) ----", "measurement_model <- constructs(", ",\n".join(cons_lines), ")", "",
        "# ---- 3. Model struktural (inner model) ----", "structural_model <- relationships(", ",\n".join(path_lines), ")", "",
        "# ---- 4. Estimasi PLS ----", "pls_model <- estimate_pls(", "  data              = data,",
        "  measurement_model = measurement_model,", "  structural_model  = structural_model,",
        f"  inner_weights     = {'path_factorial' if s.get('inner') == 'factorial' else 'path_weighting'},",
        "  missing           = mean_replacement,", "  missing_value     = NA,",
        f"  maxIt             = {int(s['maxit'])},", f"  stopCriterion     = {int(s['stop'])}", ")",
        "summary_pls <- summary(pls_model)", "",
        "# ---- 5. Evaluasi model pengukuran ----", "summary_pls$loadings", "summary_pls$reliability",
        "summary_pls$validity$htmt", "summary_pls$validity$fl_criteria", "summary_pls$validity$cross_loadings",
        "summary_pls$validity$vif_items", "",
        "# ---- 6. Evaluasi model struktural ----", "summary_pls$paths", "summary_pls$fSquare",
        "summary_pls$vif_antecedents", "summary_pls$total_indirect_effects", "",
        "# ---- 7. Bootstrapping ----",
        f"boot_model <- bootstrap_model(pls_model, nboot = {int(s['nboot'])}, cores = NULL, seed = {int(s['seed'])})",
        f"summary_boot <- summary(boot_model, alpha = {alpha_ci})", "summary_boot$bootstrapped_paths",
        "summary_boot$bootstrapped_loadings", "summary_boot$bootstrapped_total_indirect_paths",
        "t_stat <- summary_boot$bootstrapped_paths[, \"T Stat.\"]",
        f"p_value <- 2 * pt(-abs(t_stat), df = {int(s['nboot'])} - 1)",
        "round(cbind(summary_boot$bootstrapped_paths[, 1:4], p_value), 3)", "", "plot(boot_model)"]
    return "\n".join(lines)


def excel_report(res: dict, s: dict, pred: Optional[pd.DataFrame]) -> bytes:
    info = pd.DataFrame(dict(
        Keterangan=["Algoritma", "Skema inner", "Maks. iterasi", "Iterasi terpakai", "Missing value", "n dipakai",
                    "Bootstrap subsampel", "Alpha", "Uji", "SRMR", "Dibuat"],
        Nilai=["PLSc" if s["algorithm"] == "plsc" else "PLS-SEM standar", s["inner"], s["maxit"], res["iterations"],
               "listwise" if s["missing"] == "listwise" else "mean replacement", res["n_used"],
               res["boot"]["nboot"] if res["has_boot"] else "-", s["alpha"], "satu arah" if s["tail"] == "one" else "dua arah",
               round(res["srmr"], 4), f"{datetime.now():%Y-%m-%d %H:%M}"]))
    mat = lambda M, first="Konstruk": M.reset_index().rename(columns={"index": first})
    b = res["boot"] or {}
    sheets = {
        "Info": info, "Hipotesis_Jalur": res["paths"], "Outer_Loading": res["loadings"],
        "Reliabilitas": res["reliab"].drop(columns=["Dinilai"]), "HTMT": mat(res["htmt"]), "Fornell_Larcker": mat(res["fl"]),
        "Cross_Loading": mat(res["cross"], "Indikator"), "VIF_Indikator": res["vif_items"], "R2": res["r2"],
        "VIF_Inner": res["vif_inner"], "Efek_Total": res["total"], "Efek_Tidak_Langsung": res["total_ind"],
        "Boot_Indirect_Spesifik": b.get("indirect"), "Boot_Indirect_Total": b.get("total_indirect"),
        "Boot_Loading": b.get("loadings"), "Boot_Weight": b.get("weights"), "Boot_HTMT": b.get("htmt"),
        "AIC_BIC": mat(res["it_criteria"], "Kriteria"), "PLSpredict": pred, "Skor_Konstruk": res["scores"],
    }
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="xlsxwriter") as xw:
        for name, df in sheets.items():
            if df is None or not len(df):
                continue
            df.to_excel(xw, sheet_name=name, index=False)
            ws = xw.sheets[name]
            for j, col in enumerate(df.columns):
                width = max(10, min(45, int(max([len(str(col))] + [len(str(v)) for v in df[col].head(200)]) * 1.1)))
                ws.set_column(j, j, width)
    return buf.getvalue()


DEMO_SYNTAX = {
    "is": "\n".join([
        "# Model Kesuksesan Sistem Informasi (DeLone & McLean)", "# Model pengukuran (reflektif)",
        "IQ  =~ IQ1 + IQ2 + IQ3 + IQ4", "SQ  =~ SQ1 + SQ2 + SQ3 + SQ4", "SVQ =~ SV1 + SV2 + SV3 + SV4",
        "ITU =~ IU1 + IU2", "US  =~ US1 + US2 + US3", "NB  =~ NB1 + NB2 + NB3 + NB4", "", "# Model struktural",
        "US  ~ IQ + SQ + SVQ", "ITU ~ IQ + SQ + SVQ + US", "NB  ~ ITU + US"]),
    "mobi": "\n".join([
        "# European Customer Satisfaction Index (data mobi dari seminr)",
        "Image        =~ IMAG1:IMAG5", "Expectation  =~ CUEX1:CUEX3", "Quality      =~ PERQ1:PERQ7",
        "Value        =~ PERV1 + PERV2", "Satisfaction =~ CUSA1:CUSA3", "Complaints   =~ CUSCO", "Loyalty      =~ CUSL1:CUSL3", "",
        "Expectation  ~ Image", "Quality      ~ Expectation", "Value        ~ Expectation + Quality",
        "Satisfaction ~ Image + Expectation + Quality + Value", "Complaints   ~ Satisfaction",
        "Loyalty      ~ Image + Satisfaction + Complaints"]),
}
