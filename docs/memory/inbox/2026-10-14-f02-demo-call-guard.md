# F02 demo-call guard

- `POST /demo/call` uses nginx's `X-Real-IP`, never `X-Forwarded-For`; invalid or absent addresses are stored as null and share the Redis `unknown` rate bucket. Source: approved task 003 r3.
- Consent text is versioned server-side in `agent/demo_guard.py`; v1 must never be edited in place because old-page requests are recorded as v1. Source: approved task 003 r3.
- Operators can use Redis `demo:kill` and `demo:config` to disable demo calls or adjust limits without an environment edit. Source: approved task 003 r3.
