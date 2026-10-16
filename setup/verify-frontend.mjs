import { build } from '../frontend/node_modules/vite/dist/node/index.js';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const root = fileURLToPath(new URL('../frontend/', import.meta.url));
process.env.PLAYWRIGHT_BROWSERS_PATH = path.resolve(root, '../.cache/ms-playwright');
const { chromium } = await import('../frontend/node_modules/playwright/index.mjs');
const id = '\0cortexops-environment.tsx';
await build({
  root,
  configFile: false,
  logLevel: 'warn',
  plugins: [{
    name: 'environment-smoke',
    resolveId(source) { if (source === id) return id; },
    load(source) {
      if (source === id) return `
        import React from 'react';
        import { createRoot } from 'react-dom/client';
        import { BrowserRouter } from 'react-router-dom';
        import { QueryClient } from '@tanstack/react-query';
        import { create } from 'zustand';
        import { ReactFlow } from '@xyflow/react';
        import { LineChart } from 'recharts';
        import { Activity } from 'lucide-react';
        import { Slot } from '@radix-ui/react-slot';
        import { cva } from 'class-variance-authority';
        import clsx from 'clsx';
        import { twMerge } from 'tailwind-merge';
        console.log(React, createRoot, BrowserRouter, new QueryClient(), create, ReactFlow, LineChart, Activity, Slot, cva, clsx, twMerge);
      `;
    }
  }],
  build: {
    write: false,
    rollupOptions: {
      input: id,
      onwarn(warning, warn) {
        // Client directives have no effect in this browser-only dependency probe.
        if (warning.code === 'MODULE_LEVEL_DIRECTIVE' && warning.message.includes('use client')) return;
        warn(warning);
      },
    },
    minify: false,
  },
});
console.log('PASS Vite production bundle with frontend runtime dependencies');
const browser = await chromium.launch({ headless: true });
try {
  const page = await browser.newPage();
  await page.setContent('<button id="probe">Ready</button><output id="result"></output><script>document.querySelector("button").onclick=()=>document.querySelector("output").textContent="clicked";</script>');
  await page.locator('#probe').click();
  if (await page.locator('#result').textContent() !== 'clicked') throw new Error('Browser interaction failed');
  console.log('PASS Playwright Chromium launch and browser interaction');
} finally {
  await browser.close();
}
