import { useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { useQuery, useMutation } from '@tanstack/react-query';
import { ArrowUpRight, Download, ShieldCheck } from 'lucide-react';
import { api, download, type Evidence, useAuth } from '@/lib/api';
import { Panel, PageTitle, Empty, ErrorBox, Loading, Badge } from '@/components/common';
import { EvidenceCard } from './Knowledge';
import { date } from '@/lib/utils';

export function Reports() {
  const q = useQuery({ queryKey: ['reports'], queryFn: () => api<any[]>('/reports'), refetchInterval: 5000 });
  return <><PageTitle title="Investigation reports" description="Verified observations, traceable hypotheses, and clear next steps."/><Panel title="Report library" subtitle="Built from recorded evidence, preserved across restarts">{q.isPending ? <Loading/> : q.error ? <ErrorBox error={q.error}/> : q.data?.length ? <div className="report-list">{q.data.map(r => <article key={r.id}><div><Link to={`/reports/${r.id}`}><strong>{r.title}</strong></Link><small>Generated {date(r.created_at)}</small></div><Link className="button secondary" to={`/reports/${r.id}`}>Review report<ArrowUpRight size={14}/></Link></article>)}</div> : <Empty title="Your first report starts with an investigation">Completed investigations produce a report here.</Empty>}</Panel></>;
}

export function ReportDetail({ reportId }: { reportId?: string }) {
  const params = useParams(); const id = reportId || params.id; const [exportError, setExportError] = useState<unknown>(); const user = useAuth(s => s.user);
  const q = useQuery({ queryKey: ['report', id], queryFn: () => api(`/reports/${id}`), enabled: !!id });
  const action = useMutation({ mutationFn: () => api('/mcp/tools/invoke', { method: 'POST', body: JSON.stringify({ server: 'github', tool: 'create_issue', investigation_id: q.data.investigation_id,
    arguments: { title: q.data.title.slice(0, 160), body: `${q.data.content.summary}\n\nRecommended validation:\n${q.data.content.recommendations.map((x: string) => '- ' + x).join('\n')}\n\nCortexOps report: ${id}\nEvidence IDs: ${q.data.content.evidence.map((e: Evidence) => e.id).join(', ')}`.slice(0, 8000) } }) }) });
  if (q.isPending) return <Loading/>; if (q.error) return <ErrorBox error={q.error}/>;
  const r = q.data; const c = r.content;
  async function exportReport(format: string) { try { await download(`/reports/${id}/export?format=${format}`, `cortexops-${id}.${format}`); } catch (e) { setExportError(e); } }
  return <><PageTitle eyebrow="EVIDENCE-BACKED INVESTIGATION REPORT" title={r.title} description={`Generated ${date(r.created_at)} · ${c.evidence.length} evidence records`} action={<div className="form-actions"><button className="button secondary" onClick={() => exportReport('md')}><Download size={15}/>Markdown</button><button className="button primary" onClick={() => exportReport('pdf')}><Download size={15}/>Export PDF</button></div>}/><ErrorBox error={exportError}/><Panel title="Working explanation" subtitle="A synthesized explanation to validate against the sources"><div className="prose"><p>{c.summary}</p><Link className="text-link" to={`/investigations/${r.investigation_id}`}>Inspect original execution<ArrowUpRight size={14}/></Link></div></Panel><Panel title="Verified observations" subtitle="Deterministic calculations from recorded tool results"><div className="report-section">{c.verified_findings.length ? c.verified_findings.map((f: any, i: number) => <Finding key={i} value={f}/>) : <p>No numerical observation could be independently verified from the selected sources.</p>}</div></Panel><Panel title="Root-cause hypotheses" subtitle="Supporting and contradictory evidence; causal proof requires reproduction"><div className="report-section">{c.hypotheses.length ? c.hypotheses.map((f: any, i: number) => <Finding key={i} value={f}/>) : <p>No model hypothesis passed citation validation. Review the sources below.</p>}</div></Panel><div className="dashboard-grid"><Panel title="Recommended actions" subtitle="Suggestions only; this investigation has not changed external systems"><div className="report-section"><ul>{c.recommendations.map((x: string, i: number) => <li key={i}>{x}</li>)}</ul><button className="button secondary" disabled={action.isPending || user?.role === 'viewer'} onClick={() => action.mutate()}><ShieldCheck size={15}/>Request follow-up issue</button><small>Synthetic mode creates a local incident after approval. Live GitHub requires an operator-configured connection.</small><ErrorBox error={action.error}/>{action.isSuccess && <div className="notice">Approval requested. <Link to="/approvals">Review the exact action in Approvals.</Link></div>}</div></Panel><Panel title="Limitations and uncertainty"><div className="report-section"><ul>{c.limitations.map((x: string, i: number) => <li key={i}>{x}</li>)}</ul></div></Panel></div><Panel title="Source evidence" subtitle="Original tool/chunk outputs with recorded provenance"><div className="evidence-list">{c.evidence.map((e: Evidence) => <div id={`evidence-${encodeURIComponent(e.id)}`} key={e.id}><EvidenceCard evidence={e}/></div>)}</div></Panel></>;
}

function Finding({ value }: { value: any }) { return <article className="finding"><div className="tag-list"><Badge status={value.classification === 'verified' ? 'completed' : 'pending'}>{value.classification}</Badge><span>{value.confidence} confidence</span></div><h3>{value.statement}</h3><div className="citation-links">{value.evidence_ids.map((id: string, i: number) => <a key={id} href={`#evidence-${encodeURIComponent(id)}`}>Source {i + 1} · {id.slice(0, 18)}…</a>)}</div>{value.contradictory_evidence_ids?.length > 0 && <p>Contradictory/context sources: {value.contradictory_evidence_ids.join(', ')}</p>}</article>; }

export function InvestigationReport({ investigationId }: { investigationId: string }) {
  const q = useQuery({ queryKey: ['reports'], queryFn: () => api<any[]>('/reports') });
  const report = q.data?.find(x => x.investigation_id === investigationId);
  return report ? <Panel title="Investigation report ready" subtitle="Review findings, uncertainty, citations and recommendations"><div className="prose"><Link className="button primary" to={`/reports/${report.id}`}>Open evidence-backed report<ArrowUpRight size={15}/></Link></div></Panel> : null;
}
