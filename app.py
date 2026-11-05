"""
SEM-PLS Studio (versi Streamlit)
Analisis PLS-SEM dengan editor diagram bergaya SmartPLS.
Jalankan:  streamlit run app.py
"""
from __future__ import annotations

import json
from pathlib import Path

import altair as alt
import numpy as np
import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

from pls_engine import bootstrap, estimate, plspredict
from sempls_utils import (DEMO_SYNTAX, build_narrative, compute_results, describe_data, excel_report, excel_sheets,
                          fmt_id, gen_r_code, model_for_editor, model_from_editor, model_signature, model_to_syntax,
                          parse_syntax, prepare_data, prepare_estimation_data, read_delim_auto, read_uploaded,
                          to_spec, validate_model)

APP_DIR = Path(__file__).parent
st.set_page_config(page_title="SEM-PLS Studio", page_icon="\U0001F537", layout="wide",
                   initial_sidebar_state="collapsed")
_editor = components.declare_component("pls_editor", path=str(APP_DIR / "components" / "pls_editor"))
ss = st.session_state

# ---------------------------------------------------------------------
# Gaya
# ---------------------------------------------------------------------
st.markdown("""
<style>
.block-container { padding-top: 3.4rem; padding-bottom: 2rem; }
.brand { display:flex; align-items:center; gap:10px; font-weight:700; font-size:1.35rem; color:#13213c; }
.brand small { font-weight:400; color:#5b6b85; font-size:.85rem; }
div[role="radiogroup"][aria-label="Navigasi"] { gap: 6px; }
.statgrid { display:grid; grid-template-columns:repeat(auto-fill,minmax(180px,1fr)); gap:12px; margin:4px 0 14px; }
.statcard { background:#fff; border:1px solid #dfe5ee; border-top:4px solid #2f6fdb; border-radius:6px; padding:9px 13px; }
.statcard.amber{border-top-color:#d4a017}.statcard.teal{border-top-color:#0f8a6a}.statcard.warn{border-top-color:#e0a800}.statcard.muted{border-top-color:#b8c3d4}
.statcard .t { font-size:.78rem; color:#5b6b85; font-weight:600; }
.statcard .v { font-size:1.55rem; font-weight:700; color:#13213c; font-variant-numeric:tabular-nums; }
.statcard .c { font-size:.76rem; color:#5b6b85; }
.checklist { list-style:none; padding:0; margin:0 0 .4rem; font-size:.88rem; }
.checklist li { display:flex; gap:8px; padding:3px 0; line-height:1.35; }
.checklist .ic { flex:0 0 16px; font-weight:700; }
.checklist .ok .ic{color:#0f8a6a}.checklist .warn .ic{color:#b07d00}.checklist .err .ic{color:#c2413a}.checklist .err{color:#8d2a24}
.narrative p { line-height:1.6; margin-bottom:.6rem; }
.small-help { color:#5b6b85; font-size:.86rem; }
</style>
""", unsafe_allow_html=True)


def stat_card(title, value, cap="", tone="blue"):
    return f'<div class="statcard {tone}"><div class="t">{title}</div><div class="v">{value}</div><div class="c">{cap}</div></div>'


def help_txt(t):
    st.markdown(f'<div class="small-help">{t}</div>', unsafe_allow_html=True)


# ---------------------------------------------------------------------
# State awal; kunci widget "disentuh" agar tidak hilang saat pindah halaman
# ---------------------------------------------------------------------
DEFAULTS = dict(prep=None, src=None, data_sig=None, data_msg=None,
                model_json={"constructs": [], "paths": []}, model_rev=0,
                res=None, plsres=None, settings=None, used_sig=None, used_json=None, used_model=None,
                warnings=[], pred=None, res_token=0, syntax_msg=None, json_sig=None, run_errors=None, xlsx=None)
WIDGETS = dict(nav="1 \u00b7 Data", data_src="file", header=True, paste_txt="", demo_model=True, missing="mean",
               alg="pls", inner="path", maxit=300, stop=7, nboot=1000, alpha=0.05, tail="two", seed=123,
               syntax="", diag_label="coef", diag_items=True, pred_folds=10, pred_reps=1)
for k, v in DEFAULTS.items():
    ss.setdefault(k, v)
for k, v in WIDGETS.items():
    ss[k] = ss[k] if k in ss else v

PAGES = ["1 \u00b7 Data", "2 \u00b7 Model", "3 \u00b7 Hasil", "Panduan"]
if "goto" in ss:
    ss.nav = PAGES[{"data": 0, "model": 1, "hasil": 2}[ss.pop("goto")]]


def settings_now():
    return dict(algorithm=ss.alg, inner=ss.inner, maxit=int(ss.maxit), stop=int(ss.stop), missing=ss.missing,
                nboot=int(ss.nboot), alpha=float(ss.alpha), tail=ss.tail, seed=int(ss.seed))


def clear_results():
    ss.res = None; ss.plsres = None; ss.used_sig = None; ss.used_json = None; ss.used_model = None
    ss.pred = None; ss.warnings = []; ss.res_token += 1; ss.xlsx = None


def load_model(editor_model: dict):
    ss.model_json = editor_model
    ss.model_rev += 1


def set_data(df: pd.DataFrame, src: dict, sep=None) -> bool:
    try:
        prep = prepare_data(df, sep)
    except Exception as e:
        ss.data_msg = ("error", f"Data gagal dibaca: {e}"); return False
    if not prep["vars"]:
        ss.data_msg = ("error", "Tidak ada kolom angka yang bisa dipakai sebagai indikator."); return False
    ss.prep, ss.src = prep, src
    clear_results()
    ss.data_msg = ("success", f"Data dimuat: {prep['n']} baris, {len(prep['vars'])} indikator.")
    return True


