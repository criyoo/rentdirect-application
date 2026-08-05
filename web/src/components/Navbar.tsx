import { Link, NavLink, useLocation } from 'react-router-dom'
import { useAuth } from '@/hooks/useAuth'
import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { api } from '@/lib/api'
import { User } from '@/types'
import BrandLogo from '@/components/BrandLogo'
import { HiMenu, HiX, HiSearch, HiPlus, HiUser, HiLogout } from 'react-icons/hi'

export default function Navbar() {
    const { user, logout } = useAuth()
    const location = useLocation()
    const [isMobileMenuOpen, setIsMobileMenuOpen] = useState(false)

    // Verify authentication with backend if user is not in localStorage
    const { data: backendUser } = useQuery({
        queryKey: ['users', 'me'],
        queryFn: async () => (await api.get<User>('/users/me')).data,
        enabled: !user, // Only fetch if user is not in localStorage
        retry: false,
    })

    // Use user from localStorage or backend
    const authenticatedUser = user || backendUser

    // Check if user is currently on their dashboard page
    const isOnDashboard = authenticatedUser && authenticatedUser.id && (
        (authenticatedUser.role === 'landlord' && location.pathname.startsWith(`/dashboard/landlord/${authenticatedUser.id}`)) ||
        (authenticatedUser.role === 'tenant' && location.pathname.startsWith(`/dashboard/tenant/${authenticatedUser.id}`))
    )

    const handleLogout = async () => {
        await logout()
        setIsMobileMenuOpen(false)
    }

    return (
        <header className="fixed inset-x-0 top-0 z-[100] bg-white/90 backdrop-blur-md border-b border-gray-200/50 shadow-sm">
            <div className="container-modern">
                <div className="flex items-center justify-between h-20">
                    {/* Logo */}
                    <Link to="/" aria-label="RentDirect home" className="flex shrink-0 items-center group">
                        <BrandLogo className="h-40 w-40" />
                    </Link>

                    {/* Desktop Navigation */}
                    <nav className="hidden md:flex items-center space-x-8">
                        <NavLink
                            to="/about"
                            className="nav-link hover:text-blue-600 transition-colors duration-200"
                        >
                            About
                        </NavLink>

                        {authenticatedUser?.id ? <NavLink
                            to="/how-it-works"
                            className="nav-link hover:text-blue-600 transition-colors duration-200"
                        >
                            How it works
                        </NavLink> : null}

                        <NavLink
                            to="/search"
                            className="nav-link flex items-center space-x-1 hover:text-blue-600 transition-colors duration-200"
                        >
                            <HiSearch className="w-4 h-4" />
                            <span>Search</span>
                        </NavLink>

                        {authenticatedUser && authenticatedUser.role === 'landlord' && (
                            <NavLink
                                to="/listings/new"
                                className="nav-link flex items-center space-x-1 hover:text-blue-600 transition-colors duration-200"
                            >
                                <HiPlus className="w-4 h-4" />
                                <span>Add Listing</span>
                            </NavLink>
                        )}

                        {authenticatedUser && authenticatedUser.id ? (
                            <div className="flex items-center space-x-4">
                                {!isOnDashboard && (
                                    <NavLink
                                        to={authenticatedUser.role === 'landlord' ? `/dashboard/landlord/${authenticatedUser.id}` : `/dashboard/tenant/${authenticatedUser.id}`}
                                        className="btn btn-outline text-sm"
                                    >
                                        <HiUser className="w-4 h-4 mr-1" />
                                        Dashboard
                                        {/* {authenticatedUser.role === 'landlord' ? 'Landlord Dashboard' : 'Tenant Dashboard'} */}
                                    </NavLink>
                                )}

                                <button
                                    onClick={handleLogout}
                                    className="btn btn-danger text-sm"
                                >
                                    <HiLogout className="w-4 h-4 mr-1" />
                                    Logout
                                </button>
                            </div>
                        ) : (
                            <div className="flex items-center space-x-4">
                                <NavLink
                                    to="/login"
                                    className="nav-link hover:text-blue-600 transition-colors duration-200"
                                >
                                    Login
                                </NavLink>
                                <NavLink
                                    to="/register"
                                    className="btn btn-primary text-sm"
                                >
                                    Sign up
                                </NavLink>
                            </div>
                        )}
                    </nav>

                    {/* Mobile menu button */}
                    <button
                        onClick={() => setIsMobileMenuOpen(!isMobileMenuOpen)}
                        className="md:hidden p-2 rounded-lg text-gray-600 hover:text-gray-900 hover:bg-gray-100 transition-colors duration-200"
                    >
                        {isMobileMenuOpen ? (
                            <HiX className="w-6 h-6" />
                        ) : (
                            <HiMenu className="w-6 h-6" />
                        )}
                    </button>
                </div>

                {/* Mobile Navigation */}
                {isMobileMenuOpen && (
                    <div className="md:hidden py-4 border-t border-gray-200 animate-slide-up">
                        <div className="space-y-4">
                            <NavLink
                                to="/about"
                                className="flex items-center space-x-2 px-4 py-2 text-gray-700 hover:text-blue-600 hover:bg-blue-50 rounded-lg transition-colors duration-200"
                                onClick={() => setIsMobileMenuOpen(false)}
                            >
                                <span>About</span>
                            </NavLink>

                            {authenticatedUser?.id ? (
                                <NavLink
                                    to="/how-it-works"
                                    className="flex items-center space-x-2 px-4 py-2 text-gray-700 hover:text-blue-600 hover:bg-blue-50 rounded-lg transition-colors duration-200"
                                    onClick={() => setIsMobileMenuOpen(false)}
                                >
                                    <span>How it works</span>
                                </NavLink>
                            ) : null}

                            <NavLink
                                to="/search"
                                className="flex items-center space-x-2 px-4 py-2 text-gray-700 hover:text-blue-600 hover:bg-blue-50 rounded-lg transition-colors duration-200"
                                onClick={() => setIsMobileMenuOpen(false)}
                            >
                                <HiSearch className="w-4 h-4" />
                                <span>Search</span>
                            </NavLink>

                            {authenticatedUser && authenticatedUser.role === 'landlord' && (
                                <NavLink
                                    to="/listings/new"
                                    className="flex items-center space-x-2 px-4 py-2 text-gray-700 hover:text-blue-600 hover:bg-blue-50 rounded-lg transition-colors duration-200"
                                    onClick={() => setIsMobileMenuOpen(false)}
                                >
                                    <HiPlus className="w-4 h-4" />
                                    <span>Add Listing</span>
                                </NavLink>
                            )}

                            {authenticatedUser && authenticatedUser.id ? (
                                <div className="space-y-2">
                                    {!isOnDashboard && (
                                        <NavLink
                                            to={authenticatedUser.role === 'landlord' ? `/dashboard/landlord/${authenticatedUser.id}` : `/dashboard/tenant/${authenticatedUser.id}`}
                                            className="flex items-center space-x-2 px-4 py-2 text-gray-700 hover:text-blue-600 hover:bg-blue-50 rounded-lg transition-colors duration-200"
                                            onClick={() => setIsMobileMenuOpen(false)}
                                        >
                                            <HiUser className="w-4 h-4" />
                                            <span>Dashboard</span>
                                        </NavLink>
                                    )}

                                    <button
                                        onClick={handleLogout}
                                        className="w-full flex items-center space-x-2 px-4 py-2 text-red-600 hover:text-red-700 hover:bg-red-50 rounded-lg transition-colors duration-200"
                                    >
                                        <HiLogout className="w-4 h-4" />
                                        <span>Logout</span>
                                    </button>
                                </div>
                            ) : (
                                <div className="space-y-2">
                                    <NavLink
                                        to="/login"
                                        className="flex items-center space-x-2 px-4 py-2 text-gray-700 hover:text-blue-600 hover:bg-blue-50 rounded-lg transition-colors duration-200"
                                        onClick={() => setIsMobileMenuOpen(false)}
                                    >
                                        <span>Login</span>
                                    </NavLink>
                                    <NavLink
                                        to="/register"
                                        className="flex items-center space-x-2 px-4 py-2 bg-blue-600 text-white hover:bg-blue-700 rounded-lg transition-colors duration-200"
                                        onClick={() => setIsMobileMenuOpen(false)}
                                    >
                                        <span>Sign up</span>
                                    </NavLink>
                                </div>
                            )}
                        </div>
                    </div>
                )}
            </div>
        </header>
    )
}
