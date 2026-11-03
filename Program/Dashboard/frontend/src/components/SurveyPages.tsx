import React, { useEffect, useState } from 'react';
import {
  BarChart3,
  Check,
  ChevronLeft,
  ChevronRight,
  Download,
  FileSpreadsheet,
  FileText,
  LockKeyhole,
  PieChart as PieChartIcon,
  Printer,
  RefreshCw,
  Send,
  ShieldCheck,
  User,
} from 'lucide-react';
import { Cell, Pie, PieChart as RechartsPieChart, ResponsiveContainer, Tooltip as RechartsTooltip } from 'recharts';

const API = '/api/v1/survey';

type SurveySchema = {
  title: string;
  description: string;
  consent_text: string;
  respondent_types: string[];
  likert_options: { value: number; label: string }[];
  sections: { id: string; title: string; items: { id: string; text: string }[] }[];
  question_count: number;
};

type SurveyResponse = {
  id: string;
  submitted_at: string;
  respondent_type: string;
  answers: Record<string, number>;
  comment: string;
  respondent_name?: string;
  respondent_email?: string;
  respondent_phone?: string;
  respondent_age?: number;
};

type SurveySummary = {
  response_count: number;
  overall_mean: number | null;
  respondent_types: Record<string, number>;
  sections: { id: string; title: string; mean: number | null }[];
  questions: Record<string, { count: number; mean: number | null; distribution: Record<string, number> }>;
  likert_options: { value: number; label: string }[];
};

// Palet warna khas Google Forms untuk opsi kuesioner
const LIKERT_COLORS = ['#ea4335', '#ff7043', '#fbbc04', '#4285f4', '#34a853'];

