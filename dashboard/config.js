// When the dashboard is served by the agent itself (/ui on Cloud Run or
// localhost:8000), call the API on the same origin. When served separately
// (docker-compose nginx on :3000), call the agent on :8000.
// Override by setting window.AUTOOPS_API_URL before this file loads.
const API_URL = window.AUTOOPS_API_URL
  || (location.port === "3000" ? `${location.protocol}//${location.hostname}:8000` : location.origin);
