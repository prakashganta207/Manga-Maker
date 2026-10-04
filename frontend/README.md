# Frontend (Next.js + TypeScript + Tailwind)

Pages:
- `/` — story input form (shows which AI providers the backend is using)
- `/jobs/[id]` — live progress per pipeline stage, then the manga reader
  (right-to-left toggle, page navigation with arrow keys, PNG/PDF downloads, character sheets)

The backend URL comes from `NEXT_PUBLIC_API_URL` (default `http://localhost:8000`).

```bash
npm install
npm run dev     # http://localhost:3000
npm run build && npm start
```

See the main [README](../README.md) for the full setup.
