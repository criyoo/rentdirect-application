// Central feature flags for optional platform features.
// Set VITE_SUBSCRIPTIONS_ENABLED=true in the environment (or change the
// fallback below) to re-enable subscription billing across the app.
export const SUBSCRIPTIONS_ENABLED = import.meta.env.VITE_SUBSCRIPTIONS_ENABLED === 'true'
