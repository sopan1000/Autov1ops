# Chaos scripts

Each script does two things:

1. **If a live `kubectl` context is configured** (i.e. you've deployed
   `sandbox/` to a real GKE cluster), it mutates the real deployment the
   same way a human mistake would - a bad image tag, a leaky config, etc.
   That's what makes Cloud Monitoring fire a real alert.
2. **Always**, it also calls `POST /alerts` on the agent directly, so the
   scenario runs immediately even with no cluster at all. This is what
   the hackathon demo actually uses day-to-day - it's faster and doesn't
   depend on a live GCP project being up during a demo.

Usage:
```bash
export AGENT_URL=http://localhost:8000   # or your Cloud Run URL
./bad_deploy.sh
./oom_leak.sh
./db_exhaustion.sh
./bad_config.sh
```

Run `../../scripts/demo.sh` to fire all four in sequence with pauses,
scripted for a live walkthrough.
