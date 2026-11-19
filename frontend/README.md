# Nandi frontend

React 19 + Tailwind 4 (Vite). In production the FastAPI backend serves `dist/`; for development:

```bash
npm install
npm run dev      # http://localhost:5173, proxies /api and /media to the backend on :8000
npm run build    # outputs dist/ (served by the backend)
npm run lint     # oxlint
```

The logo lives in `public/nandi.svg` (also the favicon) and is used through `src/components/Logo.jsx`.
