# Simple RBAC Model

## Roles

- `admin`: platform owner; manages users and sees all scans.
- `architect`: reviews risk findings and decides accepted/false-positive/request-fix.
- `developer`: uploads service source and sees their own scans.
- `viewer`: reads dashboard only.

## Demo users

Seeded automatically when `SEED_DEMO_USERS=true`.

```text
admin@fundsafe.local / admin123
architect@fundsafe.local / architect123
dev@fundsafe.local / dev123
viewer@fundsafe.local / viewer123
```

## API authorization

- `POST /auth/login`: public
- `GET /me`: authenticated
- `GET/POST /users`: admin only
- `POST /projects`: developer+
- `GET /projects`: authenticated, developer sees own projects
- `POST /scans/upload`: developer+
- `GET /scans`: authenticated, developer sees own scans
- `POST /findings/{id}/review`: architect+
- `GET /dashboard/risk`: authenticated