def load_demo(which: str):
    df = pd.read_csv(APP_DIR / "data" / ("demo_is_success.csv" if which == "is" else "demo_mobi.csv"))
    ss.data_sig = None
    if set_data(df, {"type": "demo_is" if which == "is" else "demo_mobi"}) and ss.demo_model:
        ss.syntax = DEMO_SYNTAX[which]
        load_model(model_for_editor(parse_syntax(DEMO_SYNTAX[which], ss.prep["vars"])))


# ---------------------------------------------------------------------
# Tabel bergaya
# ---------------------------------------------------------------------
def _status_css(v):
    if not isinstance(v, str):
        return ""
    if v.startswith("\u2713"): return "background-color:#e3f4ed;color:#0b6b52;font-weight:600"
    if v.startswith("\u26a0"): return "background-color:#fff3cf;color:#7a5600;font-weight:600"
    if v.startswith("\u2717"): return "background-color:#fbe4e2;color:#a1322c;font-weight:600"
    return ""


def show_df(df, status_cols=(), rename=None, p_cols=(), digits=3, max_h=620):
    if df is None or not len(df):
        st.caption("Tidak ada data untuk ditampilkan."); return
    d = df.copy()
    for c in p_cols:
        if c in d:
            d[c] = d[c].map(lambda p: "" if pd.isna(p) else ("< 0.001" if p < 0.001 else f"{p:.3f}"))
    status_cols = list(status_cols)
    if rename:
        d = d.rename(columns=rename)
        status_cols = [rename.get(c, c) for c in status_cols]
    num = [c for c in d.columns if pd.api.types.is_float_dtype(d[c])]
    for c in [c for c in num if d[c].isna().any()]:     # hindari tampilan "None"
        d[c] = d[c].map(lambda v: "" if pd.isna(v) else f"{v:.{digits}f}")
        num.remove(c)
    sty = d.style.format({c: f"{{:.{digits}f}}" for c in num}, na_rep="")
    for c in status_cols:
        if c in d:
            sty = sty.map(_status_css, subset=[c])
    st.dataframe(sty, hide_index=True, height=min(max_h, 38 + 35 * len(d)))


def show_matrix(M: pd.DataFrame, css_fn, first="Konstruk"):
    d = M.copy()
    d.index.name = first
    txt = d.apply(lambda col: col.map(lambda v: "" if pd.isna(v) else f"{v:.3f}"))
    css = pd.DataFrame([[("text-align:right;" + css_fn(i, j, d.iat[i, j])) for j in range(d.shape[1])]
                        for i in range(d.shape[0])], index=d.index, columns=d.columns)
    sty = txt.style.apply(lambda _: css, axis=None)
    st.dataframe(sty, height=min(620, 38 + 35 * len(d)))


# ---------------------------------------------------------------------
# Kepala & navigasi
# ---------------------------------------------------------------------
hc1, hc2 = st.columns([1.3, 3])
with hc1:
    st.markdown('<div class="brand">\U0001F537 SEM-PLS Studio <small>PLS-SEM tanpa coding</small></div>',
                unsafe_allow_html=True)
with hc2:
    page = st.radio("Navigasi", PAGES, horizontal=True, key="nav", label_visibility="collapsed")
st.divider()

model = model_from_editor(ss.model_json)

