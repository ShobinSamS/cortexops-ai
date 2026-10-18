import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { Upload, Search, RotateCw, Trash2, ChevronRight, FileText } from 'lucide-react';
import { api, type Evidence, useAuth } from '@/lib/api';
import { Badge, Panel, Empty, PageTitle, ErrorBox, Loading } from '@/components/common';
import { date } from '@/lib/utils';

export function EvidenceCard({ evidence }: { evidence: Evidence }) {
  return <article className="evidence-card"><div><span className="subtle-tag">{evidence.source}</span><strong>{evidence.title}</strong>{(evidence.reference?.page > 0 || evidence.reference?.section) && <small>{evidence.reference.page > 0 ? `Page ${evidence.reference.page} · ` : ''}{evidence.reference.section}</small>}</div><p>{evidence.content}</p><details><summary>Source provenance <ChevronRight size={12}/></summary><pre className="json">{JSON.stringify({ id: evidence.id, ...evidence.reference }, null, 2)}</pre></details></article>;
}

export function Knowledge() {
  const cache = useQueryClient(); const canWrite = useAuth(s => s.user?.role !== 'viewer');
  const [filterDocument, setFilterDocument] = useState('');
  const [documentQuery, setDocumentQuery] = useState(''); const [documentStatus, setDocumentStatus] = useState('all');
  const [selected, setSelected] = useState<string | null>(null); const [query, setQuery] = useState(''); const [jobId, setJobId] = useState<string | null>(null);
  const docs = useQuery({ queryKey: ['documents'], queryFn: () => api<any[]>('/documents'), refetchInterval: 3000 });
  const chunks = useQuery({ queryKey: ['chunks', selected], queryFn: () => api<any[]>(`/documents/${selected}/chunks`), enabled: !!selected });
  const job = useQuery({ queryKey: ['job', jobId], queryFn: () => api(`/jobs/${jobId}`), enabled: !!jobId, refetchInterval: q => ['completed', 'failed'].includes(q.state.data?.status) ? false : 1000 });
  const upload = useMutation({ mutationFn: (file: File) => { const form = new FormData(); form.append('file', file); return api('/documents', { method: 'POST', body: form }); }, onSuccess: () => cache.invalidateQueries({ queryKey: ['documents'] }) });
  const action = useMutation({ mutationFn: ({ id, method }: { id: string; method: 'POST' | 'DELETE' }) => api(`/documents/${id}${method === 'POST' ? '/reindex' : ''}`, { method }), onSuccess: () => cache.invalidateQueries({ queryKey: ['documents'] }) });
  const search = useMutation({ mutationFn: () => api('/knowledge/search', { method: 'POST', body: JSON.stringify({ query, limit: 6, document_ids: filterDocument ? [filterDocument] : [] }) }), onSuccess: data => setJobId(data.job_id) });
  const visibleDocuments = (docs.data ?? []).filter(d => d.filename.toLowerCase().includes(documentQuery.trim().toLowerCase()) && (documentStatus === 'all' || d.status === documentStatus));

  return <>
    <PageTitle title="Knowledge base" description="Give every investigation a reliable source of context." action={<label className="button primary upload-label"><Upload size={16}/>{upload.isPending ? 'Uploading…' : 'Upload document'}<input type="file" accept=".pdf,.txt,.md,.docx" disabled={!canWrite || upload.isPending} onChange={e => { if (e.target.files?.[0]) upload.mutate(e.target.files[0]); e.target.value = ''; }}/></label>}/>
    <ErrorBox error={docs.error || upload.error || action.error}/>
    {upload.isSuccess && <div className="notice">{upload.data.duplicate ? 'This document is already in your workspace.' : 'Upload saved. The worker will parse and index it shortly.'}</div>}
    <div className="knowledge-grid">
      <Panel title="Workspace documents" subtitle="PDF, TXT, Markdown and DOCX · up to 20 MB">
        {docs.isPending ? <Loading/> : docs.data?.length ? <>
          <div className="document-filters">
            <input aria-label="Find documents by filename" placeholder="Find a document…" value={documentQuery} onChange={e => setDocumentQuery(e.target.value)}/>
            <select aria-label="Filter documents by status" value={documentStatus} onChange={e => setDocumentStatus(e.target.value)}>
              <option value="all">All statuses</option><option value="queued">Queued</option><option value="processing">Processing</option><option value="indexed">Indexed</option><option value="failed">Failed</option><option value="deleting">Deleting</option>
            </select>
            <small>{visibleDocuments.length} of {docs.data.length} documents</small>
          </div>
          {visibleDocuments.length ? <div className="document-list">{visibleDocuments.map(d => <article key={d.id} className={selected === d.id ? 'selected' : ''}>
            <button className="document-main" onClick={() => setSelected(selected === d.id ? null : d.id)}><FileText size={21}/><span><strong>{d.filename}</strong><small>{Math.ceil(d.size_bytes / 1024)} KB · {date(d.created_at)}</small>{d.error && <small className="error-text">{d.error}</small>}</span></button>
            <Badge status={d.status}/><div className="document-actions">
              <button aria-label={`Reindex ${d.filename}`} title="Reindex" disabled={!canWrite || ['queued', 'processing', 'deleting'].includes(d.status)} onClick={() => action.mutate({ id: d.id, method: 'POST' })}><RotateCw size={14}/></button>
              <button aria-label={`Delete ${d.filename}`} title="Delete document" disabled={!canWrite || d.status === 'deleting'} onClick={() => { if (window.confirm(`Delete ${d.filename} and its indexed chunks?`)) action.mutate({ id: d.id, method: 'DELETE' }); }}><Trash2 size={14}/></button>
            </div>
          </article>)}</div> : <Empty title="No documents match">Try another filename or status filter.</Empty>}
        </> : <Empty title="Build your evidence library">Upload runbooks, release notes and model documentation. The worker processes them in the background.</Empty>}
      </Panel>
      <Panel title="Test retrieval" subtitle="Dense + sparse search, followed by cross-encoder reranking">
        <form className="prose" onSubmit={e => { e.preventDefault(); search.mutate(); }}>
          <label>Document filter<select aria-label="Document filter" value={filterDocument} onChange={e => setFilterDocument(e.target.value)}><option value="">All indexed documents</option>{docs.data?.filter(d => d.status === 'indexed').map(d => <option key={d.id} value={d.id}>{d.filename}</option>)}</select></label>
          <label>Search your knowledge<input value={query} onChange={e => setQuery(e.target.value)} placeholder="What changed in document preprocessing?" minLength={2} required/></label>
          <button className="button secondary" disabled={search.isPending || job.data?.status === 'running' || job.data?.status === 'queued'}><Search size={15}/>Search evidence</button>
          <ErrorBox error={search.error || job.error || job.data?.error}/>
          {jobId && job.data && !['completed', 'failed'].includes(job.data.status) && <p>Search {job.data.status} — embeddings and reranking run in the worker.</p>}
          {job.data?.status === 'completed' && <small>{job.data.result.evidence.length} cited results returned.</small>}
        </form>
      </Panel>
    </div>
    {selected && <Panel title="Chunk inspector" subtitle="Stable chunk IDs, extracted text and page/section references">{chunks.isPending ? <Loading/> : chunks.data?.length ? <div className="evidence-list">{chunks.data.map(c => <EvidenceCard key={c.id} evidence={{ id: c.id, source: 'knowledge', title: `Chunk ${c.position + 1}`, content: c.content, reference: { page: c.page, section: c.section, document_id: c.document_id, ...c.metadata_json } }}/>)}</div> : <Empty title="No indexed chunks yet">Chunk text appears after ingestion completes.</Empty>}</Panel>}
    {job.data?.status === 'completed' && <Panel title="Retrieved evidence" subtitle="Inspect the sources before using them in an investigation">{job.data.result.evidence.length ? <div className="evidence-list">{job.data.result.evidence.map((e: Evidence) => <EvidenceCard key={e.id} evidence={e}/>)}</div> : <Empty title="No matching indexed evidence">Try another query or wait for document processing.</Empty>}</Panel>}
  </>;
}
