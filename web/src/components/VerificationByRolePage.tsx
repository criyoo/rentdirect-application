import { Navigate } from 'react-router-dom'
import { useAuth } from '@/hooks/useAuth'
import TenantVerificationPage from '@/pages/tenants/TenantVerificationPage'

// /verify is the canonical verification URL used in emails and shared links.
// Route each role to its own verification page so PIOs never land on the
// tenant/landlord verification flows.
export default function VerificationByRolePage() {
    const { user, isRestoring } = useAuth()

    if (isRestoring) {
        return (
            <div className="min-h-screen bg-gray-50 flex items-center justify-center">
                <div className="text-center">
                    <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-600 mx-auto mb-4"></div>
                    <p className="text-gray-600">Verifying authentication...</p>
                </div>
            </div>
        )
    }

    if (!user) return <Navigate to="/login" replace />
    if (user.role === 'agent') return <Navigate to="/agents/verification" replace />
    if (user.role === 'landlord') return <Navigate to="/landlord/verification" replace />
    if (user.role === 'admin') return <Navigate to="/admin/verification" replace />
    return <TenantVerificationPage />
}
