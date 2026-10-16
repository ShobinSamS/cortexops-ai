import { useEffect, useMemo, useRef, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { ReactFlow, Background, Controls, Handle, Position, MarkerType, type Node, type NodeProps } from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import { api, useAuth, refreshSession } from '@/lib/api';
import { Badge, Empty, ErrorBox, Panel } from './common';
import { date } from '@/lib/utils';

type Agent = Node<{ name: string; status: string }, 'agent'>;
function AgentNode({ data }: NodeProps<Agent>) { return <div className={`agent-node ${data.status}`}><Handle type="target" position={Position.Left}/><strong>{data.name.replaceAll('_', ' ')}</strong><div style={{ marginTop: 8 }}><Badge status={data.status}/></div><Handle type="source" position={Position.Right}/></div>; }
const nodeTypes = { agent: AgentNode };
const names = ['supervisor', 'planner', 'retrieval', 'data_analysis', 'code_investigation', 'monitoring', 'diagnosis', 'evidence_validation', 'reporting'];

export function Execution({ id, status }: { id: string; status: string }) {
  const cache = useQueryClient(); const token = useAuth(s => s.token); const [connected, setConnected] = useState(false); const cursor = useRef(0);
  const active = ['queued', 'running', 'paused', 'waiting_approval'].includes(status);
  const steps = useQuery({ queryKey: ['steps', id], queryFn: () => api(`/investigations/${id}/steps`), refetchInterval: active ? 3000 : false });
  const events = useQuery({ queryKey: ['events', id], queryFn: () => api<any[]>(`/investigations/${id}/events`), refetchInterval: active ? 5000 : false });
  const tools = useQuery({ queryKey: ['investigation-tools', id], queryFn: () => api<any[]>(`/investigations/${id}/tools`), refetchInterval: active ? 4000 : false });
  useEffect(() => {
    cursor.current = Math.max(cursor.current, ...(events.data || []).map(x => x.sequence), 0);
  }, [events.data]);
  useEffect(() => {
    if (!active || !token) return;
    let socket: WebSocket; let retry: ReturnType<typeof setTimeout> | undefined; let stopped = false;
    function connect() {
      socket = new WebSocket(`${location.protocol === 'https:' ? 'wss:' : 'ws:'}//${location.host}/api/v1/ws/investigations/${id}`);
      socket.onopen = () => { setConnected(true); socket.send(JSON.stringify({ token: useAuth.getState().token, after: cursor.current })); };
      socket.onmessage = event => {
        const data = JSON.parse(event.data);
        if (data.type === 'event') {
          cursor.current = Math.max(cursor.current, data.sequence);
          cache.setQueryData<any[]>(['events', id], old => [...(old || []).filter(x => x.sequence !== data.sequence), data].sort((a, b) => a.sequence - b.sequence));
          cache.invalidateQueries({ queryKey: ['steps', id] });
          cache.invalidateQueries({ queryKey: ['investigation', id] });
          cache.invalidateQueries({ queryKey: ['investigation-tools', id] });
          if (data.kind === 'investigation.completed') cache.invalidateQueries({ queryKey: ['reports'] });
        }
      };
      socket.onclose = async event => {
        setConnected(false);
        if (!stopped && event.code !== 1000) {
          if (event.code === 4401) await refreshSession();
          if (!stopped) retry = setTimeout(connect, 1500);
        }
      };
    }
    connect();
    return () => { stopped = true; clearTimeout(retry); socket?.close(); setConnected(false); };
  }, [id, active, token, cache]);
  const nodes = useMemo<Agent[]>(() => names.map((name, i) => ({ id: name, type: 'agent', position: { x: (i % 3) * 245, y: Math.floor(i / 3) * 130 }, data: { name, status: steps.data?.steps.find((s: any) => s.agent === name)?.status || 'pending' } })), [steps.data]);
  const edges = useMemo(() => names.slice(0, -1).map((name, i) => ({ id: `${name}-${names[i + 1]}`, source: name, target: names[i + 1], animated: nodes[i]?.data.status === 'running', markerEnd: { type: MarkerType.ArrowClosed, color: '#6b9474' }, style: { stroke: nodes[i]?.data.status === 'completed' ? '#759f70' : '#34464e' } })), [nodes]);
  return <><div className="live-layout"><Panel title="Agent execution graph" subtitle="States reflect recorded backend execution" action={<span className="live-dot">{connected ? 'Live socket connected' : active ? 'Reconnecting / polling' : 'Recorded execution'}</span>}><div className="flow-chart"><ReactFlow nodes={nodes} edges={edges} nodeTypes={nodeTypes} fitView nodesConnectable={false} nodesDraggable={false} colorMode="dark"><Background color="#273a42" gap={22}/><Controls showInteractive={false}/></ReactFlow></div></Panel><Panel title="Execution timeline" subtitle="Persisted events replay after reconnect"><ErrorBox error={events.error}/><div className="event-list">{events.data?.length ? [...events.data].reverse().map(e => <div key={e.sequence} className="event-row"><strong>{e.agent?.replaceAll('_', ' ') || 'Investigation'}</strong> <Badge status={e.kind.split('.').at(-1) || 'pending'}/><small>#{e.sequence} · {date(e.created_at)}{e.data?.duration_ms != null ? ` · ${Math.round(e.data.duration_ms)} ms` : ''}</small>{e.data?.error && <p className="error-text">{e.data.error}</p>}</div>) : <Empty title="Waiting for execution events">Start an investigation to follow its progress.</Empty>}</div></Panel></div><Panel title="Agent attempts" subtitle="Actual duration, local model calls and reported token usage"><div className="table-wrap"><table><thead><tr><th>Agent</th><th>Status</th><th>Duration</th><th>LLM calls</th><th>Input / output tokens</th></tr></thead><tbody>{steps.data?.executions.map((x: any) => <tr key={x.id}><td>{x.agent.replaceAll('_', ' ')}</td><td><Badge status={x.status}/></td><td>{x.duration_ms == null ? '—' : `${(x.duration_ms / 1000).toFixed(1)}s`}</td><td>{x.llm_calls}</td><td>{x.input_tokens} / {x.output_tokens}</td></tr>)}</tbody></table></div></Panel><Panel title="Tool calls and results" subtitle="Inspect the inputs and evidence gathered by each specialist"><div className="execution-list">{tools.data?.length ? tools.data.map(t => <details key={t.id}><summary><span>{t.server} / {t.tool}</span><Badge status={t.status}/></summary><pre className="json">{JSON.stringify({ arguments: t.arguments, result: t.result, error: t.error }, null, 2)}</pre></details>) : <Empty title="No tool calls yet">Read operations appear here as the agents collect evidence.</Empty>}</div></Panel></>;
}
