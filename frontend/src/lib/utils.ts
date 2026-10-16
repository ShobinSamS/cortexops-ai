import { clsx, type ClassValue } from 'clsx';
import { twMerge } from 'tailwind-merge';
export function cn(...inputs: ClassValue[]) { return twMerge(clsx(inputs)); }
export const date = (value?: string) => value ? new Date(value).toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' }) : '—';
export const duration = (seconds?: number | null) => seconds == null ? '—' : seconds < 60 ? `${Math.round(seconds)}s` : `${Math.round(seconds / 60)}m`;
