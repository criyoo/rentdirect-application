import { Navigate } from 'react-router-dom'
import RegisterPage from '@/pages/shared/auth/RegisterPage'
import AgentPublicHeader from '@/components/agent/AgentPublicHeader'
import { useAuth } from '@/hooks/useAuth'

export default function AgentRegistrationPage() {
    const { user, isRestoring } = useAuth()

    if (isRestoring) {
        return (
            <div className="agent-theme min-h-screen bg-gradient-to-br from-emerald-50 via-white to-green-50 flex items-center justify-center">
                <div className="text-center">
                    <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-emerald-600 mx-auto mb-4"></div>
                    <p className="text-gray-600">Verifying authentication...</p>
                </div>
            </div>
        )
    }

    // Signed-in tenants and landlords cannot view the agent sign-up page.
    if (user) {
        const dashboards = {
            agent: '/agents/dashboard',
            landlord: `/dashboard/landlord/${user.id}`,
            tenant: `/dashboard/tenant/${user.id}`,
            admin: '/admin/dashboard',
        } as const
        return <Navigate to={dashboards[user.role]} replace />
    }

    return (
        <>
            <AgentPublicHeader current="register" />
            <RegisterPage lockedRole="agent" />
        </>
    )
}