# =====================================================================
# HALAMAN 1: DATA
# =====================================================================
if page == PAGES[0]:
    left, right = st.columns([1, 2.7], gap="large")
    with left:
        st.subheader("Sumber data")
        st.radio("Sumber", ["file", "paste", "demo"], key="data_src", label_visibility="collapsed",
                 format_func={"file": "Unggah file (Excel / CSV / SPSS)", "paste": "Tempel dari Excel",
                              "demo": "Data contoh"}.get)
        if ss.data_src == "file":
            up = st.file_uploader("Pilih file", type=["xlsx", "xls", "xlsm", "csv", "txt", "tsv", "sav"])
            st.checkbox("Baris pertama berisi nama kolom", key="header")
            if up is not None:
                raw = up.getvalue()
                sheets = excel_sheets(raw, up.name)
                sheet = st.selectbox("Sheet", sheets) if len(sheets) > 1 else (sheets[0] if sheets else None)
                sig = (up.name, up.size, sheet, ss.header)
                if sig != ss.data_sig:
                    ss.data_sig = sig
                    try:
                        df, sep = read_uploaded(raw, up.name, sheet, ss.header)
                        set_data(df, {"type": "file", "name": up.name, "ext": up.name.rsplit(".", 1)[-1].lower(),
                                      "sheet": sheet}, sep)
                    except Exception as e:
                        ss.data_msg = ("error", f"File gagal dibaca: {e}")
            help_txt("Setiap baris = satu responden, setiap kolom = satu indikator (mis. IQ1, IQ2, ...).")
        elif ss.data_src == "paste":
            st.text_area("Tempel data", key="paste_txt", height=220, label_visibility="collapsed",
                         placeholder="1. Blok data di Excel, termasuk baris judul kolom\n2. Tekan Ctrl+C\n3. Klik di kotak ini, tekan Ctrl+V")
            if st.button("Pakai data ini", type="primary", width="stretch"):
                if not ss.paste_txt.strip():
                    ss.data_msg = ("warning", "Kotak tempel masih kosong.")
                else:
                    try:
                        df, sep = read_delim_auto(ss.paste_txt, True)
                        ss.data_sig = None
                        set_data(df, {"type": "paste"}, sep)
                    except Exception as e:
                        ss.data_msg = ("error", f"Teks gagal dibaca: {e}")
        else:
            help_txt("Data latihan untuk mencoba aplikasi.")
            if st.button("Kesuksesan Sistem Informasi (200 responden)", width="stretch"):
                load_demo("is")
            if st.button("Kepuasan pelanggan ECSI (250 responden)", width="stretch"):
                load_demo("mobi")
            st.checkbox("Sekaligus muat contoh model", key="demo_model")
        st.divider()
        st.selectbox("Jika ada sel kosong (missing)", ["mean", "listwise"], key="missing",
                     format_func={"mean": "Isi dengan rata-rata kolom", "listwise": "Hapus baris yang kosong (listwise)"}.get)

    with right:
        if ss.data_msg:
            kind, msg = ss.data_msg
            getattr(st, kind)(msg)
        p = ss.prep
        if p is None:
            st.info("**Belum ada data.** Pilih sumber data di panel kiri. Untuk mencoba cepat, pilih **Data contoh**.")
        else:
            nas = int(p["data"][p["vars"]].isna().sum().sum())
            ign = len(p["non_numeric"]) + len(p["constant"])
            st.markdown('<div class="statgrid">' + stat_card("Responden (baris)", p["n"]) +
                        stat_card("Indikator numerik", len(p["vars"]), tone="amber") +
                        stat_card("Sel kosong", nas, "ditangani saat estimasi" if nas else "data lengkap", "warn" if nas else "teal") +
                        stat_card("Kolom diabaikan", ign, "bukan angka / konstan" if ign else "tidak ada", "muted") +
                        "</div>", unsafe_allow_html=True)
            notes = []
            if p["non_numeric"]: notes.append("Kolom bukan angka (tidak bisa jadi indikator): **" + ", ".join(p["non_numeric"]) + "**")
            if p["constant"]: notes.append("Kolom bernilai konstan (varians 0): **" + ", ".join(p["constant"]) + "**")
            if p["renamed"]: notes.append("Nama kolom disesuaikan: " + "; ".join(f"{a} \u2192 {b}" for a, b in p["renamed"]))
            if notes:
                st.warning("\n".join(f"- {n}" for n in notes))
            t1, t2, t3 = st.tabs(["Pratinjau data", "Statistik deskriptif", "Sebaran jawaban"])
            with t1:
                st.dataframe(p["data"], height=380)
            with t2:
                show_df(describe_data(p["data"], p["vars"]))
                help_txt("Skewness dan kurtosis (excess) hanya informasi. PLS-SEM tidak mensyaratkan data berdistribusi normal.")
            with t3:
                sel = st.multiselect("Indikator yang ditampilkan", p["vars"], default=p["vars"][:8])
                if sel:
                    long = p["data"][sel].melt(var_name="Indikator", value_name="Skor").dropna()
                    discrete = np.allclose(long.Skor, long.Skor.round()) and long.Skor.nunique() <= 11
                    if discrete:
                        tab = long.groupby(["Indikator", "Skor"]).size().rename("n").reset_index()
                        tab["Persen"] = tab.n / tab.groupby("Indikator").n.transform("sum")
                        ch = alt.Chart(tab).mark_bar(color="#2f6fdb").encode(
                            x=alt.X("Skor:O", title="Skor jawaban"),
                            y=alt.Y("Persen:Q", axis=alt.Axis(format="%"), title="Responden"),
                            tooltip=["Indikator", "Skor", "n", alt.Tooltip("Persen:Q", format=".1%")])
                    else:
                        ch = alt.Chart(long).mark_bar(color="#2f6fdb").encode(
                            x=alt.X("Skor:Q", bin=alt.Bin(maxbins=20)), y=alt.Y("count()", title="Frekuensi"))
                    st.altair_chart(ch.properties(width=170, height=130).facet(
                        facet=alt.Facet("Indikator:N", sort=sel, title=None), columns=4))
            if st.button("Lanjut: gambar model \u2192", type="primary"):
                ss.goto = "model"; st.rerun()

