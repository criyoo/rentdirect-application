import { Link } from 'react-router-dom'
import { useAuth } from '@/hooks/useAuth'
import BrandLogo from '@/components/BrandLogo'
import {
    HiArrowRight,
    HiBadgeCheck,
    HiLocationMarker,
    HiMail,
    HiSearch,
    HiShieldCheck,
    HiUserGroup,
} from 'react-icons/hi'

const browseLinks = [
    { label: 'Home', href: '/' },
    { label: 'About', href: '/about' },
    { label: 'How it works', href: '/how-it-works' },
    { label: 'Search', href: '/search' },
]

const footerHighlights = [
    {
        label: 'Verified listings',
        description: 'Browse homes backed by a cleaner trust layer.',
        icon: HiBadgeCheck,
    },
    {
        label: 'Direct comms',
        description: 'Move from search to enquiry without middlemen.',
        icon: HiUserGroup,
    },
    {
        label: 'Clear payments',
        description: 'Track rental steps and billing in one workflow.',
        icon: HiShieldCheck,
    },
]

export default function Footer() {
    const { user } = useAuth()

    const dashboardPath = user?.id
        ? user.role === 'landlord'
            ? `/dashboard/landlord/${user.id}`
            : `/dashboard/tenant/${user.id}`
        : '/register'

    const accountLinks = user?.id
        ? [
            { label: 'Dashboard', href: dashboardPath },
            { label: 'Profile', href: `/profile/${user.id}` },
            { label: 'Saved homes', href: '/favourites' },
            { label: 'Feedback', href: '/feedback' },
            { label: 'Complaint', href: '/complaint' },
            { label: 'Issues', href: '/issues' },
            { label: 'Settings', href: '/dashboard/settings' },
        ]
        : [
            { label: 'Login', href: '/login' },
            { label: 'Register', href: '/register' },
            { label: 'Forgot password', href: '/forgot-password' },
            { label: 'Issues', href: '/issues' },
            { label: 'Complaint', href: '/complaint' },
            // { label: 'Saved homes', href: '/favourites' },
        ]

    const landlordLinks = user?.id
        ? [
            { label: 'Enquiries', href: '/enquiries' },
            { label: 'Billings', href: '/billing' },
            { label: 'Feedback', href: '/feedback' },
            { label: 'Community Chat', href: '/community-chat' },
            { label: 'Identity checks', href: '/landlord/verification' },
            { label: 'Featured properties', href: '/dashboard/featured-properties' },
        ] : [
            { label: 'List property', href: '/listings/new' },
            { label: 'Identity checks', href: '/landlord/verification' },
            { label: 'Featured placements', href: '/dashboard/featured-properties' },
            { label: 'Feedback', href: '/feedback' },
        ]

    return (
        <footer className="border-t border-slate-800 bg-slate-950 text-white">
            <div className="bg-[linear-gradient(135deg,rgba(37,99,235,0.18),rgba(15,23,42,0)_42%,rgba(147,51,234,0.18))]">
                <div className="mx-auto max-w-7xl px-4 py-12 sm:px-6 lg:px-8">
                    <div className="grid items-start gap-12 border-b border-white/10 pb-10 lg:grid-cols-[minmax(0,1.15fr)_minmax(0,1.35fr)]">
                        <div className="flex h-full flex-col gap-6">
                            <Link to="/" aria-label="RentDirect home" className="inline-flex items-center">
                                <BrandLogo className="h-24 w-36 shrink-0 rounded-lg bg-white p-1" />
                            </Link>
                            {/* <span className="inline-flex gap-3 w-fit items-center rounded-full border border-blue-400/30 bg-blue-500/10 px-3 py-1 text-xs font-semibold uppercase tracking-[0.2em] text-blue-100">
                                Direct landlord rentals
                            </span> */}
                            <div className="space-y-4">
                                <p className="max-w-xl font-semibold leading-tight text-white sm:text-xl">
                                    Search, verify, and rent with a cleaner path from landlord to tenant.
                                </p>
                                {/* <p className="leading-6 text-slate-300 sm:text-base">
                                    RentDirect keeps property discovery, verification, and payments simple and transparent, its a platform built for serious renters and landlords.
                                </p> */}
                            </div>

                            <div className="flex flex-col gap-3 sm:flex-row">
                                <Link
                                    to="/search"
                                    className="inline-flex items-center justify-center gap-2 rounded-lg bg-blue-600 px-3 py-2 text-sm font-semibold text-white shadow-lg shadow-blue-950/40 hover:bg-blue-500"
                                >
                                    Search homes
                                    <HiArrowRight className="h-3 w-3" />
                                </Link>
                                <a
                                    href="mailto:info@rentdirect.homes"
                                    className="inline-flex items-center justify-center gap-2 rounded-lg border border-white/15 bg-white/5 px-5 py-3 text-sm font-semibold text-slate-100 hover:border-blue-300/40 hover:bg-white/10"
                                >
                                    <HiMail className="h-3 w-3 text-blue-200" />
                                    info@rentdirect.homes
                                </a>
                            </div>

                            <div className="mt-auto grid auto-rows-fr items-stretch gap-3 sm:grid-cols-3">
                                {footerHighlights.map((item) => {
                                    const Icon = item.icon

                                    return (
                                        <div key={item.label} className="flex h-full min-h-36 flex-col rounded-lg border border-white/10 bg-white/5 p-4">
                                            <span className="mb-3 inline-flex h-9 w-9 items-center justify-center rounded-lg bg-blue-500/15 text-blue-100">
                                                <Icon className="h-5 w-5" />
                                            </span>
                                            <p className="text-sm font-semibold text-white">{item.label}</p>
                                            <p className="mt-auto pt-2 text-sm leading-5 text-slate-300">{item.description}</p>
                                        </div>
                                    )
                                })}
                            </div>
                        </div>

                        <div className="grid items-start gap-10 sm:grid-cols-2 xl:grid-cols-[repeat(3,minmax(0,1fr))]">
                            <nav aria-label="Browse">
                                <p className="text-xs font-semibold uppercase tracking-[0.22em] text-blue-200">Browse</p>
                                <ul className="mt-4 space-y-3 text-sm text-slate-300">
                                    {browseLinks.map((link) => (
                                        <li key={link.label}>
                                            <Link className="transition hover:text-white" to={link.href}>
                                                {link.label}
                                            </Link>
                                        </li>
                                    ))}
                                </ul>
                            </nav>

                            <nav aria-label="Account">
                                <p className="text-xs font-semibold uppercase tracking-[0.22em] text-blue-200">Account</p>
                                <ul className="mt-4 space-y-3 text-sm text-slate-300">
                                    {accountLinks.map((link) => (
                                        <li key={link.label}>
                                            <Link className="transition hover:text-white" to={link.href}>
                                                {link.label}
                                            </Link>
                                        </li>
                                    ))}
                                </ul>
                            </nav>

                            <nav aria-label="Landlords">
                                <p className="text-xs font-semibold uppercase tracking-[0.22em] text-blue-200">Landlords</p>
                                <ul className="mt-4 space-y-3 text-sm text-slate-300">
                                    {landlordLinks.map((link) => (
                                        <li key={link.label}>
                                            <Link className="transition hover:text-white" to={link.href}>
                                                {link.label}
                                            </Link>
                                        </li>
                                    ))}
                                </ul>
                            </nav>

                            <div className="min-w-0 sm:col-span-2 xl:col-span-3">
                                <p className="text-xs font-semibold uppercase tracking-[0.22em] text-blue-200">Support</p>
                                <div className="mt-8 grid auto-rows-fr items-stretch gap-3 md:grid-cols-3">
                                    <a
                                        href="mailto:info@rentdirect.homes"
                                        className="flex h-full min-h-36 flex-col rounded-lg border border-white/10 bg-white/5 p-4 text-sm text-slate-300 hover:border-blue-300/40 hover:bg-white/10"
                                    >
                                        <span className="mb-3 inline-flex h-9 w-9 items-center justify-center rounded-lg bg-blue-500/15 text-blue-100">
                                            <HiMail className="h-5 w-5" />
                                        </span>
                                        <span className="mt-auto block">
                                            <span className="block font-semibold text-white">Email support</span>
                                            <span className="mt-1 block">support@rentdirect.homes</span>
                                        </span>
                                    </a>

                                    <div className="flex h-full min-h-36 flex-col rounded-lg border border-white/10 bg-white/5 p-4 text-sm text-slate-300">
                                        <span className="mb-3 inline-flex h-9 w-9 items-center justify-center rounded-lg bg-blue-500/15 text-blue-100">
                                            <HiLocationMarker className="h-5 w-5" />
                                        </span>
                                        <span className="mt-auto block">
                                            <span className="block font-semibold text-white">Coverage</span>
                                            <span className="mt-1 block">Verified homes and renters across Nigeria.</span>
                                        </span>
                                    </div>

                                    <Link
                                        to="/verify"
                                        className="flex h-full min-h-36 flex-col rounded-lg border border-white/10 bg-white/5 p-4 text-sm text-slate-300 hover:border-blue-300/40 hover:bg-white/10"
                                    >
                                        <span className="mb-3 inline-flex h-9 w-9 items-center justify-center rounded-lg bg-blue-500/15 text-blue-100">
                                            <HiSearch className="h-5 w-5" />
                                        </span>
                                        <span className="mt-auto block">
                                            <span className="block font-semibold text-white">Verification flow</span>
                                            <span className="mt-1 block">Complete checks before you enquire or list.</span>
                                        </span>
                                    </Link>
                                </div>
                            </div>
                        </div>
                    </div>

                    <div className="flex flex-col gap-3 pt-6 text-sm text-slate-400 md:flex-row md:items-center md:justify-between">
                        <p>Copyright {new Date().getFullYear()} RentDirect. All rights reserved.</p>
                        <div className="flex flex-wrap items-center gap-x-5 gap-y-2">
                            <span className="inline-flex items-center gap-2">
                                <HiBadgeCheck className="h-4 w-4 text-blue-200" />
                                Verified listings
                            </span>
                            <span className="inline-flex items-center gap-2">
                                <HiUserGroup className="h-4 w-4 text-blue-200" />
                                Direct landlord contact
                            </span>
                            <span className="inline-flex items-center gap-2">
                                <HiShieldCheck className="h-4 w-4 text-blue-200" />
                                Secure rent workflow
                            </span>
                        </div>
                    </div>
                </div>
            </div>
        </footer>
    )
}
