import { defineConfig } from 'vite';

export default defineConfig({
  // relative asset paths, so the site works from any folder (GitHub Pages project sites too)
  base: './',
  worker: { format: 'es' },
});
