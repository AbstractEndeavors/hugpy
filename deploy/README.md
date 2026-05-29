# Deploy

Server-side config snapshots so the repo records the deployment contract.
Treat this directory as the source of truth — copy from here to the server,
not the other way around.

## systemd

`systemd/6092_abstractgpt_api.service` — the AbstractGPT API unit. Differs
from the older copy on the server in one important way: every storage path
now points at `/mnt/llm_registry`, the shared LLM registry mount, instead
of the older `/mnt/llm_storage`. This matches `abstract_hugpy`'s
`DEFAULT_ROOT` and the abstractppe registry config.

Install:

```
sudo cp deploy/systemd/6092_abstractgpt_api.service \
    /etc/systemd/system/6092_abstractgpt_api.service
sudo systemctl daemon-reload
sudo systemctl restart 6092_abstractgpt_api.service
```

If `/mnt/llm_registry` doesn't exist yet, bind-mount or symlink it to
wherever the model weights actually live before restarting the unit.

## Frontend builds

The React app picks up two build-time knobs (both wired through
`app/webpack.config.js`):

| Var | Default | Use for |
| --- | --- | --- |
| `API_BASE` | `/api` | Where to send REST calls. Set to `https://api.abstractgpt.ai` for any prod host (the SPA is cross-origin to the API). |
| `PUBLIC_PATH` | `/` | Where `dist/assets/*` is served from. Set to `/app/` for the `llm.abstractgpt.ai/app/` deploy. |

Examples:

```
# abstractgpt.ai (root SPA, prod API)
API_BASE=https://api.abstractgpt.ai npm run build

# llm.abstractgpt.ai/app/
API_BASE=https://api.abstractgpt.ai PUBLIC_PATH=/app/ npm run build

# local dev (webpack devServer proxies /api -> localhost:8000)
npm run dev
```
