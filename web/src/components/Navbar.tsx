import { Link, NavLink, useLocation } from 'react-router-dom'
import { useAuth } from '@/hooks/useAuth'
import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { api } from '@/lib/api'
import { User } from '@/types'
import BrandLogo from '@/components/BrandLogo'
import {
    HiMenu,
    HiX,
    HiSearch,
    HiPlus,
    HiUser,
    HiLogout,
    HiHome,
    HiOfficeBuilding,
    HiInformationCircle,
    HiLightBulb,
    HiLogin,
} from 'react-icons/hi'

export default function Navbar() {
    const { user, logout } = useAuth()
    const location = useLocation()
    const [isMobileMenuOpen, setIsMobileMenuOpen] = useState(false)
    const registrationRole = location.pathname === '/register'
        ? new URLSearchParams(location.search).get('role')
        : null
    const isTenantRegistrationActive = registrationRole === 'tenant'
    const isLandlordRegistrationActive = registrationRole === 'landlord'

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

    const navIconClassName = "h-6 w-6 transition-transform duration-300 group-hover:scale-120"
    const navMenuClassName = ({ isActive }: { isActive: boolean }) => `group flex items-center gap-3 rounded-xl px-4 py-3 font-semibold transition-all duration-300 hover:-translate-y-0.5 hover:bg-indigo-50 hover:text-indigo-700 hover:shadow-sm active:scale-[0.98] ${isActive ? 'bg-indigo-50 text-indigo-700 shadow-sm' : 'text-slate-700'}`




    return (
        <header className="fixed inset-x-0 top-0 z-[100] bg-white/80 backdrop-blur-xl shadow-[0_4px_18px_rgba(15,23,42,0.05)]">
            <div className="container-modern">
                <div className="flex items-center justify-between h-22">
                    {/* Logo */}
                    <Link to="/" aria-label="RentDirect home" className="flex shrink-0 items-center group">
                        <BrandLogo className="h-40 w-40" />
                    </Link>

                    {/* Desktop Navigation */}
                    <nav className="hidden md:flex items-center gap-3">
                        <NavLink
                            to="/about"
                            className={({ isActive }) => `group inline-flex items-center gap-1 rounded-xl px-6 py-2 text-sm font-semibold transition-all duration-300 hover:-translate-y-1.0 hover:bg-indigo-100 hover:text-purple-900 hover:shadow-sm active:scale-95 ${isActive ? 'bg-indigo-50 text-indigo-700 shadow-sm' : 'text-slate-700'}`}
                        >
                            <HiInformationCircle className={navIconClassName} />
                            About
                        </NavLink>

                        {authenticatedUser?.id ? <NavLink
                            to="/how-it-works"
                            className={({ isActive }) => `group inline-flex items-center gap-1 rounded-xl px-6 py-2 text-sm font-semibold transition-all duration-300 hover:-translate-y-0.5 hover:bg-indigo-50 hover:text-indigo-700 hover:shadow-sm active:scale-95 ${isActive ? 'bg-indigo-50 text-indigo-700 shadow-sm' : 'text-slate-700'}`}
                        >
                            <HiLightBulb className={navIconClassName} />
                            How it works
                        </NavLink> : null}

                        <NavLink
                            to="/search"
                            className={({ isActive }) => `group inline-flex items-center gap-1 rounded-xl px-3 py-2 text-sm font-semibold transition-all duration-300 hover:-translate-y-0.5 hover:bg-indigo-50 hover:text-indigo-700 hover:shadow-sm active:scale-95 ${isActive ? 'bg-indigo-50 text-indigo-700 shadow-sm' : 'text-slate-700'}`}
                        >
                            <HiSearch className={navIconClassName} />
                            <span>Search</span>
                        </NavLink>

                        {authenticatedUser && authenticatedUser.role === 'landlord' && (
                            <NavLink
                                to="/listings/new"
                                className={({ isActive }) => `group inline-flex items-center gap-2 rounded-xl px-3 py-2 text-sm font-semibold transition-all duration-300 hover:-translate-y-0.5 hover:bg-indigo-50 hover:text-indigo-700 hover:shadow-sm active:scale-95 ${isActive ? 'bg-indigo-50 text-indigo-700 shadow-sm' : 'text-slate-700'}`}
                            >
                                <HiPlus className="h-6 w-6 transition-transform duration-300 group-hover:rotate-90" />
                                <span>Add Listing</span>
                            </NavLink>
                        )}

                        {authenticatedUser && authenticatedUser.id ? (
                            <div className="flex items-center gap-3">
                                {!isOnDashboard && (
                                    <NavLink
                                        to={authenticatedUser.role === 'landlord' ? `/dashboard/landlord/${authenticatedUser.id}` : `/dashboard/tenant/${authenticatedUser.id}`}
                                        className="group btn gap-2 bg-gradient-to-r from-slate-700 to-indigo-700 text-sm font-semibold text-white shadow-sm transition-all duration-300 hover:-translate-y-0.5 hover:from-indigo-600 hover:to-purple-600 hover:shadow-lg active:scale-95"
                                    >
                                        <HiUser className={navIconClassName} />
                                        Dashboard
                                        {/* {authenticatedUser.role === 'landlord' ? 'Landlord Dashboard' : 'Tenant Dashboard'} */}
                                    </NavLink>
                                )}

                                <button
                                    onClick={handleLogout}
                                    className="group btn gap-2 bg-gradient-to-r from-rose-600 to-red-600 text-sm font-semibold text-white shadow-sm transition-all duration-300 hover:-translate-y-0.5 hover:from-red-600 hover:to-rose-700 hover:shadow-lg active:scale-95"
                                >
                                    <HiLogout className="h-6 w-6 transition-transform duration-300 group-hover:translate-x-0.5" />
                                    Logout
                                </button>
                            </div>
                        ) : (
                            <div className="flex items-center gap-3">
                                <NavLink
                                    to="/login"
                                    className={({ isActive }) => `group inline-flex items-center gap-2 rounded-xl px-3 py-2 text-sm font-semibold transition-all duration-300 hover:-translate-y-0.5 hover:bg-indigo-50 hover:text-indigo-700 hover:shadow-sm active:scale-95 ${isActive ? 'bg-indigo-50 text-indigo-700 shadow-sm' : 'text-slate-700'}`}
                                >
                                    <HiLogin className="h-6 w-6 transition-transform duration-300 group-hover:translate-x-0.5" />
                                    Login
                                </NavLink>
                                <NavLink
                                    to="/register?role=tenant"
                                    className={`group btn relative gap-2 overflow-hidden text-sm font-semibold shadow-sm transition-all duration-300 hover:-translate-y-0.5 hover:shadow-lg active:translate-y-0 active:scale-95 ${isTenantRegistrationActive
                                        ? 'bg-indigo-800 text-white shadow-md'
                                        : 'bg-indigo-50 text-indigo-700 hover:bg-indigo-100'
                                        }`}
                                >
                                    <HiHome className="h-6 w-6 transition-transform duration-300 group-hover:-translate-y-0.5 group-hover:scale-120" />
                                    <span>Find a home</span>
                                </NavLink>
                                <NavLink
                                    to="/register?role=landlord"
                                    className={`group btn relative gap-2 overflow-hidden text-sm font-semibold transition-all duration-300 hover:-translate-y-0.5 hover:shadow-lg active:translate-y-0 active:scale-95 ${isLandlordRegistrationActive
                                        ? 'bg-purple-700 text-white shadow-md'
                                        : 'bg-purple-50 text-purple-700 hover:bg-purple-100'
                                        }`}
                                >
                                    <HiOfficeBuilding className="h-6 w-6 transition-transform duration-300 group-hover:-translate-y-0.5 group-hover:scale-120" />
                                    <span>List a Property</span>
                                </NavLink>
                            </div>
                        )}
                    </nav>

                    {/* Mobile menu button */}
                    <button
                        type="button"
                        onClick={() => setIsMobileMenuOpen(!isMobileMenuOpen)}
                        aria-label={isMobileMenuOpen ? 'Close navigation menu' : 'Open navigation menu'}
                        aria-expanded={isMobileMenuOpen}
                        className={`group rounded-xl p-3 shadow-sm transition-all duration-300 hover:-translate-y-0.5 hover:shadow-md active:scale-95 md:hidden ${isMobileMenuOpen
                            ? 'bg-indigo-700 text-white rotate-0'
                            : 'bg-white/80 text-gray-600 hover:bg-indigo-50 hover:text-indigo-700'
                            }`}
                    >
                        {isMobileMenuOpen ? (
                            <HiX className="h-6 w-6 rotate-90 transition-transform duration-300" />
                        ) : (
                            <HiMenu className="h-6 w-6 transition-transform duration-300 group-hover:scale-110" />
                        )}
                    </button>
                </div>

                {/* Mobile Navigation */}
                {isMobileMenuOpen && (
                    <div className="md:hidden py-4 border-t border-gray-200 animate-slide-up">
                        <div className="flex flex-col gap-3">
                            <NavLink
                                to="/about"
                                className={navMenuClassName}
                                onClick={() => setIsMobileMenuOpen(false)}
                            >
                                <HiInformationCircle className="h-6 w-6 transition-transform duration-300 group-hover:scale-110" />
                                <span>About</span>
                            </NavLink>

                            {authenticatedUser?.id ? (
                                <NavLink
                                    to="/how-it-works"
                                    className={navMenuClassName}
                                    onClick={() => setIsMobileMenuOpen(false)}
                                >
                                    <HiLightBulb className="h-6 w-6 transition-transform duration-300 group-hover:scale-110" />
                                    <span>How it works</span>
                                </NavLink>
                            ) : null}

                            <NavLink
                                to="/search"
                                className={navMenuClassName}
                                onClick={() => setIsMobileMenuOpen(false)}
                            >
                                <HiSearch className="h-6 w-6 transition-transform duration-300 group-hover:scale-110" />
                                <span>Search</span>
                            </NavLink>

                            {authenticatedUser && authenticatedUser.role === 'landlord' && (
                                <NavLink
                                    to="/listings/new"
                                    className={navMenuClassName}
                                    onClick={() => setIsMobileMenuOpen(false)}
                                >
                                    <HiPlus className="h-6 w-6 transition-transform duration-300 group-hover:rotate-90" />
                                    <span>Add Listing</span>
                                </NavLink>
                            )}

                            {authenticatedUser && authenticatedUser.id ? (
                                <div className="flex flex-col gap-3">
                                    {!isOnDashboard && (
                                        <NavLink
                                            to={authenticatedUser.role === 'landlord' ? `/dashboard/landlord/${authenticatedUser.id}` : `/dashboard/tenant/${authenticatedUser.id}`}
                                            className="group flex items-center gap-3 rounded-xl bg-gradient-to-r from-slate-700 to-indigo-700 px-4 py-3 font-semibold text-white shadow-sm transition-all duration-300 hover:-translate-y-0.5 hover:from-indigo-600 hover:to-purple-600 hover:shadow-md active:scale-[0.98]"
                                            onClick={() => setIsMobileMenuOpen(false)}
                                        >
                                            <HiUser className="h-6 w-6 transition-transform duration-300 group-hover:scale-110" />
                                            <span>Dashboard</span>
                                        </NavLink>
                                    )}

                                    <button
                                        onClick={handleLogout}
                                        className="group flex w-full items-center gap-3 rounded-xl bg-gradient-to-r from-rose-600 to-red-600 px-4 py-3 font-semibold text-white shadow-sm transition-all duration-300 hover:-translate-y-0.5 hover:from-red-600 hover:to-rose-700 hover:shadow-md active:scale-[0.98]"
                                    >
                                        <HiLogout className="h-6 w-6 transition-transform duration-300 group-hover:translate-x-0.5" />
                                        <span>Logout</span>
                                    </button>
                                </div>
                            ) : (
                                <div className="flex flex-col gap-3">
                                    <NavLink
                                        to="/login"
                                        className={navMenuClassName}
                                        onClick={() => setIsMobileMenuOpen(false)}
                                    >
                                        <HiLogin className="h-6 w-6 transition-transform duration-300 group-hover:translate-x-0.5" />
                                        <span>Login</span>
                                    </NavLink>

                                    <NavLink
                                        to="/register?role=tenant"
                                        onClick={() => setIsMobileMenuOpen(false)}
                                        className={`group flex items-center gap-3 rounded-xl px-4 py-3 font-semibold shadow-sm transition-all duration-300 hover:-translate-y-0.5 hover:shadow-md active:scale-[0.98] ${isTenantRegistrationActive
                                            ? 'bg-indigo-600 text-white shadow-md'
                                            : 'bg-indigo-100 text-indigo-700 hover:bg-indigo-400'
                                            }`}
                                    >
                                        <HiHome className="h-6 w-6 transition-transform duration-300 group-hover:-translate-y-0.5 group-hover:scale-120" />
                                        <span>Find a home</span>
                                    </NavLink>

                                    <NavLink
                                        to="/register?role=landlord"
                                        onClick={() => setIsMobileMenuOpen(false)}
                                        className={`group flex items-center gap-3 rounded-xl px-4 py-3 font-semibold shadow-sm transition-all duration-300 hover:-translate-y-0.5 hover:shadow-md active:scale-[0.98] ${isLandlordRegistrationActive
                                            ? 'bg-purple-600 text-white shadow-md'
                                            : 'bg-purple-50 text-purple-700 hover:bg-purple-400'
                                            }`}
                                    >
                                        <HiOfficeBuilding className="h-6 w-6 transition-transform duration-300 group-hover:-translate-y-0.5 group-hover:scale-120" />
                                        <span>List a Property</span>
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
