import { defineConfig } from 'vite';

export default defineConfig({
  // relative asset paths, so the site works from any folder (GitHub Pages project sites too)
  base: './',
  worker: { format: 'es' },
  build: {
    rollupOptions: {
      // the converter, and the "how it works" page (served at /how-it-works/); paths are
      // relative to the project root (this folder)
      input: {
        main: 'index.html',
        how: 'how-it-works/index.html',
      },
    },
  },
});
