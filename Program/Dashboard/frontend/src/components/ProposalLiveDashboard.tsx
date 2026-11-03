import { useEffect, useState } from 'react';
import { Activity, ArrowDown, ArrowUp, Clock3, ExternalLink, Info, Wifi, WifiOff } from 'lucide-react';
import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { ProposalModelComparison, ProposalStatusGuide } from './ProposalDashboard';

type Data = Record<string, any>;
export type MarketFeed = {
  quote: null | { price: number; previous_close: number | null; change: number | null; change_percent: number | null; day_high: number | null; day_low: number | null; quote_as_of: string; trading_date: string; points: { time: number; price: number }[] };
  feed_status: string; last_error: string | null; last_success_at: string | null;
  quote_age_seconds: number | null; freshness: string; source_url: string; definition_note?: string; unit?: string;
};
type DomesticFeed = {
  observation: null | { value: number; reference_label: string; decision_date: string | null; reference_period: string | null };
  provider: string; source_url: string; feed_status: string; last_error: string | null;
  last_success_at: string | null; next_poll_at: string | null;
};
type LiveState = { market: MarketFeed | null; indicators: Record<string, MarketFeed>; domestic: Record<string, DomesticFeed>; error: string; indicatorError: string; domesticError: string };
const format = (v: number | null | undefined, digits = 2) => v === null || v === undefined || !Number.isFinite(v) ? '—' : v.toLocaleString('en-US', { minimumFractionDigits: digits, maximumFractionDigits: digits });
const signed = (v: number | null | undefined, digits = 2) => v === null || v === undefined ? '—' : `${v > 0 ? '+' : ''}${format(v, digits)}`;
export const liveTime = (v?: string | null) => v ? new Date(v).toLocaleString('id-ID', { timeZone: 'Asia/Jakarta', day: 'numeric', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit', second: '2-digit' }) + ' WIB' : 'Belum tersedia';
const hour = (v: number) => new Date(v * 1000).toLocaleTimeString('id-ID', { timeZone: 'Asia/Jakarta', hour: '2-digit', minute: '2-digit' });

export function useMarketFeeds(enabled: boolean): LiveState {
  const [state, setState] = useState<LiveState>({ market: null, indicators: {}, domestic: {}, error: '', indicatorError: '', domesticError: '' });
  useEffect(() => {
    if (!enabled) return;
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    let stopped = false;
    const get = async (path: string) => {
      const r = await fetch(path, { signal: controller.signal, cache: 'no-store' });
      if (!r.ok) throw new Error(r.status === 404 ? 'Jalankan ulang program untuk memuat koneksi indikator baru.' : 'Koneksi dashboard belum tersedia. Mencoba kembali otomatis.');
      return r.json();
    };
    const poll = async () => {
      const [market, indicators, domestic] = await Promise.allSettled([get('/api/v1/market/live'), get('/api/v1/market/live/indicators'), get('/api/v1/market/live/domestic')]);
      if (!stopped) {
        setState(previous => ({
          market: market.status === 'fulfilled' ? market.value : previous.market,
          indicators: indicators.status === 'fulfilled' ? indicators.value.items : previous.indicators,
          domestic: domestic.status === 'fulfilled' ? domestic.value.items : previous.domestic,
          error: market.status === 'fulfilled' ? '' : 'Koneksi IHSG belum tersedia. Cache terakhir dipertahankan.',
          indicatorError: indicators.status === 'fulfilled' ? '' : indicators.reason?.message || 'Koneksi indikator belum tersedia.',
          domesticError: domestic.status === 'fulfilled' ? '' : domestic.reason?.message || 'Publikasi domestik belum tersedia.',
        }));
        timer = setTimeout(poll, 15000);
      }
    };
    void poll();
    return () => { stopped = true; clearTimeout(timer); controller.abort(); };
  }, [enabled]);
  return state;
}

function LiveSpark({ feed, color }: { feed?: MarketFeed; color: string }) {
  const points = feed?.quote?.points.slice(-20) || [];
  return <div className="proposal-spark" aria-hidden="true"><ResponsiveContainer width="100%" height="100%"><LineChart data={points}><YAxis hide domain={['dataMin', 'dataMax']} /><Line dataKey="price" type="linear" stroke={color} strokeWidth={1.5} dot={false} isAnimationActive={false} /></LineChart></ResponsiveContainer></div>;
}

function DomesticPublications({ feeds, error }: { feeds: Record<string, DomesticFeed>; error: string }) {
  return <section className="domestic-publications" aria-label="Publikasi domestik terbaru">
    <div className="domestic-heading"><h2>PUBLIKASI DOMESTIK TERBARU</h2><span>Diperiksa otomatis setiap 6 jam</span></div>
    {error && <p className="live-indicator-error" role="alert">{error}</p>}
    <div className="domestic-cards">{[
      { key: 'BI_Rate', title: 'BI-RATE', provider: 'Bank Indonesia', note: 'Suku bunga kebijakan · berubah sesuai keputusan BI' },
      { key: 'Inflation_YoY', title: 'INFLASI IHK · YOY', provider: 'BPS melalui Bank Indonesia', note: 'Inflasi tahunan nasional · publikasi bulanan' },
    ].map(item => {
      const feed = feeds[item.key]; const observation = feed?.observation;
      const failed = error || feed?.last_error;
      return <article className="proposal-card domestic-card" key={item.key}>
        <div className="domestic-card-title"><h3>{item.title}</h3><span>Publikasi terbaru</span></div>
        <strong className="domestic-value">{observation ? `${observation.value.toLocaleString('id-ID', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}%` : '—'}</strong>
        <p className="domestic-period">{observation ? `${item.key === 'BI_Rate' ? 'Keputusan' : 'Periode'}: ${observation.reference_label}` : 'Menunggu publikasi sumber'}</p>
        <p>{item.note}</p>
        {item.key === 'Inflation_YoY' && <p>Bulan referensi berbeda dari tanggal rilis.</p>}
        <div className="domestic-source">{feed?.source_url ? <a href={feed.source_url} target="_blank" rel="noreferrer">{feed.provider}<ExternalLink size={11} /></a> : <span>{item.provider}</span>}
          <span className={failed ? 'domestic-connection-error' : ''}>{failed ? observation ? 'Koneksi bermasalah · cache terakhir' : 'Belum terhubung' : feed?.feed_status === 'disabled' ? 'Pembaruan nonaktif' : feed?.feed_status === 'cached' ? 'Cache tersimpan' : observation ? 'Terhubung' : 'Menyambungkan'}</span>
        </div>
        <small>Terakhir diperiksa: {liveTime(feed?.last_success_at)}</small>
      </article>;
    })}</div>
    <p className="domestic-usage">Model penelitian memakai BI-Rate Change dan Inflation Change antarrilis. Publikasi terbaru di sini menjadi konteks live; belum otomatis memperbarui prediksi penelitian.</p>
  </section>;
}

export function ProposalLiveDashboard({ state, meta, selectedModel, onModel }: {
  state: LiveState; meta: Data; selectedModel: string; onModel: (name: string) => void;
}) {
  const feed = state.market;
  const q = feed?.quote;
  const connected = feed?.feed_status === 'connected' && !state.error;
  const message = state.error || feed?.last_error;
  const definitions = [
    { key: 'USD_IDR', title: 'USD/IDR — MARKET QUOTE', color: '#2461ac', digits: 2, unit: 'IDR / USD' },
    { key: 'Brent', title: 'BRENT FUTURES (BZ=F)', color: '#249643', digits: 2, unit: 'USD / barel' },
    { key: 'US10Y', title: 'US10Y INDEX QUOTE (^TNX)', color: '#2461ac', digits: 3, unit: 'Quote indeks Yahoo' },
  ];
  return <div className="proposal-dashboard proposal-live-dashboard">
    <div className="proposal-provenance live-provenance"><Activity size={14} /><span>Mode Live · quote diperiksa setiap 60 detik; publikasi domestik setiap 6 jam. Waktu data mengikuti sumber.</span><b><span className={`live-connection-dot ${connected ? 'connected' : ''}`} />{connected ? 'Terhubung' : feed?.feed_status === 'disabled' ? 'Feed nonaktif' : message ? 'Koneksi bermasalah' : 'Menyambungkan'}</b></div>
    {(message || state.indicatorError) && <div className="proposal-live-error" role="alert"><WifiOff size={15} /><span>{message || state.indicatorError}</span></div>}
    <div className="proposal-summary">
      <section className="proposal-card proposal-stat proposal-close"><h2>LAST IHSG QUOTE</h2><strong>{format(q?.price)}</strong><div style={{ color: (q?.change || 0) < 0 ? '#ed1924' : '#269a43' }}>{q ? `${signed(q.change)} (${signed(q.change_percent)}%)` : 'Menunggu data sumber'}</div><p>vs Previous Close · delayed</p></section>
      <section className="proposal-card proposal-stat proposal-close"><h2>IHSG DAY HIGH</h2><strong>{format(q?.day_high)}</strong><ArrowUp className="proposal-stat-icon" size={27} color="#299942" /><p>Nilai tertinggi pada sesi sumber</p></section>
      <section className="proposal-card proposal-stat proposal-close"><h2>IHSG DAY LOW</h2><strong>{format(q?.day_low)}</strong><ArrowDown className="proposal-stat-icon" size={27} color="#e6333b" /><p>Nilai terendah pada sesi sumber</p></section>
      <section className="proposal-card proposal-stat"><h2>FEED STATUS</h2><strong className="proposal-regime live-feed-state">{feed?.feed_status === 'disabled' ? 'Nonaktif' : connected ? 'Delayed' : message ? 'Terputus' : 'Menunggu'}</strong>{connected ? <Wifi className="proposal-stat-icon" size={29} color="#299942" /> : <WifiOff className="proposal-stat-icon" size={29} color="#bb8c36" />}<p>{q ? `Harga: ${liveTime(q.quote_as_of)}` : 'Tidak menampilkan harga contoh'}</p></section>
    </div>
    <div className="proposal-main-grid">
      <section className="proposal-card proposal-trend live-proposal-trend"><div className="proposal-panel-title"><h2>IHSG — INTRADAY · DELAYED</h2><span className="live-auto-tag">AUTO 60s</span></div>
        {q ? <div className="proposal-price-chart" role="img" aria-label={`Grafik intraday IHSG, ${q.points.length} titik`}><ResponsiveContainer width="100%" height="100%"><LineChart data={q.points} margin={{ top: 10, right: 12, left: -3, bottom: 8 }}><CartesianGrid vertical={false} strokeDasharray="3 4" stroke="#e8e8e8" /><XAxis dataKey="time" type="number" domain={['dataMin', 'dataMax']} tickFormatter={hour} axisLine={false} tickLine={false} minTickGap={35} tick={{ fontSize: 10, fill: '#525252' }} /><YAxis domain={['auto', 'auto']} tickFormatter={v => format(v, 0)} width={58} axisLine={false} tickLine={false} tick={{ fontSize: 10, fill: '#525252' }} /><Tooltip labelFormatter={v => liveTime(new Date(Number(v) * 1000).toISOString())} formatter={(v: any) => [format(Number(v)), 'IHSG']} contentStyle={{ border: '1px solid #ddd', borderRadius: 5, fontSize: 11 }} /><Line dataKey="price" type="linear" stroke="#ff2028" strokeWidth={1.65} dot={false} isAnimationActive={false} /></LineChart></ResponsiveContainer></div> : <div className="proposal-chart-message">{message ? 'Harga belum tersedia. Mencoba kembali otomatis.' : 'Menunggu harga pertama dari sumber…'}</div>}
        <div className="live-chart-footer"><Clock3 size={11} /><span>Diambil: {liveTime(feed?.last_success_at)}</span>{feed?.source_url && <a href={feed.source_url} target="_blank" rel="noreferrer">Sumber <ExternalLink size={10} /></a>}</div>
      </section>
      <ProposalModelComparison meta={meta} selectedModel={selectedModel} onModel={onModel} live />
      <ProposalStatusGuide />
      <div className="proposal-indicators live-indicators">
        <section className="proposal-card proposal-indicator live-unavailable"><h2>FOREIGN NET FLOW (IDR)</h2><strong>Belum tersambung</strong><p>Sumber live belum terverifikasi.</p><span>Nilai historis tersedia di mode Penelitian.</span></section>
        {definitions.map(item => {
          const indicator = state.indicators[item.key]; const quote = indicator?.quote;
          return <section className="proposal-card proposal-indicator live-indicator" key={item.key}><h2>{item.title}<span className="live-proxy-tag">PROXY</span></h2><div className="proposal-indicator-main"><div><strong style={{ color: item.color }}>{format(quote?.price, item.digits)}</strong><span>{item.unit}</span><p style={{ color: (quote?.change || 0) < 0 ? '#d82a31' : '#299942' }}>{quote ? item.key === 'US10Y' ? `${signed(quote.change, 3)} quote` : `${signed(quote.change)} (${signed(quote.change_percent)}%)` : 'Menunggu sumber'}</p></div><LiveSpark feed={indicator} color={item.color} /></div><p className="proposal-indicator-date">{quote ? liveTime(quote.quote_as_of) : 'Waktu sumber belum tersedia'}</p>{indicator?.last_error && <p className="live-indicator-error">Koneksi bermasalah; cache terakhir.</p>}<span className="live-definition" title={indicator?.definition_note}>{item.key === 'USD_IDR' ? 'Quote pasar, berbeda dari kurs ECB.' : item.key === 'Brent' ? 'Futures, bukan Brent spot penelitian.' : 'Quote ^TNX, bukan seri resmi DGS10.'}</span></section>;
        })}
      </div>
    </div>
    <DomesticPublications feeds={state.domestic} error={state.domesticError} />
    {q && ['no_recent_tick', 'previous_trading_date'].includes(feed?.freshness || '') && <p className="live-tick-note">Belum ada tick IHSG yang lebih baru pada sumber. Harga dapat tetap saat perdagangan jeda/tutup atau feed terlambat. Periksa timestamp di atas.</p>}
    <div className="live-model-boundary"><Info size={15} /><p><strong>Live adalah pantauan harga.</strong> Prediksi EWS terbaru belum dihitung karena seluruh input harian model belum tersambung. Pilih <b>Penelitian</b> untuk melihat hasil model pada tanggal historis. Quote proxy tidak masuk fitur model.</p></div>
  </div>;
}
