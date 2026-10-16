import { defineConfig } from '@playwright/test';
process.env.PLAYWRIGHT_BROWSERS_PATH ||= new URL('../.cache/ms-playwright', import.meta.url).pathname.replace(/^\/(\w:)/, '$1');
export default defineConfig({ testDir: './tests', timeout: 60000, use: { baseURL: process.env.E2E_BASE_URL || 'http://127.0.0.1:5173', viewport: { width: 1440, height: 1000 }, trace: 'retain-on-failure' }, reporter: [['list']], outputDir: 'test-results' });
