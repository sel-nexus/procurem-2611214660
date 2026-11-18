import type { Config } from 'tailwindcss';
const config: Config = {
  content: ['./app/**/*.{ts,tsx}', './components/**/*.{ts,tsx}'],
  theme: { extend: { colors: { page:'#070b14', card:'#0f172a', edge:'#1e293b', raised:'#131c31', ink:'#f1f5f9', body:'#cbd5e1', muted:'#94a3b8', accent:'#2dd4bf', accentInk:'#042f2e', danger:'#fb7185', focus:'#5eead4', input:'#0b1220' }, fontFamily: { sans:['Inter','sans-serif'], display:['Space Grotesk','sans-serif'] } } },
  plugins: [],
};
export default config;
