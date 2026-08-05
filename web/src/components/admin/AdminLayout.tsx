import { ReactNode } from 'react'
import { Link, useNavigate, useLocation } from 'react-router-dom'
import { useAuth } from '@/hooks/useAuth'
import BrandLogo from '@/components/BrandLogo'

interface AdminLayoutProps
{
    children: ReactNode
}

export default function AdminLayout({ children }: AdminLayoutProps)
{
    const { user, logout } = useAuth()
    const navigate = useNavigate()
    const location = useLocation()

    // Check if user is admin
    if (!user || user.role !== 'admin')
    {
        return (
            <div className="min-h-screen bg-gray-50 flex flex-col justify-center py-12 sm:px-6 lg:px-8">
                <div className="sm:mx-auto sm:w-full sm:max-w-md">
                    <div className="text-center">
                        <h1 className="text-2xl font-bold text-red-600">Access Denied</h1>
                        <p className="text-gray-600 mt-2">You don't have permission to access the admin area.</p>
                        <Link
                            to="/admin/login"
                            className="mt-4 inline-block text-purple-600 hover:text-purple-500"
                        >
                            Go to Admin Login
                        </Link>
                    </div>
                </div>
            </div>
        )
    }

    const handleLogout = async () =>
    {
        await logout()
        navigate('/admin/login')
    }

    const isActiveRoute = (path: string) =>
    {
        return location.pathname === path
    }

    return (
        <div className="min-h-screen bg-gray-50">
            {/* Admin Header */}
            <header className="fixed inset-x-0 top-0 z-[100] bg-white/95 shadow-sm border-b border-gray-200 backdrop-blur-md">
                <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
                    <div className="flex justify-between items-center h-16">
                        {/* Admin Logo */}
                        <div className="flex items-center space-x-4">
                            <Link to="/admin/dashboard" aria-label="RentDirect admin dashboard" className="flex items-center space-x-3">
                                <BrandLogo alt="RentDirect Admin" className="h-12 w-24 rounded-md bg-white p-1" />
                                <span className="text-sm font-semibold uppercase tracking-[0.18em] text-gray-600">
                                    Admin
                                </span>
                            </Link>
                        </div>

                        {/* Admin Navigation */}
                        <nav className="hidden md:flex items-center space-x-8">
                            <Link
                                to="/admin/dashboard"
                                className={`px-3 py-2 rounded-md text-sm font-medium transition-colors duration-200 ${isActiveRoute('/admin/dashboard')
                                    ? 'bg-purple-100 text-purple-700'
                                    : 'text-gray-600 hover:text-purple-600 hover:bg-purple-50'
                                    }`}
                            >
                                Dashboard
                            </Link>
                            <Link
                                to="/admin/verification"
                                className={`px-3 py-2 rounded-md text-sm font-medium transition-colors duration-200 ${isActiveRoute('/admin/verification')
                                    ? 'bg-purple-100 text-purple-700'
                                    : 'text-gray-600 hover:text-purple-600 hover:bg-purple-50'
                                    }`}
                            >
                                Verifications
                            </Link>
                            <Link
                                to="/admin/users"
                                className={`px-3 py-2 rounded-md text-sm font-medium transition-colors duration-200 ${isActiveRoute('/admin/users')
                                    ? 'bg-purple-100 text-purple-700'
                                    : 'text-gray-600 hover:text-purple-600 hover:bg-purple-50'
                                    }`}
                            >
                                Users
                            </Link>
                            <Link
                                to="/admin/listings"
                                className={`px-3 py-2 rounded-md text-sm font-medium transition-colors duration-200 ${isActiveRoute('/admin/listings')
                                    ? 'bg-purple-100 text-purple-700'
                                    : 'text-gray-600 hover:text-purple-600 hover:bg-purple-50'
                                    }`}
                            >
                                Listings
                            </Link>
                            <Link
                                to="/admin/settings"
                                className={`px-3 py-2 rounded-md text-sm font-medium transition-colors duration-200 ${isActiveRoute('/admin/settings')
                                    ? 'bg-purple-100 text-purple-700'
                                    : 'text-gray-600 hover:text-purple-600 hover:bg-purple-50'
                                    }`}
                            >
                                Settings
                            </Link>
                        </nav>

                        {/* Admin User Menu */}
                        <div className="flex items-center space-x-4">
                            <div className="text-right">
                                <div className="text-sm font-medium text-gray-900">{user.name}</div>
                                <div className="text-xs text-gray-500">Administrator</div>
                            </div>
                            <button
                                onClick={handleLogout}
                                className="px-3 py-2 text-sm font-medium text-red-600 hover:text-red-700 hover:bg-red-50 rounded-md transition-colors duration-200"
                            >
                                Logout
                            </button>
                        </div>
                    </div>
                </div>
            </header>

            {/* Admin Content */}
            <main className="flex-1 pt-16">
                {children}
            </main>

        </div>
    )
}
