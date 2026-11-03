import { originLabel, type ResearchCalendar } from './ResearchDatePicker';
const day = (value?: string) => value ? new Date(`${value}T12:00:00+07:00`).toLocaleDateString('id-ID', { day: 'numeric', month: 'long', year: 'numeric', timeZone: 'Asia/Jakarta' }) : 'Belum tersedia';
const range = (start?: string, end?: string) => `${day(start)} – ${day(end)}`;
const explanations: Record<string, string> = {
  training_replay: 'Model sudah mempelajari data tanggal ini. Hasil merupakan simulasi, bukan skor validation atau test.',
  validation: 'Prediksi berasal dari fold evaluasi yang tersimpan. Tanggal ini tidak digunakan untuk melatih model pada fold tersebut; dapat menjadi data latih pada fold berikutnya.',
  test: 'Tanggal ini tidak digunakan untuk melatih atau memilih model yang diuji. Prediksi berasal dari model development yang dibekukan.',
  inference: 'Prediksi tersedia; hasil aktual lima hari perdagangan berikutnya belum tersedia dalam dataset.',
  purge_gap: 'Tanggal ini berada pada jeda pemisahan data. Hasil merupakan simulasi dan tidak dimasukkan ke skor validation atau test.',
  data_only: 'Data mentah tersedia, tetapi fitur model belum lengkap. Kelas prediksi dan status EWS tidak diisi.',
};
const featureNames: Record<string, string> = { bi_rate_change: 'BI-Rate Change', inflation_change_release: 'Inflation Change antarrilis', ihsg_return_1d: 'Return IHSG 1D', ihsg_return_5d: 'Return IHSG 5D', ma_5: 'MA 5D', ma_20: 'MA 20D', ma_ratio: 'MA Ratio', volatility_5d: 'Volatilitas 5D', volatility_20d: 'Volatilitas 20D', rsi_14: 'RSI 14', volume_change: 'Volume Change', foreign_net_5d: 'Foreign Net Flow 5D', usdidr_return: 'Return USD/IDR', brent_return: 'Return Brent', us10y_change: 'US10Y Change' };
export function ResearchContext({ calendar, meta, prediction, model }: { calendar: ResearchCalendar; meta: Record<string, any>; prediction: Record<string, any>; model: string }) {
  const entry = meta.models[model];
  const fold = prediction.origin === 'validation' ? calendar.validation_folds?.find(f => prediction.data_date >= f.validation.start_date && prediction.data_date <= f.validation.end_date) : undefined;
  return <section className="research-context" aria-label="Informasi penggunaan data penelitian">
    <h2>Penggunaan data · {model === 'xgboost' ? 'XGBoost' : 'LightGBM'}</h2>
    <dl className="research-periods">
      <div><dt>Seluruh dataset</dt><dd>{range(meta.date_start, meta.date_end)}</dd><small>Data yang dikumpulkan; tidak seluruhnya digunakan untuk fit model.</small></div>
      <div><dt>Pelatihan model development</dt><dd>{range(entry.training_start, entry.training_end)}</dd><small>Model tersimpan untuk simulasi dan final test; pelatihan fold validation berbeda.</small></div>
      <div><dt>Evaluasi validation · 5 fold</dt><dd>{range(meta.validation_start, meta.validation_end)}</dd><small>Prediksi dari lima model fold dengan pelatihan yang bertambah.</small></div>
      <div><dt>Evaluasi final test</dt><dd>{range(meta.final_test?.start_date, meta.final_test?.end_date)}</dd><small>Satu blok pengujian terpisah; model dan threshold tetap.</small></div>
    </dl>
    <div className="research-selected"><strong>Tanggal yang sedang ditampilkan: {day(prediction.data_date)}</strong><span>{originLabel(prediction.origin)}</span>
      <p>{explanations[prediction.origin] || prediction.usage_notice}</p>
      {fold && <p><b>Fold {fold.fold}:</b> pelatihan {range(fold.train.start_date, fold.train.end_date)}; evaluasi {range(fold.validation.start_date, fold.validation.end_date)}.</p>}
      {prediction.origin === 'validation' && !fold && <p>Rincian periode pelatihan fold belum tersedia. Muat ulang layanan untuk membaca metadata fold.</p>}
      <p><b>Ketersediaan prediksi:</b> {prediction.prediction_available === false ? 'Belum tersedia' : 'Tersedia'}{prediction.missing_features?.length > 0 && ` · Fitur yang belum tersedia: ${prediction.missing_features.map((f: string) => featureNames[f] || f).join(', ')}.`}</p>
    </div>
  </section>;
}