# =====================================================================
# HALAMAN 2: MODEL
# =====================================================================
elif page == PAGES[1]:
    def apply_syntax():
        try:
            m = parse_syntax(ss.syntax, ss.prep["vars"] if ss.prep else [])
            load_model(model_for_editor(m))
            ss.syntax_msg = ("success", f"Model diterapkan: {len(m['constructs'])} konstruk, {len(m['paths'])} jalur. Buka tab Gambar model.")
        except Exception as e:
            ss.syntax_msg = ("error", str(e))

    def pull_syntax():
        ss.syntax = model_to_syntax(model_from_editor(ss.model_json))
        ss.syntax_msg = None

    def open_json():
        f = ss.get("model_file")
        if f is None:
            return
        try:
            j = json.loads(f.getvalue().decode("utf-8"))
            if "constructs" not in j:
                raise ValueError("bukan file model SEM-PLS Studio")
            load_model(j)
            ss.syntax_msg = ("success", "Model dibuka. Lihat tab Gambar model.")
        except Exception as e:
            ss.syntax_msg = ("error", f"File model tidak valid: {e}")

    left, right = st.columns([3.3, 1], gap="medium")
    with left:
        t_draw, t_syn, t_code, t_file = st.tabs(["\u270F\uFE0F Gambar model", "\u2328\uFE0F Tulis sintaks",
                                                 "\u2039/\u203A Kode R (seminr)", "\U0001F4BE Simpan / buka model"])
        with t_draw:
            overlay = None
            if ss.res is not None and ss.used_sig == model_signature(model):
                overlay = {"token": f"m{ss.res_token}", "data": ss.res["js"]}
            val = _editor(vars=ss.prep["vars"] if ss.prep else [], model=ss.model_json, rev=ss.model_rev,
                          results=overlay, label_mode=ss.diag_label, show_items=ss.diag_items,
                          readonly=False, height=680, key="editor", default=None)
            if isinstance(val, dict) and val.get("rev") == ss.model_rev and val.get("model") is not None \
                    and val["model"] != ss.model_json:
                ss.model_json = val["model"]
                model = model_from_editor(ss.model_json)
        with t_syn:
            if ss.syntax_msg:
                getattr(st, ss.syntax_msg[0])(ss.syntax_msg[1])
            c1, c2 = st.columns([1.4, 1])
            with c1:
                st.text_area("Sintaks model", key="syntax", height=360, label_visibility="collapsed",
                             placeholder="IQ  =~ IQ1 + IQ2 + IQ3 + IQ4\nSQ  =~ SQ1:SQ4\nUS  =~ US1 + US2 + US3\n\nUS ~ IQ + SQ")
                b1, b2 = st.columns(2)
                b1.button("Terapkan ke diagram", type="primary", on_click=apply_syntax, width="stretch")
                b2.button("Ambil dari diagram", on_click=pull_syntax, width="stretch")
            with c2:
                st.markdown("""
Satu pernyataan per baris; `#` untuk komentar.

| Penulisan | Arti |
|---|---|
| `IQ =~ IQ1 + IQ2` | konstruk reflektif |
| `SQ =~ SQ1:SQ4` | rentang kolom berurutan |
| `IMG <~ X1 + X2` | konstruk formatif |
| `US ~ IQ + SQ` | jalur IQ \u2192 US, SQ \u2192 US |
| `IQ -> US -> NB` | penulisan jalur alternatif |
""")
        with t_code:
            if not model["constructs"] or not model["paths"]:
                st.info("Gambar model terlebih dahulu; kode R akan muncul di sini.")
            else:
                code = gen_r_code(model, settings_now(), ss.src, ss.prep)
                st.download_button("Unduh .R", code, file_name="analisis_sempls.R", mime="text/plain")
                help_txt("Kode ini mereproduksi model dan pengaturan yang sama dengan paket seminr di R, cocok untuk lampiran skripsi/tesis.")
                st.code(code, language="r")
        with t_file:
            c1, c2 = st.columns(2)
            with c1:
                st.markdown("**Simpan model**")
                help_txt("Menyimpan diagram (konstruk, indikator, jalur, posisi) ke file .json agar bisa dibuka lagi.")
                st.download_button("Unduh model (.json)", json.dumps(ss.model_json, indent=2, ensure_ascii=False),
                                   file_name="model_sempls.json", mime="application/json")
            with c2:
                st.markdown("**Buka model**")
                st.file_uploader("Pilih .json", type=["json"], key="model_file", on_change=open_json)

    with right:
        st.markdown("**Pemeriksaan model**")
        checks, ok = validate_model(model, ss.prep)
        icon = {"ok": "\u2713", "warn": "!", "err": "\u2717"}
        st.markdown('<ul class="checklist">' + "".join(
            f'<li class="{lv}"><span class="ic">{icon[lv]}</span><span>{msg}</span></li>' for lv, msg in checks) + "</ul>",
            unsafe_allow_html=True)
        if ss.res is not None and ss.used_sig != model_signature(model):
            st.warning("Model berubah sejak estimasi terakhir. Jalankan ulang.")
        st.radio("Algoritma", ["pls", "plsc"], key="alg", format_func={
            "pls": "PLS-SEM standar (setara PLS Algorithm di SmartPLS)",
            "plsc": "PLSc (consistent PLS)"}.get)
        with st.expander("Pengaturan lanjutan"):
            st.selectbox("Skema pembobotan inner", ["path", "factorial"], key="inner",
                         format_func={"path": "Path weighting", "factorial": "Factorial"}.get)
            st.number_input("Maks. iterasi", 50, 5000, step=50, key="maxit")
            st.selectbox("Kriteria berhenti", [7, 5, 9], key="stop", format_func=lambda v: f"10^-{v}")
        run_pls = st.button("\u25B6 Jalankan PLS Algorithm", type="primary", width="stretch")
        st.divider()
        st.markdown("**Bootstrapping (uji hipotesis)**")
        st.selectbox("Jumlah subsampel", [500, 1000, 5000, 10000], key="nboot",
                     format_func=lambda v: {500: "500 (cepat)", 5000: "5000 (disarankan untuk publikasi)"}.get(v, str(v)))
        a1, a2 = st.columns(2)
        a1.selectbox("\u03b1", [0.01, 0.05, 0.10], key="alpha", format_func=lambda v: f"{v:.2f}".replace(".", ","))
        a2.selectbox("Uji", ["two", "one"], key="tail", format_func={"two": "Dua arah", "one": "Satu arah"}.get)
        st.number_input("Seed (agar hasil bisa diulang)", 1, 10**9, step=1, key="seed")
        run_boot = st.button("\u25B6 Jalankan Bootstrapping", width="stretch")
        help_txt("Bootstrapping ikut menjalankan PLS Algorithm, jadi tombol ini cukup diklik sekali.")

        if ss.run_errors:
            st.error("\n".join(f"- {e}" for e in ss.run_errors))
            ss.run_errors = None
        if run_pls or run_boot:
            if not ok:
                ss.run_errors = ["Model belum siap diestimasi:"] + [m_ for lv, m_ in checks if lv == "err"]
                st.rerun()
            s = settings_now()
            try:
                d, dropped = prepare_estimation_data(ss.prep, model, s["missing"])
                with st.spinner("Menjalankan PLS Algorithm..."):
                    r = estimate(d, to_spec(model), s["algorithm"], s["inner"], s["maxit"], s["stop"])
                warns = []
                if r.fit["iterations"] >= s["maxit"]:
                    warns.append(f"Algoritma PLS berhenti di batas {s['maxit']} iterasi (belum konvergen). Naikkan 'Maks. iterasi'.")
                boot = None
                if run_boot:
                    bar = st.progress(0.0, text=f"Bootstrapping {s['nboot']} subsampel...")
                    boot = bootstrap(r, s["nboot"], s["seed"],
                                     progress=lambda f: bar.progress(min(f, 1.0), text=f"Bootstrapping {s['nboot']} subsampel... {int(f * 100)}%"))
                    bar.empty()
                    if boot["dropped"]:
                        warns.append(f"{boot['dropped']} subsampel bootstrap tidak dapat diestimasi dan dikeluarkan.")
                res = compute_results(r, boot, s["alpha"], s["tail"], dropped)
            except Exception as e:
                ss.run_errors = [f"Estimasi gagal: {e}",
                                 "Periksa indikator yang nilainya hampir konstan, indikator yang identik, atau data kosong yang terlalu banyak."]
                st.rerun()
            ss.res, ss.plsres, ss.settings = res, r, s
            ss.used_sig, ss.used_json, ss.used_model = model_signature(model), ss.model_json, model
            ss.warnings, ss.pred, ss.xlsx = warns, None, None
            ss.res_token += 1
            ss.goto = "hasil"
            st.rerun()

