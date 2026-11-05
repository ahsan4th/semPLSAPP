# SEM-PLS Studio (versi Streamlit)

Aplikasi web untuk analisis PLS-SEM tanpa coding. Model digambar di kanvas seperti SmartPLS
(seret indikator, tarik jalur antar konstruk), lalu klik Jalankan.

Mesin perhitungan (`pls_engine.py`) ditulis dalam Python mengikuti algoritma paket R **seminr**.
Koefisien jalur, loading, weight, R², alpha, rhoA, rhoC, AVE, HTMT, Fornell-Larcker, cross loading,
f², VIF, AIC/BIC, dan SRMR sudah dicocokkan dengan seminr 2.6 (selisih < 1e-12) untuk PLS standar
maupun PLSc, termasuk model dengan konstruk formatif dan item tunggal.

## Menjalankan di komputer sendiri

```bash
pip install -r requirements.txt
streamlit run app.py
```

Browser akan terbuka di http://localhost:8501. Dibutuhkan Python 3.9 atau lebih baru.

## Deploy ke Streamlit Community Cloud (gratis)

1. Unggah seluruh isi folder ini ke repositori GitHub (termasuk folder `components`, `data`, dan `.streamlit`).
2. Buka https://share.streamlit.io, klik **Create app**, pilih repositori tersebut, dan isi *Main file path*: `app.py`.
3. Klik **Deploy**. Paket di `requirements.txt` dipasang otomatis.

## Alur kerja

1. **Data**: unggah xlsx/xls/csv/txt/sav, tempel dari Excel, atau pakai data contoh.
2. **Model**: gambar di tab *Gambar model* (atau tulis di tab *Tulis sintaks*), lalu jalankan PLS Algorithm atau Bootstrapping.
3. **Hasil**: ringkasan + tabel hipotesis + narasi otomatis, diagram hasil, model pengukuran,
   validitas diskriminan, model struktural, bootstrapping (mediasi), SRMR, PLSpredict, unduhan Excel/R/CSV.

Contoh sintaks:

```
IQ  =~ IQ1 + IQ2 + IQ3 + IQ4     # reflektif
SQ  =~ SQ1:SQ4                   # rentang kolom
IMG <~ X1 + X2 + X3              # formatif
US  ~ IQ + SQ                    # jalur struktural
```

## Catatan

- Bootstrapping dan PLSpredict memakai pengacakan, jadi angkanya sedikit berbeda dari seminr/SmartPLS
  walau kesimpulannya sama. p-value dari t-statistik (df = subsampel - 1); interval kepercayaan persentil.
- PLSpredict memakai pendekatan *direct antecedent*; benchmark LM memakai indikator konstruk anteseden.
- Data contoh ECSI (`data/demo_mobi.csv`) berasal dari dataset `mobi` di paket R seminr.

## Isi folder

```
app.py                         antarmuka Streamlit
pls_engine.py                  mesin PLS-SEM (numpy/scipy)
sempls_utils.py                data, sintaks, validasi, tabel hasil, narasi, kode R, laporan Excel
components/pls_editor/         kanvas gambar model (komponen Streamlit, HTML/JS tanpa build)
data/                          data contoh
.streamlit/config.toml         tema dan pengaturan
requirements.txt
```
