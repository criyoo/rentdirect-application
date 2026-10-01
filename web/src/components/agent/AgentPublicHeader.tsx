import { Link } from 'react-router-dom'
import { HiInformationCircle, HiLightBulb, HiLogin, HiUser } from 'react-icons/hi'

import BrandLogo from '@/components/BrandLogo'
import { useAuth } from '@/hooks/useAuth'

export type AgentPublicPage = 'home' | 'about' | 'how-it-works' | 'login' | 'register'

const NAV_ITEMS = [
    { key: 'about', to: '/agents/about', label: 'About', Icon: HiInformationCircle },
    { key: 'how-it-works', to: '/agents/how-it-works', label: 'How it works', Icon: HiLightBulb },
    { key: 'login', to: '/agents/login', label: 'Login', Icon: HiLogin },
    { key: 'register', to: '/agents/register', label: 'Become a PIO', Icon: HiUser, primary: true },
] as const

const DASHBOARD_PATHS = {
    agent: '/agents/dashboard',
    landlord: '/dashboard/landlord',
    tenant: '/dashboard/tenant',
    admin: '/admin/dashboard',
} as const

export default function AgentPublicHeader({ current }: { current: AgentPublicPage }) {
    const { user } = useAuth()

    const items = NAV_ITEMS.filter((item) => item.key !== current)
        .filter((item) => !user || (item.key !== 'login' && item.key !== 'register'))

    const dashboardPath = user
        ? user.role === 'landlord'
            ? `${DASHBOARD_PATHS.landlord}/${user.id}`
            : user.role === 'tenant'
                ? `${DASHBOARD_PATHS.tenant}/${user.id}`
                : DASHBOARD_PATHS[user.role]
        : null

    return (
        <header className="fixed inset-x-0 top-0 z-[100] bg-white/80 backdrop-blur-xl shadow-[0_4px_18px_rgba(15,23,42,0.05)]">
            <div className="container-modern">
                <div className="flex items-center justify-between h-22">
                    <Link to="/agents" aria-label="RentDirect Inspection Officer" className="flex shrink-0 items-center">
                        <BrandLogo className="h-40 w-40" />
                    </Link>

                    <nav className="flex items-center gap-3">
                        {items.map(({ key, to, label, Icon, ...item }) => {
                            const primary = 'primary' in item && item.primary
                            return primary ? (
                                <Link
                                    key={key}
                                    to={to}
                                    className="group btn relative gap-2 overflow-hidden bg-emerald-600 text-sm font-semibold text-white shadow-sm transition-all duration-300 hover:-translate-y-0.5 hover:bg-emerald-700 hover:shadow-lg active:scale-95"
                                >
                                    <Icon className="h-6 w-6 transition-transform duration-300 group-hover:-translate-y-0.5 group-hover:scale-120" />
                                    <span>{label}</span>
                                </Link>
                            ) : (
                                <Link
                                    key={key}
                                    to={to}
                                    className="group inline-flex items-center gap-2 rounded-xl px-3 py-2 text-sm font-semibold text-emerald-900 transition-all duration-300 hover:-translate-y-0.5 hover:bg-emerald-50 hover:text-emerald-700 hover:shadow-sm sm:px-6"
                                >
                                    <Icon className="h-6 w-6 transition-transform duration-300 group-hover:scale-120" />
                                    {label}
                                </Link>
                            )
                        })}
                        {user && dashboardPath && (
                            <Link
                                to={dashboardPath}
                                className="group btn relative gap-2 overflow-hidden bg-emerald-600 text-sm font-semibold text-white shadow-sm transition-all duration-300 hover:-translate-y-0.5 hover:bg-emerald-700 hover:shadow-lg active:scale-95"
                            >
                                <HiUser className="h-6 w-6 transition-transform duration-300 group-hover:-translate-y-0.5 group-hover:scale-120" />
                                <span>Dashboard</span>
                            </Link>
                        )}
                    </nav>
                </div>
            </div>
        </header>
    )
}
