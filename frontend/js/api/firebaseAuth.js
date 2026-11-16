// Firebase Authentication helpers. Dynamically imported by client.js only when USE_MOCK is false.
import { auth, isConfigured, createUserWithEmailAndPassword, signInWithEmailAndPassword, updateProfile, GoogleAuthProvider, signInWithPopup, signOut, onAuthStateChanged } from '../firebase.js';

const BAD_CONFIG = 'Firebase is not configured correctly. Check the config values in js/firebase.js.';
const MSG = {
    'auth/invalid-email': 'Enter a valid email address.',
    'auth/missing-email': 'Enter your email address.',
    'auth/weak-password': 'Password is too weak. Use at least 6 characters.',
    'auth/missing-password': 'Enter your password.',
    'auth/email-already-in-use': 'An account with this email already exists. Try logging in instead.',
    'auth/invalid-credential': 'Incorrect email or password.',
    'auth/invalid-login-credentials': 'Incorrect email or password.',
    'auth/user-not-found': 'Incorrect email or password.',
    'auth/wrong-password': 'Incorrect email or password.',
    'auth/user-disabled': 'This account has been disabled.',
    'auth/too-many-requests': 'Too many attempts. Please wait a moment and try again.',
    'auth/popup-closed-by-user': 'Google sign-in was cancelled.',
    'auth/cancelled-popup-request': 'Google sign-in was cancelled.',
    'auth/popup-blocked': 'Your browser blocked the Google sign-in popup. Allow popups for this site and try again.',
    'auth/account-exists-with-different-credential': 'An account already exists with this email using a different sign-in method.',
    'auth/network-request-failed': 'Network error. Check your internet connection and try again.',
    'auth/operation-not-allowed': 'This sign-in method is not enabled in Firebase Console.',
    'auth/unauthorized-domain': 'This address is not authorized in Firebase. Open the app at http://localhost:5500 or add the domain under Authentication > Settings > Authorized domains.',
    'auth/invalid-api-key': BAD_CONFIG, 'auth/api-key-not-valid.-please-pass-a-valid-api-key.': BAD_CONFIG, 'auth/configuration-not-found': BAD_CONFIG, 'auth/app-not-authorized': BAD_CONFIG
};
export const friendly = e => {
    const m = MSG[e?.code] || (e?.code ? `Authentication failed (${e.code}).` : (e?.message || 'Authentication failed.'));
    return Object.assign(new Error(m), { code: e?.code });
};
const need = () => { if (!isConfigured) throw Object.assign(new Error('Firebase is not configured yet. Paste your web app config into js/firebase.js.'), { code: 'taim/not-configured' }) };
const wrap = async fn => { try { need(); return await fn() } catch (e) { throw e?.code === 'taim/not-configured' ? e : friendly(e) } };

// Same user shape the frontend already uses: {id,name,email,program}
const toUser = (u, program = '') => ({ id: u.uid, name: u.displayName || (u.email || '').split('@')[0] || 'Student', email: u.email || '', program });
const result = async (u, program) => ({ token: await u.getIdToken(), user: toUser(u, program), raw: u });

export const register = ({ name, email, password, program }) => wrap(async () => {
    const { user } = await createUserWithEmailAndPassword(auth, (email || '').trim(), password || '');
    try { await updateProfile(user, { displayName: (name || '').trim() }) } catch (e) { console.warn('Could not set display name:', e) }
    return result(user, (program || '').trim());
});
export const login = (email, password) => wrap(async () => {
    const { user } = await signInWithEmailAndPassword(auth, (email || '').trim(), password || '');
    return result(user);
});
export const google = () => wrap(async () => {
    const p = new GoogleAuthProvider(); p.setCustomParameters({ prompt: 'select_account' });
    const { user } = await signInWithPopup(auth, p);
    return result(user);
});
export const logout = () => wrap(() => signOut(auth));
// getIdToken() returns the cached token while valid and silently refreshes it when it is about to expire.
export const getIdToken = () => wrap(async () => auth.currentUser ? auth.currentUser.getIdToken() : null);
export const onChange = (cb, onError) => onAuthStateChanged(auth, cb, onError);