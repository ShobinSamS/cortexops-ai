import { lazy, Suspense, useEffect, useState } from 'react';
import { Link, NavLink, Route, Routes, useLocation, useNavigate } from 'react-router-dom';
import { Activity, BookOpen, FlaskConical, LayoutDashboard, Network, Settings, ShieldCheck, LogOut, Menu, ArrowUpRight } from 'lucide-react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { api, refreshSession, useAuth } from '@/lib/api';
import { Auth } from '@/pages/Auth';
import { Loading, ErrorBox } from '@/components/common';

const Dashboard = lazy(() => import('@/pages/Dashboard').then(m => ({ default: m.Dashboard })));
const Investigations = lazy(() => import('@/pages/Investigations').then(m => ({ default: m.Investigations })));
const InvestigationDetail = lazy(() => import('@/pages/Investigations').then(m => ({ default: m.InvestigationDetail })));
const Knowledge = lazy(() => import('@/pages/Knowledge').then(m => ({ default: m.Knowledge })));
const Tools = lazy(() => import('@/pages/Tools').then(m => ({ default: m.Tools })));
const Approvals = lazy(() => import('@/pages/Tools').then(m => ({ default: m.Approvals })));
const Reports = lazy(() => import('@/pages/Reports').then(m => ({ default: m.Reports })));
const ReportDetail = lazy(() => import('@/pages/Reports').then(m => ({ default: m.ReportDetail })));
const Graph = lazy(() => import('@/pages/Graph').then(m => ({ default: m.Graph })));
const SettingsPage = lazy(() => import('@/pages/Settings').then(m => ({ default: m.SettingsPage })));
const navigation = [
  { to: '/', icon: LayoutDashboard, label: 'Overview' },
  { to: '/investigations', icon: FlaskConical, label: 'Investigations' },
  { to: '/knowledge', icon: BookOpen, label: 'Knowledge base' },
  { to: '/graph', icon: Network, label: 'Knowledge graph' },
  { to: '/tools', icon: Activity, label: 'MCP connections' },
  { to: '/approvals', icon: ShieldCheck, label: 'Approvals' },
  { to: '/reports', icon: BookOpen, label: 'Reports' },
  { to: '/settings', icon: Settings, label: 'Settings' },
];

export default function App() {
  const [booting, setBooting] = useState(true); const [open, setOpen] = useState(false);
  const user = useAuth(s => s.user); const cache = useQueryClient(); const location = useLocation(); const navigate = useNavigate();
  const workspaces = useQuery({ queryKey: ['workspaces'], queryFn: () => api<any[]>('/workspaces'), enabled: !!user });
  const switchWorkspace = useMutation({ mutationFn: (id: string) => api('/auth/workspace', { method: 'POST', body: JSON.stringify({ workspace_id: id }) }),
    onSuccess: data => { cache.clear(); useAuth.getState().set(data.access_token, data.user); navigate('/'); } });
  useEffect(() => { refreshSession().finally(() => setBooting(false)); }, []);
  useEffect(() => { setOpen(false); }, [location.pathname]);
  if (booting) return <Loading/>; if (!user) return <Auth/>;
  async function logout() { await api('/auth/logout', { method: 'POST' }).catch(() => {}); useAuth.getState().set(null, null); cache.clear(); }
  return <div className="app-shell">
    <aside className={open ? 'sidebar open' : 'sidebar'}>
      <Link to="/" className="brand"><span className="brand-mark"><Network size={23}/></span><span>CortexOps<span className="brand-ai"> AI</span></span></Link>
      <div className="workspace-label"><span className="workspace-avatar">{user.name.slice(0, 1).toUpperCase()}</span><div><select aria-label="Active workspace" value={user.workspace_id} disabled={switchWorkspace.isPending} onChange={e => switchWorkspace.mutate(e.target.value)}>{workspaces.data?.map(w => <option key={w.id} value={w.id}>{w.name}</option>)}</select><small>{user.role} access</small></div></div>
      <span className="nav-label">WORKSPACE</span>
      <nav>{navigation.map(item => <NavLink key={item.to} to={item.to} end={item.to === '/'}><item.icon size={18}/>{item.label}</NavLink>)}</nav>
      <div className="sidebar-bottom"><div className="local-note"><span className="status-dot"/><div><strong>Local intelligence</strong><small>Open models. Self-hosted.</small></div></div><a href="http://127.0.0.1:8000/docs" target="_blank" rel="noreferrer"><BookOpen size={16}/>API documentation<ArrowUpRight size={14}/></a><button className="profile" onClick={logout} aria-label="Sign out"><span className="profile-avatar">{user.name.slice(0, 2).toUpperCase()}</span><span><strong>{user.name}</strong><small>{user.email}</small></span><LogOut size={16}/></button></div>
    </aside>
    {open && <button className="sidebar-overlay" aria-label="Close navigation" onClick={() => setOpen(false)}/>}
    <div className="main-shell"><header className="topbar"><button className="icon-button mobile-menu" aria-label="Open navigation" onClick={() => setOpen(!open)}><Menu size={20}/></button><div className="breadcrumb">Workspace <span>/</span><strong>{navigation.find(n => n.to === location.pathname)?.label || 'Investigation detail'}</strong></div><div className="topbar-right"><span><Activity size={14}/>Evidence-backed intelligence</span><span className="subtle-tag">LOCAL</span></div></header>
      <main key={user.workspace_id}><ErrorBox error={switchWorkspace.error}/><Suspense fallback={<Loading/>}><Routes>
        <Route path="/" element={<Dashboard/>}/><Route path="/investigations" element={<Investigations/>}/><Route path="/investigations/:id" element={<InvestigationDetail/>}/>
        <Route path="/settings" element={<SettingsPage/>}/><Route path="/knowledge" element={<Knowledge/>}/><Route path="/graph" element={<Graph/>}/><Route path="/tools" element={<Tools/>}/>
        <Route path="/approvals" element={<Approvals/>}/><Route path="/reports" element={<Reports/>}/><Route path="/reports/:id" element={<ReportDetail/>}/>
        <Route path="*" element={<div className="empty"><h1>Page not found</h1><Link to="/">Return to overview</Link></div>}/>
      </Routes></Suspense></main><footer>CORTEXOPS AI <span>Decisions grounded in evidence.</span></footer>
    </div>
  </div>;
}
