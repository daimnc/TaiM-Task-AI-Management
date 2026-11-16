// Firebase initialization (Authentication only). Loaded ONLY when CONFIG.USE_MOCK is false.
// SDK version is set in the two import URLs below. Keep them identical.
import { initializeApp, getApps, getApp } from 'https://www.gstatic.com/firebasejs/12.11.0/firebase-app.js';
import { getAuth, createUserWithEmailAndPassword, signInWithEmailAndPassword, updateProfile, GoogleAuthProvider, signInWithPopup, signOut, onAuthStateChanged } from 'https://www.gstatic.com/firebasejs/12.11.0/firebase-auth.js';

// ===== PASTE YOUR FIREBASE WEB APP CONFIG HERE =====
// Firebase Console > Project settings > General > Your apps > "TAiM Web App" > SDK setup and configuration.
// This web config is not a secret (it is safe in the frontend). Never put Admin SDK / service-account keys here.
export const firebaseConfig = {
    apiKey: "AIzaSyC0rCKpaIfjfsINE1HbwqFmpxQ0Xehzmvs",
    authDomain: "taim---task-ai-management.firebaseapp.com",
    projectId: "taim---task-ai-management",
    storageBucket: "taim---task-ai-management.firebasestorage.app",
    messagingSenderId: "215421609011",
    appId: "1:215421609011:web:abae6b56326187f24caf46"
};
// =====================================================

export const isConfigured = !Object.values(firebaseConfig).some(v => String(v).startsWith('PASTE_'));
// Initialize once, even if this module is evaluated again.
export const app = getApps().length ? getApp() : initializeApp(firebaseConfig);
export const auth = getAuth(app);
export { createUserWithEmailAndPassword, signInWithEmailAndPassword, updateProfile, GoogleAuthProvider, signInWithPopup, signOut, onAuthStateChanged };