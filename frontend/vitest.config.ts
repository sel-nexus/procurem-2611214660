import { defineConfig } from 'vitest/config';
export default defineConfig({ esbuild: { jsx: 'automatic' }, test: { include:['components/**/*.test.tsx'], pool:'forks', poolOptions:{forks:{singleFork:true}} } });
