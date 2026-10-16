import { useState } from 'react';
import { Network, ArrowRight, ShieldCheck } from 'lucide-react';
import { api, useAuth } from '@/lib/api';
import { ErrorBox } from '@/components/common';
import { Button } from '@/components/ui/button';
export function Auth() {
  const [register, setRegister] = useState(false); const [busy, setBusy] = useState(false); const [error, setError] = useState<unknown>();
  async function submit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault(); setBusy(true); setError(null);
    const fields = Object.fromEntries(new FormData(e.currentTarget));
    try { const data = await api(`/auth/${register ? 'register' : 'login'}`, { method: 'POST', body: JSON.stringify(fields) }); useAuth.getState().set(data.access_token, data.user); }
    catch (err) { setError(err); } finally { setBusy(false); }
  }
  return <div className="auth-page"><div className="auth-story"><div className="brand"><span className="brand-mark"><Network/></span><span>CortexOps<span className="brand-ai"> AI</span></span></div><div><span className="eyebrow">ENTERPRISE INTELLIGENCE, EXPLAINED.</span><h1>From scattered signals<br/>to a clearer picture.</h1><p>Investigate what changed. Follow the evidence.<br/>Make the next decision with confidence.</p><div className="signal-art"><div/><div/><div/><Network size={66}/></div></div><small><ShieldCheck size={16}/> Local models. Your infrastructure. Your evidence.</small></div><div className="auth-form"><div className="auth-form-inner"><span className="eyebrow">YOUR INVESTIGATION STARTS HERE</span><h2>{register ? 'Create your workspace' : 'Welcome back'}</h2><p>{register ? 'Set up a private space for your team’s investigations.' : 'Sign in to your CortexOps workspace.'}</p><form onSubmit={submit}>{register && <><label>Your name<input name="name" autoComplete="name" required maxLength={100}/></label><label>Workspace name<input name="workspace_name" required defaultValue="Operations intelligence" maxLength={100}/></label></>}<label>Email address<input name="email" type="email" autoComplete="email" required/></label><label>Password<input name="password" type="password" autoComplete={register ? 'new-password' : 'current-password'} minLength={register ? 12 : 1} maxLength={128} required/></label>{register && <small>Use at least 12 characters.</small>}<ErrorBox error={error}/><Button className="button primary" disabled={busy}>{busy ? 'Connecting…' : register ? 'Create workspace' : 'Sign in'}<ArrowRight size={17}/></Button></form><p className="auth-switch">{register ? 'Already have an account?' : 'New to CortexOps?'} <button onClick={() => { setRegister(!register); setError(null); }}>{register ? 'Sign in' : 'Create a workspace'}</button></p></div></div></div>;
}
