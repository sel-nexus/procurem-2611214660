import { defineConfig } from 'vitest/config';
export default defineConfig({ esbuild: { jsx: 'automatic' }, test: { include:['components/**/*.test.tsx', 'app/**/*.test.tsx', 'lib/**/*.test.ts'], pool:'forks', poolOptions:{forks:{singleFork:true}} } });
