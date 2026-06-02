# packages/ui

Design tokens + reusable React primitives shared by the `frontend/` PWA.

Consumed as a local npm workspace (see `frontend/package.json` + root
`package.json` workspaces). No runtime dependency on `backend/`.

## Layout

```
ui/
├── package.json
├── tsconfig.json
├── src/
│   ├── index.ts                # barrel export for primitives
│   └── primitives/
│       └── Motion.tsx          # <Motion> helper honoring prefers-reduced-motion
└── tests/
    └── .gitkeep
```

Phase 0 ships tokens + a stub `<Motion>` helper. The full primitive set
(`<Button>`, `<Field>`, `<Sheet>`, `<AccountCard>`, `<WhyBadge>`,
`<OpenInGmailLink>`, `<EmptyState>`, `<Switch>`) lands in Phase 6.

## Rules

- **All motion goes through `<Motion>`** (plan §20.1 amendment of §19.16) —
  raw `motion.div` imports from `framer-motion` outside this package fail
  the lint step.
- Design tokens live in `frontend/src/styles/tokens.css` — a single fixed
  Notion theme (see the repo-root `DESIGN.md`). This package ships
  primitives only and no longer carries its own token sheet.
