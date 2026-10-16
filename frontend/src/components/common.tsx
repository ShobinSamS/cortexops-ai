import type { ReactNode } from 'react';
import { LoaderCircle, ArrowUpRight, SearchX } from 'lucide-react';
import { cn } from '@/lib/utils';
export function Badge({ children, status }: { children?: ReactNode; status: string }) { return <span className={cn('badge', status)}><i/>{children || status.replaceAll('_', ' ')}</span>; }
export function Panel({ children, title, subtitle, action, className }: { children: ReactNode; title?: string; subtitle?: string; action?: ReactNode; className?: string }) { return <section className={cn('panel', className)}>{title && <header className="panel-head"><div><h2>{title}</h2>{subtitle && <p>{subtitle}</p>}</div>{action}</header>}{children}</section>; }
export function Empty({ title, children }: { title: string; children?: ReactNode }) { return <div className="empty"><SearchX size={28}/><h3>{title}</h3><p>{children}</p></div>; }
export function Loading() { return <div className="empty"><LoaderCircle className="spin"/><p>Loading workspace…</p></div>; }
export function ErrorBox({ error }: { error: unknown }) { return error ? <div role="alert" className="error">{error instanceof Error ? error.message : String(error)}</div> : null; }
export function PageTitle({ eyebrow, title, description, action }: { eyebrow?: string; title: string; description: string; action?: ReactNode }) { return <div className="page-title"><div><span className="eyebrow">{eyebrow || 'CORTEXOPS WORKSPACE'}</span><h1>{title}</h1><p>{description}</p></div>{action}</div>; }
export function Metric({ label, value, hint, icon }: { label: string; value: string | number; hint: string; icon: ReactNode }) { return <div className="metric"><div className="metric-top"><span>{label}</span>{icon}</div><strong>{value}</strong><small>{hint}</small></div>; }
export { ArrowUpRight };