# =====================================================================
# HALAMAN 3: HASIL
# =====================================================================
elif page == PAGES[2]:
    res, s = ss.res, ss.settings
    if res is None:
        st.info("**Belum ada hasil.** Buka **2 \u00b7 Model**, gambar model, lalu klik **Jalankan PLS Algorithm** atau **Jalankan Bootstrapping**.")
        st.stop()
    stale = ss.used_sig != model_signature(model)
    if stale:
        st.warning("**Model sudah berubah sejak estimasi terakhir.** Hasil di bawah ini masih untuk model sebelumnya; jalankan ulang estimasi.")
    for w in ss.warnings:
        st.warning(w)
    st.caption(" \u2022 ".join(filter(None, [
        "PLSc" if s["algorithm"] == "plsc" else "PLS-SEM standar",
        "factorial" if s["inner"] == "factorial" else "path weighting",
        f"n = {res['n_used']}" + (f" ({res['n_dropped']} baris dihapus)" if res["n_dropped"] else ""),
        f"{res['iterations']} iterasi",
        f"bootstrap {res['boot']['nboot']} subsampel" if res["has_boot"] else ""])))

    tabs = st.tabs(["Ringkasan", "Diagram", "Model pengukuran", "Validitas diskriminan", "Model struktural",
                    "Bootstrapping", "Fit & prediksi", "Unduh"])
    hyp_rename = {"Koefisien": "\u03b2", "SD_boot": "SD", "t_stat": "t-statistik", "p_value": "p-value",
                  "CI_bawah": "CI bawah", "CI_atas": "CI atas", "f2": "f\u00b2", "Efek_f2": "Efek f\u00b2"}

    def hyp_table():
        p = res["paths"]
        if res["has_boot"]:
            show_df(p[["Hipotesis", "Jalur", "Koefisien", "SD_boot", "t_stat", "p_value", "CI_bawah", "CI_atas", "Keputusan"]],
                    status_cols=["Keputusan"], p_cols=["p_value"], rename=hyp_rename)
        else:
            show_df(p[["Hipotesis", "Jalur", "Koefisien", "f2", "Efek_f2"]], rename=hyp_rename)

    with tabs[0]:
        R = res["reliab"][res["reliab"].Dinilai]
        n_ok = int(((R.alpha >= .7) & (R.rhoC >= .7) & (R.AVE >= .5)).sum())
        hm = res["htmt_max"]
        st.markdown('<div class="statgrid">' +
                    stat_card("Reliabilitas & AVE", f"{n_ok} / {len(R)}" if len(R) else "\u2014", "konstruk reflektif memenuhi",
                              "teal" if len(R) and n_ok == len(R) else "warn") +
                    stat_card("HTMT tertinggi", "\u2014" if np.isnan(hm) else fmt_id(hm), res["htmt_pair"],
                              "warn" if not np.isnan(hm) and hm >= .9 else "teal") +
                    stat_card("R\u00b2 tertinggi", fmt_id(res["r2"].R2.max()), res["r2"].Konstruk[res["r2"].R2.idxmax()]) +
                    stat_card("Hipotesis didukung",
                              f"{int(res['paths'].Signifikan.sum())} / {len(res['paths'])}" if res["has_boot"] else "\u2014",
                              (f"\u03b1 = {fmt_id(s['alpha'], 2)}, uji {'satu arah' if s['tail'] == 'one' else 'dua arah'}")
                              if res["has_boot"] else "jalankan bootstrapping", "teal" if res["has_boot"] else "muted") +
                    stat_card("SRMR", fmt_id(res["srmr"]), "< 0,08: fit baik" if res["srmr"] < .08 else "batas umum < 0,08",
                              "teal" if res["srmr"] < .08 else "warn") + "</div>", unsafe_allow_html=True)
        st.markdown("#### " + ("Tabel hipotesis" if res["has_boot"] else "Koefisien jalur"))
        hyp_table()
        st.markdown("#### Interpretasi otomatis")
        paras = build_narrative(res, s)
        st.markdown('<div class="narrative">' + "".join(f"<p>{x}</p>" for x in paras) + "</div>", unsafe_allow_html=True)
        with st.expander("Salin teks interpretasi"):
            st.code("\n\n".join(paras), language=None, wrap_lines=True)
        help_txt("Narasi disusun dari aturan baku (rule of thumb). Sesuaikan dengan teori, konteks penelitian, dan pedoman kampus/jurnal Anda.")

    with tabs[1]:
        c1, c2 = st.columns([2, 1])
        c1.radio("Label", ["coef", "coef_p", "t"], key="diag_label", horizontal=True, label_visibility="collapsed",
                 format_func={"coef": "Koefisien", "coef_p": "Koefisien (p-value)", "t": "t-statistik"}.get)
        c2.checkbox("Tampilkan nilai indikator", key="diag_items")
        _editor(results={"token": f"v{ss.res_token}", "model": ss.used_json, "data": res["js"]},
                label_mode=ss.diag_label, show_items=ss.diag_items, readonly=True, height=620, key="viewer", default=None)
        help_txt("Unduh gambar lewat tombol <b>Unduh PNG / Unduh SVG</b> di atas diagram. Pilihan p-value dan t-statistik aktif setelah bootstrapping. "
                 "Indikator reflektif menampilkan outer loading, indikator formatif menampilkan outer weight.")

    with tabs[2]:
        st.markdown("#### Outer loading")
        help_txt("Indikator reflektif idealnya \u2265 0,70. Nilai 0,40\u20130,70 dapat dipertahankan bila AVE dan composite reliability sudah memenuhi.")
        L = res["loadings"]
        show_df(L[L.Tipe != "Formatif"][["Konstruk", "Indikator", "Tipe", "Loading", "Status"]], status_cols=["Status"])
        if (L.Tipe == "Formatif").any():
            st.markdown("#### Outer weight (indikator formatif)")
            help_txt("Indikator formatif dinilai dari signifikansi weight (tab Bootstrapping), loading (\u2265 0,50 bila weight tidak signifikan), dan VIF < 3.")
            show_df(L[L.Tipe == "Formatif"][["Konstruk", "Indikator", "Weight", "Loading"]])
        st.markdown("#### Reliabilitas dan validitas konvergen")
        help_txt("Cronbach's alpha dan \u03c1C \u2265 0,70 (di atas 0,95 menandakan item redundan); AVE \u2265 0,50.")
        show_df(res["reliab"][["Konstruk", "alpha", "rhoA", "rhoC", "AVE", "Reliabilitas", "Validitas_konvergen", "Keterangan"]],
                status_cols=["Reliabilitas", "Validitas_konvergen"],
                rename={"alpha": "Cronbach's \u03b1", "rhoA": "\u03c1A", "rhoC": "\u03c1C (CR)", "Validitas_konvergen": "Validitas konvergen"})
        st.markdown("#### Kolinearitas indikator (VIF)")
        help_txt("Terutama penting untuk indikator formatif: VIF idealnya < 3, maksimal < 5.")
        show_df(res["vif_items"], status_cols=["Status"])

    with tabs[3]:
        st.markdown("#### Heterotrait-Monotrait ratio (HTMT)")
        help_txt("Terpenuhi bila HTMT < 0,90 (atau < 0,85). Sel kuning \u2265 0,85, sel merah \u2265 0,90.")
        show_matrix(res["htmt"], lambda i, j, v: "" if pd.isna(v) else (
            "background-color:#fbe4e2;color:#8d2a24;font-weight:600" if v >= .9 else "background-color:#fff3cf" if v >= .85 else ""))
        if not np.isnan(hm):
            if hm < .9:
                st.success(f"HTMT tertinggi {fmt_id(hm)} ({res['htmt_pair']}) < 0,90: validitas diskriminan terpenuhi.")
            else:
                st.warning(f"HTMT tertinggi {fmt_id(hm)} ({res['htmt_pair']}) \u2265 0,90: perlu dicermati.")
        st.markdown("#### Kriteria Fornell-Larcker")
        help_txt("Diagonal (diarsir) = akar AVE; harus lebih besar daripada korelasi konstruk tersebut dengan konstruk lain.")
        show_matrix(res["fl"], lambda i, j, v: "background-color:#dce8fb;font-weight:700" if i == j else "")
        bad = [k for k, v in res["fl_ok"].items() if v is False]
        if bad:
            st.warning(f"Kriteria Fornell-Larcker belum terpenuhi untuk: **{', '.join(bad)}**.")
        else:
            st.success("Kriteria Fornell-Larcker terpenuhi untuk semua konstruk reflektif.")
        st.markdown("#### Cross loading")
        help_txt("Setiap indikator harus memiliki loading tertinggi pada konstruknya sendiri (sel diarsir).")
        CL, own = res["cross"], res["cross_own"]
        show_matrix(CL, lambda i, j, v: "background-color:#dce8fb;font-weight:700" if CL.columns[j] == own[i] else "", "Indikator")
        badc = [k for k, v in res["cross_ok"].items() if v is False]
        if badc:
            st.warning(f"Indikator dengan loading lebih tinggi di konstruk lain: **{', '.join(badc)}**.")
        else:
            st.success("Semua indikator memiliki loading tertinggi pada konstruknya sendiri.")

    with tabs[4]:
        st.markdown("#### Koefisien jalur dan effect size (f\u00b2)")
        help_txt("f\u00b2: 0,02 kecil; 0,15 sedang; 0,35 besar.")
        show_df(res["paths"][["Hipotesis", "Jalur", "Koefisien", "f2", "Efek_f2"]], rename=hyp_rename)
        st.markdown("#### Koefisien determinasi (R\u00b2)")
        help_txt("0,75 substansial; 0,50 moderat; 0,25 lemah.")
        show_df(res["r2"], rename={"R2": "R\u00b2", "R2_adj": "R\u00b2 adjusted"})
        st.markdown("#### Kolinearitas antarkonstruk (VIF inner)")
        show_df(res["vif_inner"], status_cols=["Status"])
        st.markdown("#### Efek total")
        show_df(res["total"])
        st.markdown("#### Efek tidak langsung total")
        if res["has_boot"] and res["boot"]["total_indirect"] is not None:
            show_df(res["boot"]["total_indirect"][["Dari", "Ke", "Original", "SD_boot", "t_stat", "p_value", "CI_bawah", "CI_atas"]],
                    p_cols=["p_value"], rename={"Original": "Efek", **hyp_rename})
        else:
            show_df(res["total_ind"])

    boot_rename = {"Original": "Estimasi", "Rata_boot": "Rata-rata", "SD_boot": "SD", "t_stat": "t-statistik",
                   "p_value": "p-value", "CI_bawah": "CI bawah", "CI_atas": "CI atas"}
    with tabs[5]:
        if not res["has_boot"]:
            st.warning("**Bootstrapping belum dijalankan.** Kembali ke **2 \u00b7 Model** lalu klik **Jalankan Bootstrapping**.")
        else:
            b = res["boot"]
            ci = 100 * (1 - (2 * b["alpha"] if b["tail"] == "one" else b["alpha"]))
            st.success(f"Bootstrapping {b['nboot']} subsampel" + (f" ({b['dropped']} dikeluarkan)" if b["dropped"] else "") +
                       f"; uji {'satu arah' if b['tail'] == 'one' else 'dua arah'}; \u03b1 = {fmt_id(b['alpha'], 2)}; interval kepercayaan persentil {ci:.0f}%.")
            st.markdown("#### Uji hipotesis (koefisien jalur)")
            hyp_table()
            st.markdown("#### Efek tidak langsung spesifik (mediasi)")
            help_txt("Klasifikasi mediasi mengikuti Zhao, Lynch & Chen (2010) sebagaimana dipakai Hair dkk.")
            ind = b["indirect"]
            if ind is None or not len(ind):
                st.caption("Tidak ada jalur mediasi dalam model ini.")
            else:
                ind = ind.assign(Kesimpulan=np.where(ind.Signifikan, "\u2713 ", "\u2717 ") + ind.Mediasi)
                show_df(ind[["Jalur", "Original", "SD_boot", "t_stat", "p_value", "CI_bawah", "CI_atas", "Kesimpulan"]],
                        status_cols=["Kesimpulan"], p_cols=["p_value"], rename=boot_rename)
            st.markdown("#### Signifikansi outer loading")
            show_df(b["loadings"], p_cols=["p_value"], rename=boot_rename)
            if any(res["formative"].values()):
                st.markdown("#### Signifikansi outer weight (indikator formatif)")
                form = [k for k, v in res["formative"].items() if v]
                show_df(b["weights"][b["weights"].Konstruk.isin(form)], p_cols=["p_value"], rename=boot_rename)
            st.markdown("#### Interval kepercayaan HTMT")
            help_txt("Validitas diskriminan didukung bila batas atas interval < 1 (lebih ketat: < 0,90).")
            bh = b["htmt"].assign(Status=np.where(b["htmt"].CI_atas < .9, "\u2713 Memenuhi",
                                                  np.where(b["htmt"].CI_atas < 1, "\u26a0 < 1 (longgar)", "\u2717 Tidak memenuhi")))
            show_df(bh[["Konstruk 1", "Konstruk 2", "Original", "Rata_boot", "CI_bawah", "CI_atas", "Status"]],
                    status_cols=["Status"], rename=boot_rename)

    with tabs[6]:
        st.markdown('<div class="statgrid">' +
                    stat_card("SRMR (model jenuh)", fmt_id(res["srmr"]), "< 0,08: fit baik" if res["srmr"] < .08 else "\u2265 0,08: fit kurang",
                              "teal" if res["srmr"] < .08 else "warn") +
                    stat_card("Rata-rata R\u00b2", fmt_id(res["r2"].R2.mean()), f"{len(res['r2'])} konstruk endogen") + "</div>",
                    unsafe_allow_html=True)
        st.markdown("#### PLSpredict (relevansi prediktif)")
        help_txt("Membandingkan prediksi out-of-sample model PLS dengan regresi linear (LM) untuk indikator konstruk endogen. "
                 "Q\u00b2predict > 0 berarti model lebih baik dari prediksi rata-rata.")
        c1, c2, c3 = st.columns([1, 1, 2])
        c1.number_input("Jumlah fold", 2, 20, key="pred_folds")
        c2.number_input("Pengulangan", 1, 20, key="pred_reps")
        if c3.button("\u25B6 Jalankan PLSpredict"):
            with st.spinner("Menjalankan PLSpredict..."):
                try:
                    ss.pred = plspredict(ss.plsres, int(ss.pred_folds), int(ss.pred_reps), int(s["seed"]))
                    ss.xlsx = None
                except Exception as e:
                    st.error(f"PLSpredict gagal: {e}")
        pr = ss.pred
        if pr is not None:
            k, n = int((pr.RMSE_PLS < pr.RMSE_LM).sum()), len(pr)
            lvl = ("tinggi (semua indikator: RMSE PLS < LM)" if k == n else "sedang (mayoritas indikator: RMSE PLS < LM)" if k > n / 2
                   else "rendah (minoritas indikator: RMSE PLS < LM)" if k > 0 else "tidak ada (RMSE PLS tidak lebih kecil dari LM)")
            msg = f"Q\u00b2predict > 0 pada {int((pr.Q2_predict > 0).sum())} dari {n} indikator. Kekuatan prediktif model: {lvl}."
            if k > n / 2:
                st.success(msg)
            else:
                st.warning(msg)
            show_df(pr, rename={"Q2_predict": "Q\u00b2predict", "RMSE_PLS": "RMSE PLS", "RMSE_LM": "RMSE LM",
                                "MAE_PLS": "MAE PLS", "MAE_LM": "MAE LM", "PLS_lebih_baik": "RMSE PLS < LM"})
        st.markdown("#### Kriteria informasi (AIC/BIC)")
        help_txt("Berguna untuk membandingkan beberapa model alternatif: nilai lebih kecil lebih baik.")
        show_matrix(res["it_criteria"], lambda i, j, v: "", "Kriteria")

    with tabs[7]:
        if ss.xlsx is None:
            ss.xlsx = excel_report(res, s, ss.pred)
        c1, c2 = st.columns(2)
        with c1:
            st.markdown("**\U0001F4CA Laporan Excel**")
            help_txt("Semua tabel hasil dalam satu file, satu sheet per tabel.")
            st.download_button("Unduh .xlsx", ss.xlsx, file_name="hasil_sempls.xlsx", type="primary",
                               mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
            st.markdown("**\U0001F4C8 Skor konstruk**")
            help_txt("Skor variabel laten per responden (terstandar).")
            st.download_button("Unduh .csv", res["scores"].to_csv(index=False).encode("utf-8"), file_name="skor_konstruk.csv", mime="text/csv")
        with c2:
            st.markdown("**\u2039/\u203A Skrip R (seminr)**")
            help_txt("Kode untuk mereproduksi analisis ini di RStudio.")
            st.download_button("Unduh .R", gen_r_code(ss.used_model, s, ss.src, ss.prep), file_name="analisis_sempls.R", mime="text/plain")
            st.markdown("**\U0001F5BC Diagram**")
            help_txt("Buka tab <b>Diagram</b>, lalu klik <b>Unduh PNG</b> atau <b>Unduh SVG</b> di atas diagram.")

# =====================================================================
# PANDUAN
# =====================================================================
else:
    st.markdown("""
### Alur kerja
1. **Data** \u2014 unggah Excel/CSV/SPSS, tempel langsung dari Excel, atau pakai data contoh. Kolom bukan angka otomatis diabaikan.
2. **Model** \u2014 seret indikator (kotak kuning) dari panel kiri ke kanvas. **Kelompokkan otomatis** membuat konstruk dari awalan nama kolom (IQ1, IQ2 \u2192 IQ).
   Dobel-klik konstruk untuk ganti nama; arahkan kursor ke konstruk lalu tarik titik **+** di tepi kanannya ke konstruk tujuan untuk membuat jalur.
3. **Estimasi** \u2014 klik **Jalankan PLS Algorithm** untuk koefisien, atau **Jalankan Bootstrapping** untuk sekaligus mendapatkan t-statistik dan p-value.
4. **Hasil** \u2014 ringkasan berisi tabel hipotesis dan narasi interpretasi otomatis. Semua tabel bisa disalin atau diunduh; diagram bisa diunduh PNG/SVG.

### Pintasan di kanvas
| Aksi | Hasil |
|---|---|
| Seret indikator ke area kosong / ke konstruk / kembali ke panel kiri | konstruk baru / masuk ke konstruk / dilepas dari model |
| Dobel-klik area kosong / konstruk | konstruk baru / ganti nama |
| Klik konstruk | panel properti: nama, reflektif/formatif, posisi indikator |
| Delete, Ctrl+Z, Ctrl+Y | hapus, urungkan, ulangi |
| Gulir mouse, seret area kosong | zoom, geser kanvas |

### Kriteria evaluasi
| Aspek | Ukuran | Batas |
|---|---|---|
| Reliabilitas indikator | Outer loading | \u2265 0,70 |
| Konsistensi internal | Cronbach's \u03b1, \u03c1A, \u03c1C | 0,70\u20130,95 |
| Validitas konvergen | AVE | \u2265 0,50 |
| Validitas diskriminan | HTMT | < 0,90 (atau < 0,85) |
| Kolinearitas | VIF | < 3 ideal, < 5 dapat diterima |
| Daya jelas | R\u00b2 | 0,75 / 0,50 / 0,25 |
| Effect size | f\u00b2 | 0,02 / 0,15 / 0,35 |
| Signifikansi jalur | Bootstrapping | p < \u03b1 |
| Kecocokan model | SRMR | < 0,08 |
| Relevansi prediktif | Q\u00b2predict | > 0 |

### Catatan metode
- Mesin perhitungan ditulis ulang dalam Python mengikuti algoritma paket R **seminr**; koefisien, loading, reliabilitas, HTMT, f\u00b2, VIF, dan SRMR identik dengan seminr.
- **PLS-SEM standar** = komposit mode A (reflektif) / mode B (formatif), setara *PLS Algorithm* di SmartPLS. **PLSc** mengoreksi konstruk reflektif dengan \u03c1A.
- p-value dari t-statistik bootstrap dengan derajat bebas (subsampel \u2212 1); uji satu arah = p dua arah / 2. Interval kepercayaan memakai metode persentil.
- Hasil bootstrap dan PLSpredict bergantung pada pengacakan, sehingga sedikit berbeda dari program lain.
""")
