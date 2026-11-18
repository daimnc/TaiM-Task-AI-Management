// USE_MOCK=true runs entirely in the browser (localStorage, no backend, no Firebase).
// USE_MOCK=false uses Firebase Authentication and the Flask API at API_BASE.
// MOCK_TODAY pins "today" so the demo data matches the wireframes. It is used ONLY in mock mode and is null in real mode,
// so real mode follows the actual date. Change USE_MOCK only; do not set MOCK_TODAY by hand.
const USE_MOCK = false;
export const CONFIG = { USE_MOCK, API_BASE: 'http://localhost:5000/api', MOCK_TODAY: USE_MOCK ? '2026-11-01' : null, TOKEN_KEY: 'taim_token', USER_KEY: 'taim_user' };
