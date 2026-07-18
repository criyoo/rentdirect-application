import { Navigate } from 'react-router-dom'
import { useAuth } from '@/hooks/useAuth'

interface ProtectedRouteProps
{
    children: React.ReactNode
    requiredRoles?: ('tenant' | 'landlord' | 'admin')[]
}

export default function ProtectedRoute({ children, requiredRoles }: ProtectedRouteProps)
{
    const { user, isRestoring } = useAuth()

    if (isRestoring)
    {
        return (
            <div className="min-h-screen bg-gray-50 flex items-center justify-center">
                <div className="text-center">
                    <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-600 mx-auto mb-4"></div>
                    <p className="text-gray-600">Verifying authentication...</p>
                </div>
            </div>
        )
    }

    if (!user)
    {
        return <Navigate to="/login" replace />
    }

    if (requiredRoles && !requiredRoles.includes(user.role))
    {
        return <Navigate to="/" replace />
    }

    return <>{children}</>
}
