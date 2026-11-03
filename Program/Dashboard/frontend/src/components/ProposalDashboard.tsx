import { useEffect, useState } from 'react';
import { AlignLeft, CalendarDays, CircleCheck, Info, Menu, Star, TrendingDown, TrendingUp, TriangleAlert } from 'lucide-react';
import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { originLabel, type ResearchCalendar } from './ResearchDatePicker';

type Data = Record<string, any>;
const format = (value: number | null | undefined, digits = 2) => value === null || value === undefined || !Number.isFinite(value) ? '—' : value.toLocaleString('en-US', { minimumFractionDigits: digits, maximumFractionDigits: digits });
const signed = (value: number | null | undefined, digits = 2) => value === null || value === undefined ? '—' : `${value > 0 ? '+' : ''}${format(value, digits)}`;
const date = (value: string, short = false) => new Date(`${value}T12:00:00+07:00`).toLocaleDateString('en-GB', { timeZone: 'Asia/Jakarta', day: 'numeric', month: short ? 'short' : 'long', ...(short ? {} : { year: 'numeric' }) });
const liveTime = (value?: string | null) => value ? new Date(value).toLocaleString('id-ID', { timeZone: 'Asia/Jakarta', day: 'numeric', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit', second: '2-digit' }) + ' WIB' : 'Menunggu sumber';
const modelName = (name: string) => name === 'xgboost' ? 'XGBoost' : 'LightGBM';
const regimeColor = (name: string) => ['Bearish', 'Warning'].includes(name) ? '#f01820' : ['Bullish', 'Stable'].includes(name) ? '#299942' : '#d89112';

export function ProposalHeader({ calendar, selectedDate, onDate, openMenu, error, mode, onMode, liveAsOf }: {
  calendar: ResearchCalendar | null; selectedDate: string | null; onDate: (value: string) => void;
  openMenu: () => void; error: string; mode: 'live' | 'research'; onMode: (mode: 'live' | 'research') => void;
  liveAsOf?: string | null;
}) {
  const [draft, setDraft] = useState('');
  const [message, setMessage] = useState('');
  const available = calendar?.items || [];
  useEffect(() => { setDraft(selectedDate || calendar?.default_date || ''); setMessage(''); }, [selectedDate, calendar]);
  const choose = (value: string, validate = false) => {
    setDraft(value);
    if (available.some(item => item.date === value)) { setMessage(''); onDate(value); }
    else if (validate && value) setMessage(`${date(value)} tidak tersedia dalam dataset. Tampilan tetap menggunakan ${selectedDate || calendar?.default_date ? date(selectedDate || calendar!.default_date) : 'tanggal sebelumnya'}.`);
    else setMessage('');
  };
  return <header className="proposal-header">
    <div className="proposal-title-row"><button className="proposal-mobile-menu" aria-label="Buka navigasi" onClick={openMenu}><Menu size={21} /></button><div><h1>Early Warning System Market Regime IHSG</h1><p>Market Regime Dashboard</p></div>
      <div className="proposal-asof"><span>{mode === 'live' ? 'IHSG source timestamp' : 'Data as of'}</span><strong>{mode === 'live' ? liveTime(liveAsOf) : selectedDate ? date(selectedDate) : '—'}</strong><small>{mode === 'live' ? 'Harga terakhir yang diberikan sumber' : 'After market close · historical'}</small></div>
      <div className="proposal-data-state"><strong><i />{mode === 'live' ? 'Live · Delayed' : 'Historical Data'}</strong><span>{mode === 'live' ? 'Auto refresh · 60s' : 'Research dataset'}</span></div>
    </div>
    <div className="proposal-date-row"><div className="proposal-view-tabs" role="tablist" aria-label="Mode dashboard"><button role="tab" aria-selected={mode === 'research'} onClick={() => onMode('research')}>Penelitian</button><button role="tab" aria-selected={mode === 'live'} onClick={() => onMode('live')}>Live</button></div>{mode === 'research' ? <><label><CalendarDays size={15} /><span>Tanggal penelitian</span><input type="date" name="training_date" aria-label="Tanggal penelitian" value={draft} min={available[0]?.date} max={available.at(-1)?.date} disabled={!calendar} onInput={e => choose(e.currentTarget.value, true)} onChange={e => choose(e.currentTarget.value, true)} onBlur={e => choose(e.currentTarget.value, true)} aria-describedby="proposal-date-help" /></label><span id="proposal-date-help">{calendar ? `Dataset: ${date(calendar.date_start)} – ${date(calendar.date_end)}` : 'Memuat tanggal dataset…'}</span></> : <span>IHSG dan quote indikator terbaru. Setiap sumber memiliki timestamp sendiri.</span>}</div>
    {mode === 'research' && (message || error) && <p className="proposal-date-error" role="alert">{message || error}</p>}
  </header>;
}

function IndicatorSpark({ rows, field, color }: { rows: Data[]; field: string; color: string }) {
  return <div className="proposal-spark" aria-hidden="true"><ResponsiveContainer width="100%" height="100%"><LineChart data={rows.slice(-12)}><YAxis hide domain={['dataMin', 'dataMax']} /><Line type="linear" dataKey={field} stroke={color} strokeWidth={1.4} dot={{ r: 1.8, strokeWidth: 0, fill: color }} isAnimationActive={false} connectNulls={false} /></LineChart></ResponsiveContainer></div>;
}

export function ProposalDashboard({ prediction: p, meta, rows, period, onPeriod, onModel, loading, error }: {
  prediction: Data; meta: Data; rows: Data[]; period: string; onPeriod: (period: string) => void;
  onModel: (model: string) => void; loading: boolean; error: string;
}) {
  const CurrentIcon = p.current_regime === 'Sideways' ? AlignLeft : p.current_regime === 'Bullish' ? TrendingUp : TrendingDown;
  const FutureIcon = p.predicted_future_regime === 'Sideways' ? AlignLeft : p.predicted_future_regime === 'Bullish' ? TrendingUp : TrendingDown;
  const StatusIcon = p.ews_status === 'Stable' ? CircleCheck : TriangleAlert;
  const oneDay = p.feature_values.ihsg_return_1d;
  const closeChange = p.market.Close - p.market.Close / (1 + oneDay);
  const previous = !loading ? rows.at(-2) : null;
  const indicators = [
    { key: 'Foreign', title: 'FOREIGN NET FLOW (IDR)', color: p.market.Foreign < 0 ? '#ef1823' : '#2c9e48', digits: 2, divisor: 1000, suffix: ' T' },
    { key: 'USD_IDR', title: 'USD/IDR', color: '#2461ac', digits: 0, divisor: 1, suffix: '' },
    { key: 'Brent', title: 'BRENT OIL (USD/BBL)', color: '#249643', digits: 2, divisor: 1, suffix: '' },
    { key: 'US10Y', title: 'US TREASURY YIELD 10Y (%)', color: '#2461ac', digits: 2, divisor: 1, suffix: '' },
  ];
  return <div className="proposal-dashboard">
    <div className={`proposal-provenance ${['training_replay', 'purge_gap'].includes(p.origin) ? 'simulation' : ''}`}><Info size={13} /><span>{p.origin === 'training_replay' ? 'Simulasi data latih: model telah melihat data ini. Hasil bukan evaluasi out-of-sample.' : p.origin === 'validation' ? 'Validation out-of-fold: hasil model pada fold evaluasi yang tersimpan.' : p.origin === 'test' ? 'Final test: model development beku; tanggal ini tidak digunakan untuk melatih atau memilih model.' : p.origin === 'purge_gap' ? 'Simulasi jeda purge: tidak digunakan untuk skor validation atau test.' : 'Inferensi pada ujung dataset: hasil aktual lima hari ke depan belum tersedia.'}</span><b>{modelName(p.model_name)} · {originLabel(p.origin)}</b></div>
    <div className="proposal-summary">
      <section className="proposal-card proposal-stat"><h2>CURRENT MARKET REGIME</h2><strong className="proposal-regime">{p.current_regime}</strong><CurrentIcon className="proposal-stat-icon current" size={37} strokeWidth={1.6} /><p>Condition: {p.current_regime === 'Sideways' ? 'Neutral' : p.current_regime === 'Bullish' ? 'Positive' : 'Negative'}</p></section>
      <section className="proposal-card proposal-stat"><h2>PREDICTED FUTURE REGIME <span>(5 TRADING DAYS)</span></h2><strong className="proposal-regime" style={{ color: regimeColor(p.predicted_future_regime) }}>{p.predicted_future_regime}</strong><FutureIcon className="proposal-stat-icon" style={{ color: regimeColor(p.predicted_future_regime) }} size={37} strokeWidth={1.7} /><p>Trend Probability: {format(p.class_probabilities[p.predicted_future_regime] * 100, 1)}%</p></section>
      <section className="proposal-card proposal-stat"><h2>EARLY WARNING STATUS</h2><strong className="proposal-regime" style={{ color: regimeColor(p.ews_status) }}>{p.ews_status}</strong><StatusIcon className="proposal-stat-icon" style={{ color: regimeColor(p.ews_status) }} size={32} strokeWidth={1.7} /><p>{p.ews_status === 'Warning' ? 'Signal: Future regime Bearish' : p.ews_status === 'Caution' ? 'Signal: Bullish → Sideways' : 'Baca bersama kondisi pasar saat ini'}</p></section>
      <section className="proposal-card proposal-stat proposal-close"><h2>LATEST IHSG CLOSE</h2><strong>{format(p.market.Close)}</strong><div style={{ color: oneDay < 0 ? '#ed1924' : '#269a43' }}>{signed(closeChange)} ({signed(oneDay * 100)}%)</div><p>vs Previous Close</p></section>
    </div>
    <div className="proposal-main-grid">
      <section className="proposal-card proposal-trend"><div className="proposal-panel-title"><h2>IHSG INDEX — {({ '1M': '1 MONTH', '3M': '3 MONTH', '6M': '6 MONTH', '1Y': '1 YEAR', YTD: 'YEAR TO DATE' } as Record<string, string>)[period]} TREND</h2><div className="proposal-ranges" aria-label="Rentang grafik">{['1M', '3M', '6M', '1Y', 'YTD'].map(value => <button key={value} aria-pressed={period === value} onClick={() => onPeriod(value)}>{value}</button>)}</div></div>
        {error ? <div className="proposal-chart-message" role="alert">{error}</div> : loading ? <div className="proposal-chart-message">Memuat grafik…</div> : <div className="proposal-price-chart" role="img" aria-label={`Grafik IHSG, ${rows.length} hari perdagangan`}><ResponsiveContainer width="100%" height="100%"><LineChart data={rows} margin={{ top: 12, right: 13, left: -3, bottom: 8 }}><CartesianGrid vertical={false} strokeDasharray="3 4" stroke="#e8e8e8" /><XAxis dataKey="Date" tickFormatter={v => date(v, true)} axisLine={false} tickLine={false} minTickGap={28} tick={{ fontSize: 10, fill: '#525252' }} dy={5} /><YAxis domain={['auto', 'auto']} tickFormatter={v => format(v, 0)} axisLine={false} tickLine={false} width={58} tick={{ fontSize: 10, fill: '#525252' }} /><Tooltip labelFormatter={v => date(String(v))} formatter={(v: any) => [format(Number(v)), 'IHSG']} contentStyle={{ border: '1px solid #e5e5e5', borderRadius: 5, fontSize: 12 }} /><Line dataKey="Close" type="linear" stroke="#ff2028" strokeWidth={1.65} dot={false} isAnimationActive={false} connectNulls={false} /></LineChart></ResponsiveContainer></div>}
      </section>
      <ProposalModelComparison meta={meta} selectedModel={p.model_name} onModel={onModel} />
      <ProposalStatusGuide />
      <div className="proposal-indicators">{indicators.map(indicator => {
        const raw = p.market[indicator.key];
        const prev = previous?.[indicator.key];
        const delta = prev !== null && prev !== undefined ? raw - prev : null;
        const relative = prev && delta !== null ? delta / prev * 100 : null;
        return <section className="proposal-card proposal-indicator" key={indicator.key}><h2>{indicator.title}</h2><div className="proposal-indicator-main"><div><strong style={{ color: indicator.color }}>{indicator.key === 'Foreign' ? signed(raw / indicator.divisor, indicator.digits) : format(raw / indicator.divisor, indicator.digits)}{indicator.suffix}</strong><span>vs Previous Day</span><p style={{ color: delta === null ? '#777' : delta < 0 ? '#e92b32' : '#279d46' }}>{indicator.key === 'Foreign' ? `${signed(delta === null ? null : delta / 1000)} T` : indicator.key === 'US10Y' ? `${signed(delta)} pp` : `${signed(delta)} (${signed(relative)}%)`}</p></div><IndicatorSpark rows={!loading ? rows : []} field={indicator.key} color={indicator.color} /></div><p className="proposal-indicator-date">As of {date(p.data_date)}</p></section>;
      })}</div>
    </div>
  </div>;
}

export function ProposalModelComparison({ meta, selectedModel, onModel, live = false }: { meta: Data; selectedModel: string; onModel: (name: string) => void; live?: boolean }) {
  const models = ['xgboost', 'lightgbm'].map(name => meta.models[name]);
  const score = (model: Data, key: string) => model.test_metrics[key];
  const reference = models.find(model => model.is_reference);
  return <section className="proposal-card proposal-comparison"><h2>MODEL COMPARISON</h2><p className="proposal-evaluation-label">Final Test · model beku</p><div className="proposal-comparison-table"><table><thead><tr><th>Model</th><th>Accuracy</th><th>Precision</th><th>Recall</th><th>Macro F1</th></tr></thead><tbody>{models.map(model => <tr key={model.name} className={model.name === selectedModel ? 'selected' : ''}><td><button aria-label={`Tampilkan prediksi ${modelName(model.name)}`} onClick={() => onModel(model.name)}>{modelName(model.name)}</button>{model.is_reference && <span className="proposal-reference" title="Model acuan berdasarkan Macro F1 validation"><Star size={8} fill="currentColor" />REF</span>}</td><td>{format(score(model, 'accuracy'), 3)}</td><td>{format(score(model, 'macro_precision'), 3)}</td><td>{format(score(model, 'macro_recall'), 3)}</td><td>{format(score(model, 'macro_f1'), 3)}</td></tr>)}</tbody></table></div><div className="proposal-evaluation"><p>{`Final test: ${meta.final_test.rows} tanggal · ${date(meta.final_test.start_date)} – ${date(meta.final_test.end_date)}`}</p><p>Target: Next 5 Trading Days Market Regime</p><p>Precision / Recall: macro average · scores 0–1</p><p>Skor satu blok test; model dan threshold tetap.</p><p>Reference: {reference ? modelName(reference.name) : '—'} · Macro F1 validation</p></div><p className="proposal-model-hint">{live ? 'Klik model untuk membuka prediksi historis pada mode Penelitian.' : 'Klik nama model untuk menampilkan prediksinya.'}</p></section>;
}

export function ProposalStatusGuide() {
  const guides = [
    { status: 'Stable', title: 'STABLE', color: '#2c9d48', icon: CircleCheck, text: 'Tidak ada pasangan regime yang memicu Caution atau Warning.' },
    { status: 'Caution', title: 'CAUTION', color: '#ec980b', icon: TriangleAlert, text: 'Kondisi Bullish diprediksi beralih menjadi Sideways.' },
    { status: 'Warning', title: 'WARNING', color: '#ee1e28', icon: TriangleAlert, text: 'Model memprediksi future market regime Bearish.' },
  ];
  return <aside className="proposal-card proposal-guide"><h2>EARLY WARNING STATUS GUIDE</h2><div>{guides.map(guide => <section key={guide.status}><div style={{ color: guide.color }}><guide.icon size={23} strokeWidth={1.7} /><h3>{guide.title}</h3></div><p>{guide.text}</p></section>)}</div><small>Stable tidak berarti bebas risiko.</small></aside>;
}