function GFormQuestionPieChart({
  options,
  metric,
  count,
}: {
  options: { value: number; label: string }[];
  metric?: { count: number; mean: number | null; distribution: Record<string, number> };
  count: number;
}) {
  const pieData = options.map((opt, idx) => {
    const freq = metric?.distribution[String(opt.value)] ?? 0;
    const pct = count > 0 ? (freq / count) * 100 : 0;
    return {
      name: `${opt.value}. ${opt.label}`,
      value: freq,
      percent: pct,
      color: LIKERT_COLORS[idx % LIKERT_COLORS.length],
      rawOption: opt,
    };
  });

  const activeSlices = pieData.filter(d => d.value > 0);

  if (count === 0 || activeSlices.length === 0) {
    return (
      <p className="gform-muted-text" style={{ padding: '24px 0', textAlign: 'center' }}>
        Belum ada data untuk diagram lingkaran ini.
      </p>
    );
  }

  return (
    <div className="gform-pie-container">
      <div className="gform-pie-chart-area">
        <ResponsiveContainer width={240} height={210}>
          <RechartsPieChart>
            <Pie
              data={activeSlices}
              dataKey="value"
              nameKey="name"
              cx="50%"
              cy="50%"
              outerRadius={85}
              innerRadius={0}
              stroke="#ffffff"
              strokeWidth={2}
              isAnimationActive={false}
            >
              {activeSlices.map((entry, index) => (
                <Cell key={`cell-${index}`} fill={entry.color} />
              ))}
            </Pie>
            <RechartsTooltip
              content={({ active, payload }) => {
                if (active && payload && payload.length) {
                  const data = payload[0].payload;
                  return (
                    <div className="gform-pie-tooltip">
                      <span className="gform-pie-tooltip-dot" style={{ backgroundColor: data.color }} />
                      <div>
                        <strong>{data.name}</strong>
                        <div>
                          {data.value} tanggapan ({data.percent.toFixed(1)}%)
                        </div>
                      </div>
                    </div>
                  );
                }
                return null;
              }}
            />
          </RechartsPieChart>
        </ResponsiveContainer>
      </div>

      <div className="gform-pie-legend">
        {pieData.map((item, idx) => (
          <div key={idx} className={`gform-pie-legend-row ${item.value === 0 ? 'empty' : ''}`}>
            <span className="gform-pie-legend-color" style={{ backgroundColor: item.color }} />
            <span className="gform-pie-legend-text">{item.name}</span>
            <span className="gform-pie-legend-val">
              <strong>{item.value}</strong>
              <small>({item.percent.toFixed(1)}%)</small>
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

function GFormAgePieChart({ responses }: { responses: SurveyResponse[] }) {
  const agesWithData = responses.filter(r => r.respondent_age != null);
  if (agesWithData.length === 0) return null;

  const brackets = [
    { label: '< 20 th', count: 0, color: '#4285f4' },
    { label: '20 - 25 th', count: 0, color: '#34a853' },
    { label: '26 - 30 th', count: 0, color: '#fbbc04' },
    { label: '> 30 th', count: 0, color: '#ea4335' },
  ];

  agesWithData.forEach(r => {
    const age = r.respondent_age!;
    if (age < 20) brackets[0].count++;
    else if (age <= 25) brackets[1].count++;
    else if (age <= 30) brackets[2].count++;
    else brackets[3].count++;
  });

  const activeBrackets = brackets.filter(b => b.count > 0);

  return (
    <div className="gform-card">
      <div className="gform-card-header">
        <h3>Diagram Kelompok Usia Responden</h3>
        <span>{agesWithData.length} data usia</span>
      </div>
      <div className="gform-pie-container">
        <div className="gform-pie-chart-area">
          <ResponsiveContainer width={240} height={200}>
            <RechartsPieChart>
              <Pie
                data={activeBrackets}
                dataKey="count"
                nameKey="label"
                cx="50%"
                cy="50%"
                outerRadius={75}
                innerRadius={0}
                stroke="#fff"
                strokeWidth={2}
                isAnimationActive={false}
              >
                {activeBrackets.map((entry, idx) => (
                  <Cell key={idx} fill={entry.color} />
                ))}
              </Pie>
              <RechartsTooltip
                content={({ active, payload }) => {
                  if (active && payload && payload.length) {
                    const data = payload[0].payload;
                    const pct = (data.count / agesWithData.length) * 100;
                    return (
                      <div className="gform-pie-tooltip">
                        <span className="gform-pie-tooltip-dot" style={{ backgroundColor: data.color }} />
                        <div>
                          <strong>{data.label}</strong>
                          <div>
                            {data.count} responden ({pct.toFixed(1)}%)
                          </div>
                        </div>
                      </div>
                    );
                  }
                  return null;
                }}
              />
            </RechartsPieChart>
          </ResponsiveContainer>
        </div>
        <div className="gform-pie-legend">
          {brackets.map((b, idx) => {
            const pct = agesWithData.length > 0 ? (b.count / agesWithData.length) * 100 : 0;
            return (
              <div key={idx} className={`gform-pie-legend-row ${b.count === 0 ? 'empty' : ''}`}>
                <span className="gform-pie-legend-color" style={{ backgroundColor: b.color }} />
                <span className="gform-pie-legend-text">{b.label}</span>
                <span className="gform-pie-legend-val">
                  <strong>{b.count}</strong>
                  <small>({pct.toFixed(1)}%)</small>
                </span>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}

function useSurveySchema() {
  const [schema, setSchema] = useState<SurveySchema | null>(null);
  const [error, setError] = useState('');
  useEffect(() => {
    fetch(`${API}/uat/schema`)
      .then(async response => {
        if (!response.ok) throw new Error('Kuesioner belum dapat dimuat.');
        return response.json();
      })
      .then(setSchema)
      .catch(reason => setError(reason.message || 'Terjadi kesalahan saat memuat kuesioner.'));
  }, []);
  return { schema, error };
}

function PageIntro({ eyebrow, title, text, icon }: { eyebrow: string; title: string; text: string; icon: React.ReactNode }) {
  return (
    <div className="survey-intro">
      <div className="survey-intro-icon">{icon}</div>
      <div>
        <div className="eyebrow heading-eyebrow">{eyebrow}</div>
        <h1>{title}</h1>
        <p>{text}</p>
      </div>
    </div>
  );
}

/**
 * Komponen Analisis Tanggapan ala Google Forms
 * Menyediakan 3 Sub-tab: Ringkasan (Summary), Pertanyaan (Question), dan Individual
 */
export function GFormSurveyAnalytics({
  schema,
  summary,
  responses,
  onRefresh,
  loading,
}: {
  schema: SurveySchema;
  summary: SurveySummary | null;
  responses: SurveyResponse[];
  onRefresh?: () => void;
  loading?: boolean;
}) {
  const [subtab, setSubtab] = useState<'summary' | 'question' | 'individual'>('summary');
  const [questionIdx, setQuestionIdx] = useState(0);
  const [respondentIdx, setRespondentIdx] = useState(0);
  const [globalChartType, setGlobalChartType] = useState<'pie' | 'bar'>('pie');
  const [cardOverrides, setCardOverrides] = useState<Record<string, 'pie' | 'bar'>>({});

  const total = responses.length;
  const allQuestions = schema.sections.flatMap(section => section.items.map(item => ({ ...item, sectionTitle: section.title })));
  const currentQuestion = allQuestions[questionIdx] || allQuestions[0];
  const currentRespondent = responses[respondentIdx] || responses[0];

  const overallMean = summary?.overall_mean ?? 0;
  // Perhitungan Tingkat Capaian Responden (TCR %)
  const tcr = overallMean ? (overallMean / 5) * 100 : 0;
  const kelayakan =
    tcr >= 81 ? 'Sangat Baik / Sangat Layak' :
    tcr >= 61 ? 'Baik / Layak' :
    tcr >= 41 ? 'Cukup Layak' :
    tcr > 0 ? 'Kurang Layak' : '—';

  const downloadCsv = () => {
    const anchor = document.createElement('a');
    anchor.href = `${API}/export.csv`;
    anchor.download = 'ews_ihsg_uat_responses.csv';
    anchor.click();
  };

  const handlePrint = () => {
    window.print();
  };

  return (
    <div className="gform-analytics-container">
      {/* Google Forms Top Bar */}
      <div className="gform-analytics-header">
        <div className="gform-analytics-title-group">
          <h2>{total} tanggapan</h2>
          <span className="gform-analytics-badge">UAT Sistem EWS IHSG</span>
        </div>
        <div className="gform-analytics-actions">
          <button className="gform-btn gform-btn-sheets" onClick={downloadCsv} title="Unduh tanggapan dalam format CSV/Spreadsheet">
            <FileSpreadsheet size={16} />
            <span>Unduh Spreadsheet (CSV)</span>
          </button>
          {onRefresh && (
            <button className="gform-btn gform-btn-secondary" onClick={onRefresh} disabled={loading} title="Segarkan data">
              <RefreshCw size={14} className={loading ? 'spin' : ''} />
              <span>Segarkan</span>
            </button>
          )}
        </div>
      </div>

      {/* Sub-tab Navigation: Ringkasan, Pertanyaan, Individual */}
      <div className="gform-subtabs">
        <button className={`gform-subtab-btn ${subtab === 'summary' ? 'active' : ''}`} onClick={() => setSubtab('summary')}>
          Ringkasan
        </button>
        <button className={`gform-subtab-btn ${subtab === 'question' ? 'active' : ''}`} onClick={() => setSubtab('question')} disabled={total === 0}>
          Pertanyaan
        </button>
        <button className={`gform-subtab-btn ${subtab === 'individual' ? 'active' : ''}`} onClick={() => setSubtab('individual')} disabled={total === 0}>
          Individual
        </button>
      </div>

      {loading && <div className="survey-alert">Mengambil data tanggapan terbaru…</div>}

      {total === 0 && !loading && (
        <div className="gform-empty-card">
          <FileText size={36} />
          <h3>Belum ada tanggapan yang masuk</h3>
          <p>Setelah responden mengisi kuesioner, grafik dan analisis otomatis akan muncul di sini persis seperti Google Form.</p>
        </div>
      )}

      {total > 0 && summary && (
        <>
          {/* ==================== SUB-TAB 1: RINGKASAN ==================== */}
          {subtab === 'summary' && (
            <div className="gform-tab-content">
              {/* Metrik Statistik UAT */}
              <div className="gform-kpi-grid">
                <div className="gform-kpi-card">
                  <span className="gform-kpi-label">TOTAL TANGGAPAN</span>
                  <strong className="gform-kpi-val">{total}</strong>
                  <small>Responden UAT</small>
                </div>
                <div className="gform-kpi-card">
                  <span className="gform-kpi-label">RATA-RATA SKOR (MEAN)</span>
                  <strong className="gform-kpi-val highlight">{overallMean ? overallMean.toFixed(2) : '—'} <span className="denom">/ 5.0</span></strong>
                  <small>Skala Likert 1-5</small>
                </div>
                <div className="gform-kpi-card">
                  <span className="gform-kpi-label">CAPAIAN RESPONDEN (TCR)</span>
                  <strong className="gform-kpi-val">{tcr.toFixed(1)}%</strong>
                  <span className="gform-kpi-badge">{kelayakan}</span>
                </div>
              </div>

              {/* Rata-rata per Aspek / Dimensi */}
              <div className="gform-card">
                <div className="gform-card-header">
                  <h3>Rata-rata Skor per Dimensi Evaluasi</h3>
                  <span>{schema.sections.length} dimensi</span>
                </div>
                <div className="gform-dimension-list">
                  {summary.sections.map(section => (
                    <div className="gform-dimension-row" key={section.id}>
                      <div className="gform-dimension-info">
                        <strong>{section.title}</strong>
                        <span>{section.mean != null ? `${section.mean.toFixed(2)} / 5.0` : '—'}</span>
                      </div>
                      <div className="gform-bar-track">
                        <div
                          className="gform-bar-fill accent"
                          style={{ width: `${((section.mean || 0) / 5) * 100}%` }}
                        />
                      </div>
                    </div>
                  ))}
                </div>
              </div>

              {/* Demografi Responden: Nama, Email, Telp, Umur */}
              <div className="gform-card">
                <div className="gform-card-header">
                  <h3>Nama Lengkap</h3>
                  <span>{total} tanggapan</span>
                </div>
                <div className="gform-text-answers-list">
                  {responses.map((resp, i) => (
                    <div className="gform-text-answer-item" key={resp.id || i}>
                      <span className="gform-text-num">{i + 1}.</span>
                      <strong>{resp.respondent_name || 'Tanpa Nama'}</strong>
                    </div>
                  ))}
                </div>
              </div>

              <div className="gform-card">
                <div className="gform-card-header">
                  <h3>Alamat Email</h3>
                  <span>{total} tanggapan</span>
                </div>
                <div className="gform-text-answers-list">
                  {responses.map((resp, i) => (
                    <div className="gform-text-answer-item" key={resp.id || i}>
                      <span className="gform-text-num">{i + 1}.</span>
                      <span>{resp.respondent_email || '—'}</span>
                    </div>
                  ))}
                </div>
              </div>

              <div className="gform-grid-2col">
                <div className="gform-card">
                  <div className="gform-card-header">
                    <h3>Nomor Telepon</h3>
                    <span>{responses.filter(r => r.respondent_phone).length} tanggapan</span>
                  </div>
                  <div className="gform-text-answers-list compact">
                    {responses.filter(r => r.respondent_phone).map((resp, i) => (
                      <div className="gform-text-answer-item" key={resp.id || i}>
                        <span>{resp.respondent_phone}</span>
                      </div>
                    ))}
                    {responses.filter(r => r.respondent_phone).length === 0 && (
                      <p className="gform-muted-text">Tidak ada nomor telepon yang diisi.</p>
                    )}
                  </div>
                </div>

                <div className="gform-card">
                  <div className="gform-card-header">
                    <h3>Umur Responden</h3>
                    <span>
                      Rata-rata:{' '}
                      {responses.filter(r => r.respondent_age != null).length > 0
                        ? (
                            responses.reduce((sum, r) => sum + (r.respondent_age || 0), 0) /
                            responses.filter(r => r.respondent_age != null).length
                          ).toFixed(1) + ' th'
                        : '—'}
                    </span>
                  </div>
                  <div className="gform-text-answers-list compact">
                    {responses.map((resp, i) => (
                      <div className="gform-text-answer-item" key={resp.id || i}>
                        <span>{resp.respondent_age != null ? `${resp.respondent_age} tahun` : '—'}</span>
                        <small className="gform-resp-tag">{resp.respondent_name}</small>
                      </div>
                    ))}
                  </div>
                </div>
              </div>

              {/* Diagram Kelompok Usia Responden (Pie Chart) */}
              <GFormAgePieChart responses={responses} />

              {/* Diagram Google Forms per Pernyataan (Pie Chart & Bar Chart Switcher) */}
              <div className="gform-section-separator gform-separator-with-toggle">
                <div>
                  <h4>Diagram Distribusi Jawaban Likert</h4>
                  <p>Visualisasi pilihan responden untuk setiap pernyataan</p>
                </div>
                <div className="gform-global-chart-switch">
                  <button
                    type="button"
                    className={`gform-chart-mode-pill ${globalChartType === 'pie' ? 'active' : ''}`}
                    onClick={() => {
                      setGlobalChartType('pie');
                      setCardOverrides({});
                    }}
                  >
                    <PieChartIcon size={14} />
                    <span>Diagram Lingkaran (Pie Chart)</span>
                  </button>
                  <button
                    type="button"
                    className={`gform-chart-mode-pill ${globalChartType === 'bar' ? 'active' : ''}`}
                    onClick={() => {
                      setGlobalChartType('bar');
                      setCardOverrides({});
                    }}
                  >
                    <BarChart3 size={14} />
                    <span>Diagram Batang (Bar Chart)</span>
                  </button>
                </div>
              </div>

              {schema.sections.map((section, sIdx) => (
                <div key={section.id}>
                  {section.items.map((item, iIdx) => {
                    const qNumber = sIdx * 3 + iIdx + 1;
                    const metric = summary.questions[item.id];
                    const count = metric?.count ?? 0;
                    const cardType = cardOverrides[item.id] || globalChartType;
                    return (
                      <div className="gform-card gform-chart-card" key={item.id}>
                        <div className="gform-card-header">
                          <div>
                            <span className="gform-question-code">Pernyataan {String(qNumber).padStart(2, '0')}</span>
                            <h3 className="gform-question-title">{item.text}</h3>
                          </div>
                          <div className="gform-card-header-right">
                            <div className="gform-question-meta-badge">
                              <span>{count} tanggapan</span>
                              <strong>Rata-rata: {metric?.mean != null ? metric.mean.toFixed(2) : '—'} / 5</strong>
                            </div>
                            <button
                              type="button"
                              className="gform-mini-chart-toggle"
                              onClick={() =>
                                setCardOverrides(prev => ({
                                  ...prev,
                                  [item.id]: cardType === 'pie' ? 'bar' : 'pie',
                                }))
                              }
                              title={cardType === 'pie' ? 'Ganti ke Diagram Batang' : 'Ganti ke Diagram Lingkaran (Pie Chart)'}
                            >
                              {cardType === 'pie' ? <BarChart3 size={13} /> : <PieChartIcon size={13} />}
                              <span>{cardType === 'pie' ? 'Batang' : 'Lingkaran (Pie)'}</span>
                            </button>
                          </div>
                        </div>

                        <div className="gform-chart-body">
                          {cardType === 'pie' ? (
                            <GFormQuestionPieChart
                              options={summary.likert_options}
                              metric={metric}
                              count={count}
                            />
                          ) : (
                            summary.likert_options.map((opt, oIdx) => {
                              const freq = metric?.distribution[String(opt.value)] ?? 0;
                              const pct = count > 0 ? (freq / count) * 100 : 0;
                              return (
                                <div className="gform-bar-row" key={opt.value}>
                                  <div className="gform-bar-label">
                                    <span className="gform-bar-number" style={{ color: LIKERT_COLORS[oIdx] }}>
                                      {opt.value}
                                    </span>
                                    <span className="gform-bar-text">{opt.label}</span>
                                  </div>
                                  <div className="gform-bar-track-wrap">
                                    <div
                                      className="gform-bar-fill"
                                      style={{
                                        width: `${pct}%`,
                                        backgroundColor: LIKERT_COLORS[oIdx],
                                      }}
                                    />
                                  </div>
                                  <div className="gform-bar-stats">
                                    <strong>{freq}</strong>
                                    <small>({pct.toFixed(1)}%)</small>
                                  </div>
                                </div>
                              );
                            })
                          )}
                        </div>
                      </div>
                    );
                  })}
                </div>
              ))}

              {/* Card Komentar & Catatan Tambahan */}
              <div className="gform-card">
                <div className="gform-card-header">
                  <h3>Catatan & Saran Tambahan Responden</h3>
                  <span>{responses.filter(r => r.comment).length} tanggapan</span>
                </div>
                <div className="gform-comments-list">
                  {responses.filter(r => r.comment).map((resp, i) => (
                    <div className="gform-comment-item" key={resp.id || i}>
                      <blockquote>"{resp.comment}"</blockquote>
                      <div className="gform-comment-author">
                        <span>— {resp.respondent_name || 'Responden Anonim'}</span>
                      </div>
                    </div>
                  ))}
                  {responses.filter(r => r.comment).length === 0 && (
                    <p className="gform-muted-text">Belum ada saran atau komentar yang dimasukkan.</p>
                  )}
                </div>
              </div>
            </div>
          )}

          {/* ==================== SUB-TAB 2: PERTANYAAN ==================== */}
          {subtab === 'question' && currentQuestion && (
            <div className="gform-tab-content">
              {/* Question Stepper */}
              <div className="gform-card gform-stepper-card">
                <div className="gform-stepper">
                  <div className="gform-stepper-nav">
                    <button
                      className="gform-stepper-arrow"
                      disabled={questionIdx <= 0}
                      onClick={() => setQuestionIdx(idx => Math.max(0, idx - 1))}
                    >
                      <ChevronLeft size={18} />
                    </button>
                    <select
                      className="gform-stepper-select"
                      value={questionIdx}
                      onChange={e => setQuestionIdx(Number(e.target.value))}
                    >
                      {allQuestions.map((q, idx) => (
                        <option key={q.id} value={idx}>
                          {String(idx + 1).padStart(2, '0')}. {q.text.slice(0, 50)}…
                        </option>
                      ))}
                    </select>
                    <button
                      className="gform-stepper-arrow"
                      disabled={questionIdx >= allQuestions.length - 1}
                      onClick={() => setQuestionIdx(idx => Math.min(allQuestions.length - 1, idx + 1))}
                    >
                      <ChevronRight size={18} />
                    </button>
                  </div>
                  <span className="gform-stepper-counter">
                    Pertanyaan {questionIdx + 1} dari {allQuestions.length}
                  </span>
                </div>

                <div className="gform-question-detail-header">
                  <span className="gform-dim-badge">{currentQuestion.sectionTitle}</span>
                  <h2>{currentQuestion.text}</h2>
                  <div className="gform-q-score-stat">
                    <span>
                      Rata-rata:{' '}
                      <strong>{summary.questions[currentQuestion.id]?.mean?.toFixed(2) ?? '—'} / 5.0</strong>
                    </span>
                    <span>
                      Total menjawab:{' '}
                      <strong>{summary.questions[currentQuestion.id]?.count ?? 0} orang</strong>
                    </span>
                  </div>
                </div>
              </div>

              {/* Daftar Responden per Skala Pilihan */}
              <div className="gform-breakdown-container">
                {schema.likert_options.map((opt, oIdx) => {
                  const respondersForThisOption = responses.filter(
                    r => r.answers && r.answers[currentQuestion.id] === opt.value
                  );
                  return (
                    <div className="gform-card gform-option-group" key={opt.value}>
                      <div className="gform-option-header">
                        <span className="gform-opt-bubble" style={{ backgroundColor: LIKERT_COLORS[oIdx] }}>
                          {opt.value}
                        </span>
                        <h4>{opt.label}</h4>
                        <span className="gform-opt-count">
                          {respondersForThisOption.length} tanggapan (
                          {total > 0 ? ((respondersForThisOption.length / total) * 100).toFixed(1) : 0}%)
                        </span>
                      </div>
                      {respondersForThisOption.length > 0 ? (
                        <div className="gform-responder-chips">
                          {respondersForThisOption.map((r, i) => (
                            <div className="gform-responder-chip" key={r.id || i}>
                              <User size={13} />
                              <span>{r.respondent_name || `Responden #${i + 1}`}</span>
                              {r.respondent_age && <small>({r.respondent_age} th)</small>}
                            </div>
                          ))}
                        </div>
                      ) : (
                        <p className="gform-muted-text">Tidak ada responden yang memilih opsi ini.</p>
                      )}
                    </div>
                  );
                })}
              </div>
            </div>
          )}

          {/* ==================== SUB-TAB 3: INDIVIDUAL ==================== */}
          {subtab === 'individual' && currentRespondent && (
            <div className="gform-tab-content">
              {/* Respondent Stepper */}
              <div className="gform-card gform-stepper-card">
                <div className="gform-stepper">
                  <div className="gform-stepper-nav">
                    <button
                      className="gform-stepper-arrow"
                      disabled={respondentIdx <= 0}
                      onClick={() => setRespondentIdx(idx => Math.max(0, idx - 1))}
                    >
                      <ChevronLeft size={18} />
                    </button>
                    <select
                      className="gform-stepper-select"
                      value={respondentIdx}
                      onChange={e => setRespondentIdx(Number(e.target.value))}
                    >
                      {responses.map((r, idx) => (
                        <option key={r.id || idx} value={idx}>
                          #{idx + 1} - {r.respondent_name || 'Responden Anonim'} ({r.respondent_age ? `${r.respondent_age} th` : 'Umur -'})
                        </option>
                      ))}
                    </select>
                    <button
                      className="gform-stepper-arrow"
                      disabled={respondentIdx >= responses.length - 1}
                      onClick={() => setRespondentIdx(idx => Math.min(responses.length - 1, idx + 1))}
                    >
                      <ChevronRight size={18} />
                    </button>
                  </div>
                  <div className="gform-stepper-actions">
                    <span className="gform-stepper-counter">
                      Tanggapan {respondentIdx + 1} dari {responses.length}
                    </span>
                    <button className="gform-btn gform-btn-print" onClick={handlePrint}>
                      <Printer size={15} />
                      <span>Cetak Lembar</span>
                    </button>
                  </div>
                </div>

                <div className="gform-individual-meta">
                  <div className="gform-ind-author">
                    <div className="gform-avatar">
                      <User size={22} />
                    </div>
                    <div>
                      <h2>{currentRespondent.respondent_name || 'Responden Anonim'}</h2>
                    </div>
                  </div>
                  <div className="gform-ind-score-badge">
                    <span>Skor Rata-rata</span>
                    <strong>
                      {(
                        Object.values(currentRespondent.answers).reduce((s, a) => s + a, 0) /
                        Math.max(Object.keys(currentRespondent.answers).length, 1)
                      ).toFixed(2)}{' '}
                      / 5.0
                    </strong>
                  </div>
                </div>
              </div>

              {/* Individual Sheet: Data Diri */}
              <div className="gform-card">
                <span className="survey-card-index">01 / INFORMASI RESPONDEN</span>
                <h3 className="gform-ind-section-title">Data Profil Responden</h3>
                <div className="gform-ind-profile-grid">
                  <div className="gform-ind-field">
                    <span>NAMA LENGKAP</span>
                    <strong>{currentRespondent.respondent_name || '—'}</strong>
                  </div>
                  <div className="gform-ind-field">
                    <span>ALAMAT EMAIL</span>
                    <strong>{currentRespondent.respondent_email || '—'}</strong>
                  </div>
                  <div className="gform-ind-field">
                    <span>NOMOR TELEPON</span>
                    <strong>{currentRespondent.respondent_phone || '—'}</strong>
                  </div>
                  <div className="gform-ind-field">
                    <span>UMUR</span>
                    <strong>
                      {currentRespondent.respondent_age != null
                        ? `${currentRespondent.respondent_age} tahun`
                        : '—'}
                    </strong>
                  </div>
                </div>
              </div>

              {/* Individual Sheet: Jawaban Kuesioner Lengkap */}
              {schema.sections.map((section, sIdx) => (
                <div className="gform-card" key={section.id}>
                  <span className="survey-card-index">
                    {String(sIdx + 2).padStart(2, '0')} / BAGIAN PENILAIAN
                  </span>
                  <h3 className="gform-ind-section-title">{section.title}</h3>

                  <div className="gform-ind-questions">
                    {section.items.map((item, iIdx) => {
                      const qNumber = sIdx * 3 + iIdx + 1;
                      const selectedVal = currentRespondent.answers?.[item.id];
                      return (
                        <div className="gform-ind-question-row" key={item.id}>
                          <p className="gform-ind-q-text">
                            <span>{String(qNumber).padStart(2, '0')}.</span> {item.text}
                          </p>
                          <div className="gform-ind-options-row">
                            {schema.likert_options.map(opt => {
                              const isChosen = selectedVal === opt.value;
                              return (
                                <div
                                  key={opt.value}
                                  className={`gform-ind-opt-pill ${isChosen ? 'chosen' : ''}`}
                                >
                                  <span className="gform-ind-opt-circle">
                                    {isChosen ? '✓' : opt.value}
                                  </span>
                                  <span className="gform-ind-opt-lbl">{opt.label}</span>
                                </div>
                              );
                            })}
                          </div>
                        </div>
                      );
                    })}
                  </div>
                </div>
              ))}

              {/* Catatan / Saran Responden */}
              <div className="gform-card">
                <span className="survey-card-index">OPSIONAL / MASUKAN</span>
                <h3 className="gform-ind-section-title">Catatan Tambahan</h3>
                {currentRespondent.comment ? (
                  <blockquote className="gform-ind-comment">
                    "{currentRespondent.comment}"
                  </blockquote>
                ) : (
                  <p className="gform-muted-text">Responden tidak meninggalkan catatan tambahan.</p>
                )}
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
}

/**
 * Halaman Utama Kuesioner dengan Fitur GForm
 * Pengguna dapat beralih antara Tab [Formulir] dan Tab [Tanggapan / Analisis]
 */
export function QuestionnairePage() {
  const { schema, error } = useSurveySchema();
  const [mainTab, setMainTab] = useState<'form' | 'responses'>('form');

  // State Form Kuesioner
  const [respName, setRespName] = useState('');
  const [respEmail, setRespEmail] = useState('');
  const [respPhone, setRespPhone] = useState('');
  const [respAge, setRespAge] = useState('');
  const [answers, setAnswers] = useState<Record<string, number>>({});
  const [comment, setComment] = useState('');
  const [consent, setConsent] = useState(false);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<{ type: 'success' | 'error'; text: string } | null>(null);

  // State Analytics Tanggapan
  const [summary, setSummary] = useState<SurveySummary | null>(null);
  const [responses, setResponses] = useState<SurveyResponse[]>([]);
  const [loadingAnalytics, setLoadingAnalytics] = useState(false);

  const complete = schema ? Object.keys(answers).length === schema.question_count : false;

  // Fungsi memuat data tanggapan
  const fetchAnalytics = () => {
    setLoadingAnalytics(true);
    Promise.all([
      fetch(`${API}/summary`).then(r => (r.ok ? r.json() : null)),
      fetch(`${API}/responses?limit=500`).then(r => (r.ok ? r.json() : null)),
    ])
      .then(([summaryData, responseData]) => {
        if (summaryData) setSummary(summaryData);
        if (responseData?.items) setResponses(responseData.items);
      })
      .catch(() => {})
      .finally(() => setLoadingAnalytics(false));
  };

  useEffect(() => {
    fetchAnalytics();
  }, []);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setMessage(null);
    if (!schema || !complete || !consent) {
      setMessage({ type: 'error', text: 'Lengkapi seluruh pernyataan dan persetujuan sebelum mengirim.' });
      return;
    }
    if (!respName.trim() || !respEmail.trim()) {
      setMessage({ type: 'error', text: 'Nama lengkap dan email wajib diisi.' });
      return;
    }
    setBusy(true);
    try {
      const body: Record<string, unknown> = {
        respondent_type: 'Umum',
        respondent_name: respName.trim(),
        respondent_email: respEmail.trim(),
        respondent_phone: respPhone.trim(),
        respondent_age: respAge.trim() ? Number(respAge) : null,
        answers,
        comment,
        consent,
      };
      const response = await fetch(`${API}/uat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      const result = await response.json();
      if (!response.ok) throw new Error(result.detail || 'Jawaban belum berhasil disimpan.');
      setMessage({ type: 'success', text: result.message || 'Jawaban berhasil disimpan.' });
      setAnswers({});
      setComment('');
      setConsent(false);
      setRespName('');
      setRespEmail('');
      setRespPhone('');
      setRespAge('');
      window.scrollTo({ top: 0, behavior: 'smooth' });
      fetchAnalytics();
    } catch (reason: any) {
      setMessage({ type: 'error', text: reason.message || 'Terjadi kesalahan saat mengirim jawaban.' });
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="survey-page">
      <PageIntro
        eyebrow="USER ACCEPTANCE TEST"
        title={schema?.title || 'Kuesioner UAT Sistem Early Warning IHSG'}
        text={schema?.description || 'Memuat kuesioner…'}
        icon={<ShieldCheck size={22} />}
      />

      {/* Main Tabs Header ala Google Forms: [Pertanyaan / Formulir] & [Tanggapan (X)] */}
      <div className="gform-main-tabs">
        <button
          className={`gform-main-tab-btn ${mainTab === 'form' ? 'active' : ''}`}
          onClick={() => setMainTab('form')}
        >
          <FileText size={16} />
          <span>Pertanyaan</span>
        </button>
        <button
          className={`gform-main-tab-btn ${mainTab === 'responses' ? 'active' : ''}`}
          onClick={() => {
            setMainTab('responses');
            fetchAnalytics();
          }}
        >
          <BarChart3 size={16} />
          <span>Tanggapan</span>
          <span className="gform-tab-count-badge">{responses.length}</span>
        </button>
      </div>

      {error && <div className="survey-alert error" role="alert">{error}</div>}
      {message && (
        <div className={`survey-alert ${message.type}`} role={message.type === 'error' ? 'alert' : 'status'}>
          {message.type === 'success' && <Check size={17} />}
          <span>{message.text}</span>
          {message.type === 'success' && (
            <button
              type="button"
              className="survey-btn-inline"
              onClick={() => {
                setMainTab('responses');
                fetchAnalytics();
              }}
            >
              Lihat Analisis Tanggapan →
            </button>
          )}
        </div>
      )}

      {/* TAMPILAN TAB 1: FORMULIR PENGISIAN */}
      {mainTab === 'form' && schema && (
        <form className="survey-form" onSubmit={submit}>
          <section className="survey-card survey-privacy">
            <span className="survey-card-index">01 / INFORMASI RESPONDEN</span>
            <h2>Sebelum mulai</h2>
            <p>
              Kuesioner ini mengevaluasi pengalaman menggunakan sistem Early Warning System (EWS) IHSG. Jawaban disimpan
              untuk analisis UAT.
            </p>
            <div className="survey-investor-fields">
              <label className="survey-field">
                <span className="survey-field-label">
                  Nama lengkap <span className="survey-required">*</span>
                </span>
                <input
                  type="text"
                  value={respName}
                  onChange={e => setRespName(e.target.value)}
                  placeholder="Masukkan nama lengkap Anda"
                  maxLength={120}
                  required
                />
              </label>
              <label className="survey-field">
                <span className="survey-field-label">
                  Alamat email <span className="survey-required">*</span>
                </span>
                <input
                  type="email"
                  value={respEmail}
                  onChange={e => setRespEmail(e.target.value)}
                  placeholder="contoh@email.com"
                  maxLength={254}
                  required
                />
              </label>
              <label className="survey-field">
                <span className="survey-field-label">Nomor telepon</span>
                <input
                  type="tel"
                  value={respPhone}
                  onChange={e => setRespPhone(e.target.value)}
                  placeholder="Contoh: 08123456789"
                  maxLength={20}
                />
              </label>
              <label className="survey-field">
                <span className="survey-field-label">
                  Umur <span className="survey-required">*</span>
                </span>
                <input
                  type="number"
                  value={respAge}
                  onChange={e => setRespAge(e.target.value)}
                  placeholder="Contoh: 25"
                  min={10}
                  max={99}
                  required
                />
              </label>
            </div>
          </section>

          {schema.sections.map((section, sectionIndex) => (
            <section className="survey-card" key={section.id}>
              <span className="survey-card-index">
                {String(sectionIndex + 2).padStart(2, '0')} / BAGIAN PENILAIAN
              </span>
              <h2>{section.title}</h2>
              <div className="survey-questions">
                {section.items.map((item, itemIndex) => (
                  <fieldset className="survey-question" key={item.id}>
                    <legend>
                      <span>{String(sectionIndex * 3 + itemIndex + 1).padStart(2, '0')}</span>
                      {item.text}
                    </legend>
                    <div className="survey-options">
                      {schema.likert_options.map(option => (
                        <label
                          key={option.value}
                          className={answers[item.id] === option.value ? 'selected' : ''}
                        >
                          <input
                            type="radio"
                            name={item.id}
                            value={option.value}
                            checked={answers[item.id] === option.value}
                            onChange={() => setAnswers(current => ({ ...current, [item.id]: option.value }))}
                            required
                          />
                          <span className="survey-option-value">{option.value}</span>
                          <span className="survey-option-label">{option.label}</span>
                        </label>
                      ))}
                    </div>
                  </fieldset>
                ))}
              </div>
            </section>
          ))}

          <section className="survey-card survey-comment">
            <span className="survey-card-index">OPSIONAL</span>
            <h2>Catatan tambahan</h2>
            <label className="survey-field">
              Masukan tentang pengalaman menggunakan sistem
              <textarea
                value={comment}
                maxLength={1200}
                onChange={event => setComment(event.target.value)}
                placeholder="Tulis saran atau kendala yang Anda temui. Jangan masukkan informasi pribadi."
                rows={4}
              />
            </label>
            <span className="survey-count">{comment.length} / 1.200 karakter</span>
          </section>

          <section className="survey-consent">
            <label>
              <input
                type="checkbox"
                checked={consent}
                onChange={event => setConsent(event.target.checked)}
                required
              />
              <span>{schema.consent_text}</span>
            </label>
            <p>Skala jawaban: 1 Sangat tidak setuju · 2 Tidak setuju · 3 Netral · 4 Setuju · 5 Sangat setuju.</p>
          </section>

          <div className="survey-submit-row">
            <span>
              {Object.keys(answers).length} dari {schema.question_count} pernyataan terjawab
            </span>
            <button className="survey-button primary" type="submit" disabled={busy}>
              {busy ? 'Mengirim…' : 'Kirim jawaban'} <Send size={15} />
            </button>
          </div>
        </form>
      )}

      {/* TAMPILAN TAB 2: ANALISIS TANGGAPAN ALA GFORM */}
      {mainTab === 'responses' && schema && (
        <GFormSurveyAnalytics
          schema={schema}
          summary={summary}
          responses={responses}
          onRefresh={fetchAnalytics}
          loading={loadingAnalytics}
        />
      )}
    </div>
  );
}

/**
 * Halaman Admin Standalone (/ngopiii)
 */
function basicAuthorization(username: string, password: string) {
  const bytes = new TextEncoder().encode(`${username}:${password}`);
  let binary = '';
  bytes.forEach(byte => {
    binary += String.fromCharCode(byte);
  });
  return `Basic ${btoa(binary)}`;
}

function AdminLogin({
  username,
  setUsername,
  password,
  setPassword,
  onSubmit,
  error,
}: {
  username: string;
  setUsername: (value: string) => void;
  password: string;
  setPassword: (value: string) => void;
  onSubmit: (event: React.FormEvent<HTMLFormElement>) => void;
  error: string;
}) {
  return (
    <section className="survey-card survey-admin-login">
      <div className="survey-admin-lock">
        <LockKeyhole size={21} />
      </div>
      <h2>Masuk ke analisis UAT</h2>
      <p>Masukkan username dan password admin untuk melihat jawaban dan ringkasan kuesioner.</p>
      <form onSubmit={onSubmit}>
        <label className="survey-field">
          Username
          <input
            type="text"
            autoComplete="username"
            value={username}
            onChange={event => setUsername(event.target.value)}
            required
          />
        </label>
        <label className="survey-field">
          Password
          <input
            type="password"
            autoComplete="current-password"
            value={password}
            onChange={event => setPassword(event.target.value)}
            required
          />
        </label>
        <button className="survey-button primary" type="submit">
          Buka analisis <LockKeyhole size={15} />
        </button>
      </form>
      {error && <div className="survey-alert error" role="alert">{error}</div>}
    </section>
  );
}

export function SurveyAdminPage() {
  const { schema } = useSurveySchema();
  const [username, setUsername] = useState('admin');
  const [password, setPassword] = useState('');
  const [credentials, setCredentials] = useState<{ username: string; password: string } | null>(null);
  const [summary, setSummary] = useState<SurveySummary | null>(null);
  const [responses, setResponses] = useState<SurveyResponse[]>([]);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  const fetchAdminData = () => {
    if (!credentials) return;
    setLoading(true);
    setError('');
    const headers = { Authorization: basicAuthorization(credentials.username, credentials.password) };
    Promise.all([
      fetch(`${API}/admin/summary`, { headers }),
      fetch(`${API}/admin/responses?limit=500`, { headers }),
    ])
      .then(async ([summaryResponse, responseResponse]) => {
        if (summaryResponse.status === 401 || responseResponse.status === 401) {
          throw new Error('Username atau password salah.');
        }
        if (!summaryResponse.ok || !responseResponse.ok) {
          throw new Error('Data respons belum dapat dimuat.');
        }
        return Promise.all([summaryResponse.json(), responseResponse.json()]);
      })
      .then(([summaryData, responseData]) => {
        setSummary(summaryData);
        setResponses(responseData.items);
      })
      .catch(reason => {
        setSummary(null);
        setError(reason.message || 'Tidak dapat menghubungi backend.');
      })
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    if (credentials) fetchAdminData();
  }, [credentials]);

  function signIn(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError('');
    setCredentials({ username: username.trim(), password });
  }

  function signOut() {
    setCredentials(null);
    setPassword('');
    setSummary(null);
    setResponses([]);
  }

  return (
    <div className="survey-page survey-admin-page">
      <PageIntro
        eyebrow="PANEL ADMIN · UAT"
        title="Analisis Kuesioner"
        text="Ringkasan penilaian dan jawaban pengguna EWS IHSG."
        icon={<BarChart3 size={22} />}
      />

      {!credentials && (
        <AdminLogin
          username={username}
          setUsername={setUsername}
          password={password}
          setPassword={setPassword}
          onSubmit={signIn}
          error={error}
        />
      )}

      {credentials && schema && (
        <>
          <div className="survey-admin-toolbar">
            <span>
              <ShieldCheck size={15} /> Sesi Admin Aktif
            </span>
            <button className="survey-button text" onClick={signOut}>
              Keluar
            </button>
          </div>
          {error && <div className="survey-alert error" role="alert">{error}</div>}
          <GFormSurveyAnalytics
            schema={schema}
            summary={summary}
            responses={responses}
            onRefresh={fetchAdminData}
            loading={loading}
          />
        </>
      )}
    </div>
  );
}
